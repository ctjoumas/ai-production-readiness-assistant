from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import asyncio
import uvicorn
import uuid
from azure.ai.projects import AIProjectClient
from openai import OpenAI
import httpx
import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
from dotenv import load_dotenv
import os
import urllib.parse
# Import prompts - handle both local and Docker environments
try:
    from backend.prompts import (
        get_simple_production_readiness_prompt,
        get_checklist_generation_prompt,
        get_intent_analysis_prompt,
        get_response_analysis_prompt,
        get_completion_phase_intent_prompt
    )
except ImportError:
    from prompts import (
        get_simple_production_readiness_prompt,
        get_checklist_generation_prompt,
        get_intent_analysis_prompt,
        get_response_analysis_prompt,
        get_completion_phase_intent_prompt
    )
import textwrap

app = FastAPI(title="Solution Architect Agent API", version="1.0.0")

# Load environment variables
load_dotenv()

# Get environment variables for AI Project
endpoint = os.getenv("PROJECT_ENDPOINT")
model_deployment_name = os.getenv("MODEL_DEPLOYMENT_NAME")

# Get environment variables for AOAI Resource
aoai_endpoint = os.getenv("AOAI_ENDPOINT")

# Get backend URL for file downloads (default to localhost:8000)
backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

if not endpoint or not model_deployment_name:
    raise ValueError("PROJECT_ENDPOINT and MODEL_DEPLOYMENT_NAME must be set in environment")

# Initialize Azure AI Project client
project_client = AIProjectClient(
    credential=DefaultAzureCredential(),
    endpoint=endpoint,
)

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)

aoai_client = OpenAI(
    base_url=aoai_endpoint,
    api_key=token_provider,
    #default_headers={"api-version": "2024-08-01-preview"}
)

# Set up tracing (optional - only if Application Insights is configured)
try:
    connection_string = project_client.telemetry.get_application_insights_connection_string()
    os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
    OpenAIInstrumentor().instrument()
    configure_azure_monitor(connection_string=connection_string)
    print("Application Insights tracing enabled")
except Exception as e:
    print(f"Application Insights not configured, tracing disabled: {e}")

# Get OpenAI client
#openai_client = project_client.get_openai_client(api_version="2024-02-01")
openai_client = project_client.get_openai_client(api_version="2024-08-01-preview")

# Add CORS middleware to allow frontend communication
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
allowed_origins = ["http://localhost:3000", frontend_url] if frontend_url != "http://localhost:3000" else ["http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[Message]
    stream: bool = False

class ChatResponse(BaseModel):
    message: Message
    conversation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ProductionReadinessRequest(BaseModel):
    service: str
    messages: List[Message] = []

class ChecklistItem(BaseModel):
    item: str
    status: str  # "pending", "implemented", "needs_attention", "not_applicable"
    user_response: str = ""
    recommendation: str = ""
    importance: str = ""
    description: str = ""
    references: List[str] = []  # URLs or WAF pillar references

class ChecklistItemData(BaseModel):
    """Individual checklist item data for structured output"""
    item: str
    importance: str
    description: str
    references: List[str]  # URLs to Azure docs or WAF references

class ChecklistGeneration(BaseModel):
    """Structured output for checklist generation"""
    service_name: str
    checklist_items: List[ChecklistItemData]

class UserIntentAnalysis(BaseModel):
    """Structured output for analyzing user intent"""
    intent: str  # "add_services", "continue_to_review", "view_checklist", "unclear"
    detected_services: List[str] = []
    confidence: float  # 0.0 to 1.0

class UserResponseAnalysis(BaseModel):
    """Structured output for analyzing user response during checklist review - was the recommended item implemented or not"""
    implemented: str # "implemented", "needs_attention", "skip_to_summary", "continue_review"

class CompletionPhaseIntentAnalysis(BaseModel):
    """Structured output for analyzing user intent when review is complete"""
    intent: str # "resume_review", "show_summary", "ask_question", "unclear"
    question_topic: str = ""  # If intent is "ask_question", what are they asking about

class ServiceProgress(BaseModel):
    service_name: str
    checklist_items: List[ChecklistItem] = []
    current_item_index: int = 0
    is_complete: bool = False

# In-memory storage for demo purposes (replace with CosmosDB later)
conversations: Dict[str, List[Message]] = {}
production_mode: bool = False
current_service: str = ""
services_list: List[str] = []
service_progress: List[ServiceProgress] = []
current_service_index: int = 0
conversation_phase: str = "collecting_services"  # "collecting_services", "reviewing_services", "complete"

def clean_text_for_frontend(text: str) -> str:
    """Clean up text formatting to prevent unwanted markdown rendering while preserving intentional formatting"""
    # Use textwrap.dedent to remove common leading whitespace
    cleaned = textwrap.dedent(text).strip()
    return cleaned

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "Solution Architect Agent API is running", 
        "version": "1.0.0",
        "azure_ai_enabled": True
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": "2025-08-21T00:00:00Z"}

@app.get("/api/download-file/{container_id}/{file_id}/{file_type}")
async def download_file(container_id: str, file_id: str, file_type: str):
    """
    Download a file generated by Code Interpreter
    """
    try:
        # Construct the REST API endpoint for container files
        endpoint = f"{aoai_endpoint}/containers/{container_id}/files/{file_id}/content"
        
        headers = {"Authorization": f"Bearer {token_provider()}", "Content-Type": "application/json"}
        params = {"api-version": "preview"}
        
        response = requests.get(endpoint, headers=headers, params=params, timeout=30)

        content_bytes = response.content
        content_type = "application/octet-stream"
        
        # initialize the file extension as a docx
        file_extension = "docx"
        if file_type == "excel":
            file_extension = "xlsx"

        return StreamingResponse(
            iter([content_bytes]),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="checklist.{file_extension}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

# ============================================================================
# SIMPLE TEST ENDPOINT - Uses LLM for everything, no structured outputs
# ============================================================================
@app.post("/api/production-readiness-simple", response_model=ChatResponse)
async def production_readiness_simple(request: ProductionReadinessRequest):
    """
    EXPERIMENTAL: Simplified production readiness chat that lets the LLM handle everything.
    No structured outputs, no state management - just conversation history and a comprehensive prompt.
    """
    try:
        # Build conversation history
        conversation_messages = [
            {"role": "system", "content": get_simple_production_readiness_prompt(request.service)}
        ]
        
        # Add all previous messages from the conversation
        for msg in request.messages:
            conversation_messages.append({
                "role": msg.role,
                "content": msg.content
            })

        # Get LLM response
        response = openai_client.chat.completions.create(
            model=model_deployment_name,
            messages=conversation_messages,
            temperature=1,
            max_completion_tokens=2000
        )
        
        assistant_response = response.choices[0].message.content
        
        # Check if the LLM triggered file generation
        # The LLM will output "GENERATE_FILE_TRIGGER: word" or "GENERATE_FILE_TRIGGER: excel" when ready
        if "generate_file_trigger:" in assistant_response.lower():
            # Extract file type from the trigger itself (not from elsewhere in the response)
            file_type = "word"  # default
            if "generate_file_trigger: excel" in assistant_response.lower():
                file_type = "excel"
            elif "generate_file_trigger: word" in assistant_response.lower():
                file_type = "word"
            
            # Remove the trigger from the response (handle both with and without brackets)
            clean_response = assistant_response.replace("GENERATE_FILE_TRIGGER: word", "").replace("GENERATE_FILE_TRIGGER: excel", "").replace("GENERATE_FILE_TRIGGER: [word]", "").replace("GENERATE_FILE_TRIGGER: [excel]", "").strip()
            
            # Check if the checklist is actually in the conversation (by looking for "Why Important" which appears in checklists)
            # This is sort of a hack, but solves the issue where if the user says something like "Just download the checklist as a word doc and don't show me the list", it will need this information
            # can do so "silently" without showing the user the list but still generating the list in this separate LLM call and pushing it on the chat history
            has_checklist = any("Why Important" in msg.get("content", "") for msg in conversation_messages if msg.get("role") != "system")
            
            # If no checklist in conversation, generate it now for the file
            if not has_checklist:
                print("No checklist found in conversation - generating internally for file export")
                
                # Make a separate call to generate the checklist
                checklist_prompt = """The user wants to export a production readiness checklist file. Generate a COMPLETE production readiness checklist for ALL Azure services discussed in our conversation.

CRITICAL: You MUST generate a complete checklist with real, specific items. Do NOT say items are unavailable.

For EACH service mentioned in our conversation, provide exactly 5 critical production readiness items.

Use this EXACT format for each service:

**[Service Name]**

**Item Name**
- Action description (specific actionable step - what to implement/configure)
- Why Important: [detailed explanation of why this matters for production]
- Learn more: [Full Microsoft Learn URL - https://learn.microsoft.com/...]

Example:
**Azure OpenAI**

**Authentication & Authorization**
- Ensure Azure Active Directory authentication is configured for API access
- Why Important: Protects against unauthorized access and ensures compliance with security policies
- Learn more: https://learn.microsoft.com/azure/ai-services/openai/how-to/managed-identity

**Rate Limiting & Quotas**
- Monitor and configure usage quotas to prevent throttling
- Why Important: Ensures predictable performance and cost control
- Learn more: https://learn.microsoft.com/azure/ai-services/openai/quotas-limits

[Continue with 3 more items for Azure OpenAI, then repeat for all other services]

NOW generate the COMPLETE checklist for ALL services with 5 items each:"""
                
                checklist_messages = conversation_messages.copy()
                checklist_messages.append({
                    "role": "user",
                    "content": checklist_prompt
                })
                
                # Calling LLM to generate internal checklist
                checklist_response = openai_client.chat.completions.create(
                    model=model_deployment_name,
                    messages=checklist_messages,
                    temperature=1,
                    max_completion_tokens=4000
                )
                
                checklist_content = checklist_response.choices[0].message.content
                
                # Add the checklist to conversation history for file generation
                conversation_messages.append({
                    "role": "assistant",
                    "content": checklist_content
                })
            
            # Add the assistant's original response to the conversation history
            conversation_messages.append({
                "role": "assistant",
                "content": assistant_response
            })
            
            # Format conversation history for the file generation agent
            conversation_summary = "Conversation History:\n\n"
            for msg in conversation_messages:
                if msg["role"] == "system":
                    continue  # Skip system prompt
                conversation_summary += f"{msg['role'].upper()}: {msg['content']}\n\n"
            
            # Implement Response API with Code Interpreter
            if file_type == "word":
                instructions = """You are a file generation agent. Generate a professional Word document (.docx) containing the production readiness checklist based on the conversation history provided.

**CRITICAL INSTRUCTIONS - READ CAREFULLY**:
1. The conversation history below contains the COMPLETE checklist content
2. You MUST extract and copy the EXACT text from the conversation - do NOT generate new content
3. Look for messages with "Why Important" - these contain the checklist items
4. Copy EXACTLY what you see in the conversation, including:
- All Azure services discussed
- Exact checklist item names as stated
- The action/description bullet point under each item name (e.g., "Ensure Azure Active Directory is used...")
- Complete "Why Important" descriptions
- ALL documentation URLs (Learn more links) - these MUST be included
- Implementation status (if the user went through systematic review)
- Any recommendations provided

The document should include:
1. Title: "Production Readiness Checklist for [Service Names]"
2. Executive summary paragraph
3. For EACH service, create a section with:
   - Service name as heading
   - Each checklist item with:
     * Item name (bold heading)
     * Action description (the bullet point that appears right after the item name - this is CRITICAL to include)
     * "Why Important:" followed by the exact importance text
     * "Learn more:" followed by the EXACT documentation URL from the conversation
     * Status (if reviewed): Implemented / Needs Attention / Not Applicable
     * Recommendations (if any)
4. Professional formatting with headers, bullet points, and proper spacing

**EXAMPLE FORMAT FROM CONVERSATION:**
```
Authentication & Authorization
- Ensure Azure Active Directory is used for API access.    <-- ACTION DESCRIPTION (MUST INCLUDE)
Why Important: Protects against unauthorized access...
Learn more: [URL]
```

**IMPORTANT**: 
- Do NOT paraphrase or recreate content
- Do NOT write placeholder text like "Checklist content would be listed here"
- ONLY include content that is ACTUALLY PRESENT in the conversation history below
- If you cannot find checklist items in the conversation, leave the sections empty rather than making up content

The conversation history is provided below. Extract all checklist items from it.

Use the python-docx library to create the document. Return the file when complete."""
            else:  # excel
                instructions = """You are a file generation agent. Generate a professional Excel spreadsheet (.xlsx) containing the production readiness checklist based on the conversation history provided.

**CRITICAL INSTRUCTIONS - READ CAREFULLY**:
1. The conversation history below contains the COMPLETE checklist content
2. You MUST extract and copy the EXACT text from the conversation - do NOT generate new content
3. Look for messages with "Why Important" - these contain the checklist items
4. Copy EXACTLY what you see in the conversation, including:
- All Azure services discussed
- Exact checklist item names as stated
- The action/description bullet point under each item name (e.g., "Ensure Azure Active Directory is used...")
- Complete "Why Important" descriptions
- ALL documentation URLs (Learn more links) - these MUST be included as separate cells
- Implementation status (if the user went through systematic review)
- Any recommendations provided

The spreadsheet should include:
1. Row 1: Title "Production Readiness Checklist for [Service Names]"
2. Row 3: Column headers: Service | Item | Action/Description | Why Important | Learn More (URL) | Status | Recommendations
3. Each checklist item as a row with:
   - Service name
   - Exact item name from conversation (e.g., "Authentication & Authorization")
   - Action description (the bullet point that appears right after the item name - CRITICAL to include)
   - Complete "Why Important" text
   - EXACT documentation URL from conversation
   - Status (if reviewed)
   - Recommendations (if any)
4. Professional formatting: bold headers, auto-sized columns, borders, frozen header row

**EXAMPLE FROM CONVERSATION:**
```
Authentication & Authorization
- Ensure Azure Active Directory is used for API access.    <-- ACTION/DESCRIPTION (MUST INCLUDE in separate column)
Why Important: Protects against unauthorized access...
Learn more: [URL]
```

**IMPORTANT**: 
- Do NOT paraphrase or recreate content
- Do NOT write placeholder text like "Checklist content would be listed here"
- ONLY include content that is ACTUALLY PRESENT in the conversation history below
- If you cannot find checklist items in the conversation, leave rows empty rather than making up content

The conversation history is provided below. Extract all checklist items from it.

Use the openpyxl library to create the spreadsheet. Return the file when complete."""
            
            # Use aoai_client for direct Azure OpenAI resource access (not AI Foundry Project)
            try:
                response = aoai_client.responses.create(
                    model=model_deployment_name,
                    tools=[
                        {
                            "type": "code_interpreter",
                            "container": {"type": "auto"}
                        }
                    ],
                    instructions=instructions,
                    input=conversation_summary,
                )
                print(f"DEBUG: Response created successfully")
            except AttributeError as ae:
                print(f"ERROR: aoai_client does not have 'responses' attribute: {ae}")
                raise HTTPException(status_code=500, detail=f"OpenAI client configuration error: {str(ae)}")
            except Exception as e:
                print(f"ERROR: Failed to create response with Code Interpreter: {type(e).__name__}: {str(e)}")
                import traceback
                print(f"ERROR TRACEBACK:\n{traceback.format_exc()}")
                raise HTTPException(status_code=500, detail=f"File generation failed: {str(e)}")
            
            # Extract file information from the response
            container_id = None
            file_id = None
            
            # Look for file annotations in the response
            for output in response.output:
                if output.type == "message":
                    for content in output.content:
                        if content.type == "output_text":
                            for annotation in content.annotations:
                                if annotation.type == "container_file_citation":
                                    container_id = annotation.container_id
                                    file_id = annotation.file_id
            
            file_url = f"{backend_url}/api/download-file/{container_id}/{file_id}/{file_type}" if file_id else None

            # Prepare the response message
            file_info = ""
            if file_url:
                file_info = f"\n\n📄 [Download your {file_type} file]({file_url})"
            else:
                file_info = f"\n\n📄 File generated successfully ({file_type} format)!"
            
            # If we generated an internal checklist, we need to inform the frontend about it
            # so it can be included in future conversation history
            final_content = f"{clean_response}{file_info}"
            if not has_checklist and 'checklist_content' in locals():
                # Prepend the internal checklist as a hidden prefix
                # The frontend should maintain this in conversation history but not display it
                final_content = f"[INTERNAL_CHECKLIST_START]\n{checklist_content}\n[INTERNAL_CHECKLIST_END]\n\n{clean_response}{file_info}"
            
            response_message = Message(
                role="assistant",
                content=final_content
            )
            
            return ChatResponse(
                message=response_message,
                conversation_id="production-readiness-simple",
                metadata={
                    "file_generation_requested": True, 
                    "file_type": file_type,
                    "file_id": file_id,
                    "file_url": file_url,
                    "has_hidden_checklist": not has_checklist and 'checklist_content' in locals()
                }
            )
        
        # Normal response (no file generation)
        response_message = Message(
            role="assistant",
            content=assistant_response
        )
        
        return ChatResponse(
            message=response_message,
            conversation_id="production-readiness-simple"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in simple production readiness chat: {str(e)}")

# ============================================================================
# STREAMING ENDPOINT - Streams LLM responses in real-time
# ============================================================================
@app.post("/api/production-readiness-simple-stream")
async def production_readiness_simple_stream(request: ProductionReadinessRequest):
    """
    Streaming version of the simplified production readiness chat.
    Streams LLM responses in real-time using Server-Sent Events (SSE).
    """
    async def generate_stream():
        try:
            # Build conversation history
            conversation_messages = [
                {"role": "system", "content": get_simple_production_readiness_prompt(request.service)}
            ]
            
            # Add all previous messages from the conversation
            for msg in request.messages:
                conversation_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

            # Get LLM response with streaming
            stream = openai_client.chat.completions.create(
                model=model_deployment_name,
                messages=conversation_messages,
                temperature=1,
                max_completion_tokens=2000,
                stream=True
            )
            
            # Stream the chunks to the frontend
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        # Send chunk to frontend in SSE format
                        yield f"data: {json.dumps({'chunk': delta.content})}\n\n"
            
            # Send completion signal
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            # Send error to frontend
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# ============================================================================
# STRUCTURED ENDPOINT - Uses structured outputs and state management (original)
# ============================================================================
@app.post("/api/production-readiness", response_model=ChatResponse)
async def production_readiness_chat(request: ProductionReadinessRequest):
    """
    Handle production readiness conversations with a specific Azure service
    """
    try:
        global production_mode, current_service, services_list, conversation_phase, current_service_index
        
        # Set production mode and current service
        production_mode = True
        current_service = request.service
        
        # If no messages provided, start the conversation
        if not request.messages:
            services_list = [request.service]
            conversation_phase = "collecting_services"
            
            initial_message = clean_text_for_frontend(f"""
                Hello! I'm your Production Readiness Assistant. My role is to review Azure services being deployed as part of your project and provide specific guidance based on Microsoft best practices and our internal knowledge base.

                I see you're currently looking for production advice for **{request.service}**. Are there other Azure services that are part of your overall architecture that you'd like me to review as well?

                Please let me know if you have additional services, or type 'continue' if {request.service} is the only service you'd like me to review today.
            """)

            response_message = Message(
                role="assistant",
                content=initial_message
            )
            
            return ChatResponse(
                message=response_message,
                conversation_id="production-readiness"
            )
        
        # Get the latest user message
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message found")
        
        latest_user_message = user_messages[-1]
        #user_input = latest_user_message.content.lower().strip()
        
        # Handle different conversation phases
        if conversation_phase == "collecting_services":
            # Use LLM to analyze user intent instead of keyword matching
            intent_analysis = await analyze_user_intent(latest_user_message.content)
            
            if intent_analysis.intent == "add_services":
                # Add detected services
                for service in intent_analysis.detected_services:
                    if service not in services_list:
                        services_list.append(service)
                
                response_content = f"Great! I've added {', '.join(intent_analysis.detected_services)} to our review list. So we'll be reviewing: **{', '.join(services_list)}**.\n\nAre there any other services, or would you like to start the systematic review? Alternatively, you can just see the checklist if you'd like."
            
            elif intent_analysis.intent == "continue_to_review":
                # Start the systematic review
                await initialize_services_progress(services_list)
                conversation_phase = "reviewing_services"
                current_service_index = 0
                
                # Get checklist from the initialized service progress (don't regenerate)
                first_service_progress = service_progress[0]
                first_service = first_service_progress.service_name
                checklist_items = first_service_progress.checklist_items
                
                items_list = "\n".join([f"{i+1}. **{item.item}** - {item.importance}" for i, item in enumerate(checklist_items)])
                
                response_content = clean_text_for_frontend(f"""Perfect! Let's walk through each service systematically to see where you are and what needs to be done.

**Starting with {first_service}**

Here are the key production readiness items I recommend we review:

{items_list}

Let's start with the first one: **{checklist_items[0].item}**

{checklist_items[0].importance}

Have you implemented {checklist_items[0].item.lower()} for your {first_service}?""")
            elif intent_analysis.intent == "view_checklist":
                # Generate checklists without going through systematic review
                await initialize_services_progress(services_list)
                conversation_phase = "complete"  # Mark as complete so they can ask questions or restart
                
                response_content = f"Here's your production readiness checklist for **{', '.join(services_list)}**:\n\n{generate_final_summary()}\n\nYou can ask me questions about any of these items, or type 'start review' if you'd like to go through them systematically."
            else:
                response_content = "I didn't detect any specific Azure services in your response. Could you please list the specific Azure services you'd like me to review, or type 'continue' to start reviewing the services we already have?"
        
        elif conversation_phase == "reviewing_services":
            # Handle answers about specific checklist items
            current_item = get_current_checklist_item()
            current_service_obj = get_current_service_progress()
            
            if not current_item or not current_service_obj:
                response_content = "I seem to have lost track of where we are. Let me know if you'd like to start over."
            else:
                # Process the user's response about the current item
                current_item.user_response = latest_user_message.content
                
                # Use LLM to analyze user intent instead of keyword matching
                intent_analysis = await analyze_user_response(latest_user_message.content)
                
                # Check if user is saying "continue" while already in review
                if intent_analysis.implemented == "continue_review":
                    response_content = f"We're already going through the items systematically! Let me repeat the current question:\n\n**{current_item.item}**\n\n{current_item.importance}\n\nHave you implemented {current_item.item.lower()} for your {current_service_obj.service_name}?"
                # Check if user wants to skip to summary
                elif intent_analysis.implemented == "skip_to_summary":
                    # Check if there are still items to review
                    total_items = sum(len(service.checklist_items) for service in service_progress)
                    reviewed_items = sum(1 for service in service_progress for item in service.checklist_items if item.status != "pending")
                    has_pending = reviewed_items < total_items
                    
                    conversation_phase = "complete"
                    summary = generate_final_summary()
                    
                    if has_pending:
                        response_content = f"Sure! Here's your complete production readiness checklist:\n\n{summary}\n\nYou can ask me questions about any of these items, or type request to resume the systematic review where we left off."
                    else:
                        response_content = f"Here's your complete production readiness checklist:\n\n{summary}\n\nYou can ask me questions about any of these items."
                # Determine status based on user response
                elif intent_analysis.implemented == "implemented":
                    current_item.status = "implemented"
                    current_item.recommendation = "Great! This is properly implemented."
                    
                    # Move to next item
                    advance_to_next_item()
                    
                    # Check what's next
                    next_item = get_current_checklist_item()
                    next_service = get_current_service_progress()
                    
                    if conversation_phase == "complete":
                        # All services completed
                        response_content = f"Excellent! We've completed the review of all your services.\n\n{generate_final_summary()}"
                    
                    elif next_service and next_service.service_name != current_service_obj.service_name:
                        # Moving to next service
                        new_service = next_service.service_name
                        checklist_items = next_service.checklist_items
                        
                        items_list = "\n".join([f"{i+1}. **{item.item}** - {item.importance}" for i, item in enumerate(checklist_items)])
                        
                        response_content = clean_text_for_frontend(f"""Great progress on {current_service_obj.service_name}! Now let's move to **{new_service}**.

Here are the key production readiness items for {new_service}:

{items_list}

Let's start with: **{checklist_items[0].item}**

{checklist_items[0].importance}

Have you implemented {checklist_items[0].item.lower()} for your {new_service}?""")
                    
                    elif next_item:
                        # Next item in same service
                        response_content = f"{format_item_with_references(next_item)}\n\nHave you implemented {next_item.item.lower()}?"
                    else:
                        response_content = "I seem to have lost track. Let me know if you'd like to start over."
                elif intent_analysis.implemented == "needs_attention":
                    current_item.status = "needs_attention"
                    current_item.recommendation = f"Consider implementing this - {current_item.importance.lower()}"
                    
                    # Move to next item
                    advance_to_next_item()
                    
                    # Check what's next
                    next_item = get_current_checklist_item()
                    next_service = get_current_service_progress()
                    
                    if conversation_phase == "complete":
                        # All services completed
                        response_content = f"Excellent! We've completed the review of all your services.\n\n{generate_final_summary()}"
                    
                    elif next_service and next_service.service_name != current_service_obj.service_name:
                        # Moving to next service
                        new_service = next_service.service_name
                        checklist_items = next_service.checklist_items
                        
                        items_list = "\n".join([f"{i+1}. **{item.item}** - {item.importance}" for i, item in enumerate(checklist_items)])
                        
                        response_content = clean_text_for_frontend(f"""Great progress on {current_service_obj.service_name}! Now let's move to **{new_service}**.

Here are the key production readiness items for {new_service}:

{items_list}

Let's start with: **{checklist_items[0].item}**

{checklist_items[0].importance}

Have you implemented {checklist_items[0].item.lower()} for your {new_service}?""")
                    
                    elif next_item:
                        # Next item in same service
                        response_content = clean_text_for_frontend(f"""
                        Thanks for that information about {current_item.item.lower()}.

                        Next item: **{next_item.item}**

                        {next_item.importance}

                        Have you implemented {next_item.item.lower()} for your {current_service_obj.service_name}?
                    """)
                    
                    else:
                        response_content = "Something went wrong with tracking our progress. Let me know if you'd like to continue."
                else:
                    # unclear response
                    current_item.status = "needs_attention"
                    current_item.recommendation = "Please clarify the implementation status of this item."
                    response_content = f"I'm not sure I understood your response about **{current_item.item}**. Could you clarify whether you have implemented this or not?"
        
        elif conversation_phase == "complete":
            # Review is complete or user viewed checklist - handle follow-up questions or restart
            # Use LLM to analyze user intent
            intent_analysis = await analyze_completion_phase_intent(latest_user_message.content)
            
            if intent_analysis.intent == "resume_review":
                conversation_phase = "reviewing_services"
                # Reset to first uncompleted item
                current_service_index = 0
                for service in service_progress:
                    service.current_item_index = 0
                    for i, item in enumerate(service.checklist_items):
                        if item.status == "pending":
                            service.current_item_index = i
                            break
                    if service.current_item_index < len(service.checklist_items):
                        break
                    current_service_index += 1
                
                current_item = get_current_checklist_item()
                current_service_obj = get_current_service_progress()
                
                if current_item and current_service_obj:
                    response_content = f"Great! Let's resume the systematic review. I'll pick up where we left off.\n\n**{current_item.item}**\n\n{current_item.importance}\n\nHave you implemented {current_item.item.lower()} for your {current_service_obj.service_name}?"
                else:
                    response_content = f"All items have been reviewed! Here's your summary:\n\n{generate_final_summary()}"
            
            elif intent_analysis.intent == "show_summary":
                response_content = f"Here's your production readiness summary:\n\n{generate_final_summary()}"
            
            elif intent_analysis.intent == "ask_question":
                # Use LLM to answer questions about the checklist items
                # Gather all checklist context
                checklist_context = ""
                for service in service_progress:
                    checklist_context += f"\n\n**{service.service_name} Checklist Items:**\n"
                    for item in service.checklist_items:
                        checklist_context += f"- **{item.item}**: {item.importance}\n"
                        if item.description:
                            checklist_context += f"  Description: {item.description}\n"
                        if item.references:
                            checklist_context += f"  References: {', '.join(item.references)}\n"
                
                # Use LLM to answer the question with context
                try:
                    answer_response = openai_client.chat.completions.create(
                        model=model_deployment_name,
                        messages=[
                            {"role": "system", "content": f"""You are a production readiness expert helping users understand Azure service recommendations.

Context - Here are the checklist items for the user's services:
{checklist_context}

Your task: Answer the user's question about one or more of these checklist items. Provide clear, detailed explanations with:
1. Why this item is important for production readiness
2. Specific implementation guidance
3. Best practices and potential pitfalls

Keep your answer focused and practical."""},
                            {"role": "user", "content": latest_user_message.content}
                        ],
                        temperature=1,
                        max_completion_tokens=1000
                    )
                    
                    response_content = answer_response.choices[0].message.content
                except Exception as e:
                    print(f"Error answering question: {e}")
                    response_content = f"I can help you understand any of the checklist items better. You can also type 'summary' to see the full checklist again, or 'start review' to go through the items systematically.\n\nWhat would you like to know more about?"
            
            else:
                # unclear intent
                response_content = f"I can help you with:\n- Resuming the systematic review (type 'continue')\n- Showing the checklist summary (type 'summary')\n- Answering questions about specific items\n\nWhat would you like to do?"
        
        else:
            response_content = "I'm not sure how to help with that. Type 'summary' to see your production readiness summary."
        
        # Create response message
        response_message = Message(
            role="assistant",
            content=response_content
        )
        
        return ChatResponse(
            message=response_message,
            conversation_id="production-readiness"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in production readiness chat: {str(e)}")

async def analyze_user_intent(user_message: str) -> UserIntentAnalysis:
    """Use LLM to analyze user intent during service collection phase"""
    try:
        response = openai_client.beta.chat.completions.parse(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": get_intent_analysis_prompt()},
                {"role": "user", "content": user_message}
            ],
            response_format=UserIntentAnalysis,
            temperature=1,
            max_completion_tokens=1000
        )
        
        response_content = response.choices[0].message.parsed
        
        return response_content

    except Exception as e:
        print(f"Error analyzing user intent: {e}")
        return UserIntentAnalysis(
            intent="unclear",
            detected_services=[],
            confidence=0.1
        )

async def analyze_user_response(user_message: str) -> UserResponseAnalysis:
    """Use LLM to analyze user response of whether a service recommendation was implemented or not"""
    try:
        response = openai_client.beta.chat.completions.parse(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": get_response_analysis_prompt()},
                {"role": "user", "content": user_message}
            ],
            response_format=UserResponseAnalysis,
            temperature=1,
            max_completion_tokens=1000
        )
        
        response_content = response.choices[0].message.parsed
        
        return response_content

    except Exception as e:
        print(f"Error analyzing user intent: {e}")
        return UserResponseAnalysis(
            intent="unclear",
            detected_services=[],
            confidence=0.1
        )

async def analyze_completion_phase_intent(user_message: str) -> CompletionPhaseIntentAnalysis:
    """Use LLM to analyze user intent when the review is in 'complete' phase"""
    try:
        response = openai_client.beta.chat.completions.parse(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": get_completion_phase_intent_prompt()},
                {"role": "user", "content": user_message}
            ],
            response_format=CompletionPhaseIntentAnalysis,
            temperature=1,
            max_completion_tokens=1000
        )
        
        response_content = response.choices[0].message.parsed
        
        return response_content

    except Exception as e:
        print(f"Error analyzing completion phase intent: {e}")
        return CompletionPhaseIntentAnalysis(
            intent="unclear",
            question_topic=""
        )

@app.get("/api/production-readiness/summary")
async def get_production_summary():
    """
    Get the current production readiness summary
    """
    try:
        if not service_progress:
            return {"summary": "No production readiness session in progress."}
        
        summary = generate_final_summary()
        
        return {
            "summary": summary,
            "services": [
                {
                    "name": service.service_name,
                    "is_complete": service.is_complete,
                    "items": [
                        {
                            "item": item.item,
                            "status": item.status,
                            "user_response": item.user_response,
                            "recommendation": item.recommendation,
                            "importance": item.importance
                        }
                        for item in service.checklist_items
                    ]
                }
                for service in service_progress
            ],
            "conversation_phase": conversation_phase
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting production summary: {str(e)}")

async def get_service_checklist_items(service: str) -> List[ChecklistItem]:
    """Dynamically generate production readiness checklist items for a specific service using LLM with structured outputs"""
    try:
        # Use the LLM to generate checklist items based on core knowledge with structured output
        response = openai_client.beta.chat.completions.parse(
            model=model_deployment_name,
            messages=[
                {"role": "system", "content": get_checklist_generation_prompt(service)}
            ],
            response_format=ChecklistGeneration,
            temperature=1,
            max_completion_tokens=8000
        )
        
        # Get the parsed structured output
        checklist_generation = response.choices[0].message.parsed
        
        # Convert ChecklistGeneration to List[ChecklistItem]
        checklist_items = []
        for item_data in checklist_generation.checklist_items:
            item = ChecklistItem(
                item=item_data.item,
                importance=item_data.importance,
                description=item_data.description,
                status="pending",
                references=item_data.references
            )
            checklist_items.append(item)
        
        return checklist_items
    
    except Exception as e:
        print(f"Error generating checklist for {service}: {e}")
        # Fallback checklist
        return [
            ChecklistItem(
                item=f"Production readiness assessment for {service}",
                importance="Review based on Azure best practices and core knowledge",
                description="Comprehensive review of this service for production deployment",
                status="pending"
            )
        ]

async def initialize_services_progress(services: List[str]):
    """Initialize progress tracking for all services"""
    global service_progress
    service_progress = []
    for service in services:
        checklist = await get_service_checklist_items(service)
        progress = ServiceProgress(
            service_name=service,
            checklist_items=checklist
        )
        service_progress.append(progress)

def get_current_service_progress() -> Optional[ServiceProgress]:
    """Get the current service being reviewed"""
    global current_service_index, service_progress
    if current_service_index < len(service_progress):
        return service_progress[current_service_index]
    return None

def get_current_checklist_item() -> Optional[ChecklistItem]:
    """Get the current checklist item being discussed"""
    current_service = get_current_service_progress()
    if current_service and current_service.current_item_index < len(current_service.checklist_items):
        return current_service.checklist_items[current_service.current_item_index]
    return None

def format_item_with_references(item: ChecklistItem) -> str:
    """Format a checklist item with its importance and references"""
    formatted = f"**{item.item}**\n\n{item.importance}"
    if item.references:
        formatted += f"\n\n*Learn more:* {', '.join(item.references)}"
    return formatted

def advance_to_next_item():
    """Move to the next checklist item or service"""
    global current_service_index, conversation_phase
    
    current_service = get_current_service_progress()
    if not current_service:
        return
    
    current_service.current_item_index += 1
    
    # Check if we've completed all items for this service
    if current_service.current_item_index >= len(current_service.checklist_items):
        current_service.is_complete = True
        current_service_index += 1
        
        # Check if we've completed all services
        if current_service_index >= len(service_progress):
            conversation_phase = "complete"

def generate_final_summary() -> str:
    """Generate the final summary table of all services and their status"""
    summary = "## Production Readiness Summary\n\n"
    
    for service in service_progress:
        summary += f"### {service.service_name}\n"
        
        # Check if this service has been reviewed (any item has a status other than pending)
        reviewed = any(item.status != "pending" for item in service.checklist_items)
        
        if not reviewed:
            # Service hasn't been reviewed yet - just show the checklist
            summary += "**Recommended Production Readiness Items:**\n"
            for i, item in enumerate(service.checklist_items, 1):
                summary += f"{i}. **{item.item}** - {item.importance}\n"
                if item.references:
                    summary += f"   *References:* {', '.join(item.references)}\n"
            summary += "\n"
        else:
            # Service has been reviewed - show status
            implemented = []
            needs_attention = []
            
            for item in service.checklist_items:
                if item.status == "implemented":
                    implemented.append(f"✅ {item.item}")
                elif item.status == "needs_attention":
                    needs_attention.append(f"⚠️ {item.item} - {item.recommendation}")
                elif item.status == "not_applicable":
                    implemented.append(f"➖ {item.item} (Not Applicable)")
                elif item.status == "pending":
                    needs_attention.append(f"❓ {item.item} - Not yet reviewed")
            
            if implemented:
                summary += "**Implemented:**\n"
                for item in implemented:
                    summary += f"- {item}\n"
                summary += "\n"
            
            if needs_attention:
                summary += "**Needs Attention:**\n"
                for item in needs_attention:
                    summary += f"- {item}\n"
                summary += "\n"
        
        summary += "---\n\n"
    
    # Overall statistics - only for reviewed items
    total_items = sum(len(service.checklist_items) for service in service_progress)
    reviewed_items = sum(1 for service in service_progress for item in service.checklist_items if item.status != "pending")
    implemented_items = sum(1 for service in service_progress for item in service.checklist_items if item.status == "implemented")
    attention_items = sum(1 for service in service_progress for item in service.checklist_items if item.status == "needs_attention")
    
    if reviewed_items > 0:
        summary += f"**Review Progress:** {reviewed_items}/{total_items} items reviewed\n"
        summary += f"**Overall Progress:** {implemented_items}/{reviewed_items} reviewed items implemented ({round(implemented_items/reviewed_items*100, 1) if reviewed_items > 0 else 0}%)\n"
        summary += f"**Items needing attention:** {attention_items}\n"
    else:
        summary += f"**Total items to review:** {total_items}\n"
        summary += "*No items have been reviewed yet. Type 'continue' to start the systematic review.*\n"
    
    return summary

# @app.post("/api/chat", response_model=ChatResponse)
# async def chat_completion(request: ChatRequest):
#     """
#     Handle chat completion requests using Azure AI Foundry
#     """
#     try:
#         # Get the last user message
#         user_messages = [msg for msg in request.messages if msg.role == "user"]
#         if not user_messages:
#             raise HTTPException(status_code=400, detail="No user message found")
        
#         # Convert request messages to Azure AI format
#         azure_messages = [
#             {"role": "system", "content": get_production_readiness_system_prompt()},
#         ]
        
#         for msg in request.messages:
#             azure_messages.append({
#                 "role": msg.role,
#                 "content": msg.content
#             })
        
#         response = openai_client.chat.completions.create(
#             model=model_deployment_name,
#             messages=azure_messages,
#             temperature=1,
#             max_completion_tokens=1500
#         )
        
#         assistant_response = response.choices[0].message.content
        
#         # Create response message
#         response_message = Message(
#             role="assistant",
#             content=assistant_response
#         )
        
#         return ChatResponse(
#             message=response_message,
#             conversation_id="dummy-conversation-id"
#         )
        
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")

# @app.post("/api/chat/stream")
# async def chat_completion_stream(request: ChatRequest):
#     """
#     Handle streaming chat completion requests using Azure AI Foundry
#     """
#     def generate_stream():  # Regular function, not async
#         try:
#             # Get the last user message
#             user_messages = [msg for msg in request.messages if msg.role == "user"]
#             if not user_messages:
#                 yield f"data: {json.dumps({'error': 'No user message found'})}\n\n"
#                 return
            
#             # Convert request messages to Azure AI format
#             azure_messages = [
#                 {"role": "system", "content": get_production_readiness_system_prompt()},
#             ]
            
#             for msg in request.messages:
#                 azure_messages.append({
#                     "role": msg.role,
#                     "content": msg.content
#                 })
            
#             print("🔄 Starting Azure AI streaming...")
            
#             # Create streaming response
#             stream = openai_client.chat.completions.create(
#                 model=model_deployment_name,
#                 messages=azure_messages,
#                 temperature=1,
#                 max_completion_tokens=1500,
#                 stream=True
#             )
            
#             # Stream the response - EXACTLY like working Gemini example
#             for chunk in stream:
#                 try:
#                     if (hasattr(chunk, 'choices') and 
#                         chunk.choices and 
#                         len(chunk.choices) > 0):
                        
#                         choice = chunk.choices[0]
                        
#                         if (hasattr(choice, 'delta') and 
#                             choice.delta and 
#                             hasattr(choice.delta, 'content') and 
#                             choice.delta.content is not None):
                            
#                             text = choice.delta.content
#                             data_chunk = json.dumps({'chunk': text})
#                             yield f"data: {data_chunk}\n\n"
#                             print(f"📤 Yielding chunk: {repr(text)}")
                        
#                         # Check for finish reason
#                         if (hasattr(choice, 'finish_reason') and 
#                             choice.finish_reason == 'stop'):
#                             print("✅ Stream completed")
#                             break
                            
#                 except (AttributeError, IndexError):
#                     continue  # Skip malformed chunks
                
#             # Signal end exactly like working example
#             yield "data: [DONE]\n\n"
#             print("📤 Sent [DONE] signal")
                
#         except Exception as e:
#             print(f"❌ Stream error: {e}")
#             yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
#     return StreamingResponse(
#         generate_stream(),
#         media_type="text/event-stream",
#         headers={
#             "Cache-Control": "no-cache, no-store, must-revalidate",
#             "Connection": "keep-alive",
#             "Access-Control-Allow-Origin": "http://localhost:3000",
#             "Access-Control-Allow-Headers": "*",
#             "Access-Control-Allow-Methods": "POST, OPTIONS",
#             "X-Accel-Buffering": "no",  # Disable proxy buffering
#         }
#     )

@app.get("/api/conversations")
async def get_conversations():
    """
    Get all conversations (dummy endpoint)
    """
    return {
        "conversations": [
            {
                "id": "conv-1",
                "title": "Getting Started",
                "last_message": "Hello! How can I help you today?",
                "timestamp": "2025-08-06T00:00:00Z"
            },
            {
                "id": "conv-2", 
                "title": "Azure AI Questions",
                "last_message": "Azure AI Foundry is a comprehensive platform...",
                "timestamp": "2025-08-05T12:00:00Z"
            }
        ]
    }

@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """
    Get a specific conversation by ID (dummy endpoint)
    """
    return {
        "id": conversation_id,
        "messages": [
            {
                "role": "assistant",
                "content": "Hello! How can I help you today?",
                "timestamp": "2025-08-06T00:00:00Z"
            }
        ]
    }

@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """
    Delete a specific conversation (dummy endpoint)
    """
    return {"message": f"Conversation {conversation_id} deleted successfully"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)