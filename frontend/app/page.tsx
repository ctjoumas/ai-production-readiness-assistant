'use client'

import { useState, useRef, useEffect } from 'react'
import { Send, Sparkles } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

// Get API URL from environment variable
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Helper function to strip internal checklist markers for display
const stripInternalChecklist = (content: string): string => {
  const startMarker = '[INTERNAL_CHECKLIST_START]'
  const endMarker = '[INTERNAL_CHECKLIST_END]'
  
  const startIndex = content.indexOf(startMarker)
  if (startIndex === -1) return content
  
  const endIndex = content.indexOf(endMarker)
  if (endIndex === -1) return content
  
  // Remove everything from start marker to end marker (inclusive), plus the trailing newlines
  return content.substring(0, startIndex) + content.substring(endIndex + endMarker.length).replace(/^\n+/, '')
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputMessage, setInputMessage] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [showStarterQuestions, setShowStarterQuestions] = useState(true)
  const [productionSessionId, setProductionSessionId] = useState<string | null>(null)
  const [isProductionMode, setIsProductionMode] = useState(true)
  const [currentService, setCurrentService] = useState<string>("")
  const [useSimpleEndpoint, setUseSimpleEndpoint] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const startProductionReadiness = async (service: string) => {
    try {
      setIsLoading(true)
      setIsProductionMode(true)
      setCurrentService(service)
      setShowStarterQuestions(false)
      
      // Use simple endpoint if mode=simple in URL
      const endpoint = `${API_URL}/api/production-readiness`
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          service: service,
          messages: []
        })
      })
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      
      const data = await response.json()
      setMessages([data.message])
      
    } catch (error) {
      console.error('Error starting production readiness session:', error)
      setMessages([{
        role: 'assistant',
        content: 'Sorry, I encountered an error starting the production readiness session. Please try again.'
      }])
    } finally {
      setIsLoading(false)
    }
  }

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Auto-scroll when messages update
  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Debug: Monitor messages state changes
  useEffect(() => {
    console.log('🔄 Messages state updated:', messages.map(m => ({
      role: m.role,
      contentLength: m.content?.length || 0,
      preview: m.content?.slice(0, 30) + (m.content?.length > 30 ? '...' : '')
    })))
  }, [messages])

  // Check for query parameters on component mount
  useEffect(() => {
    const checkQueryParams = () => {
      const urlParams = new URLSearchParams(window.location.search)
      const service = urlParams.get('service')
      
      if (service && !isLoading && messages.length === 0) {
        console.log(`🚀 Auto-starting production readiness for service: ${service}`)
        startProductionReadiness(service)
      }
    }

    // Run after component mounts
    checkQueryParams()
  }, [])

  const sendMessage = async (messageText?: string) => {
    const textToSend = messageText || inputMessage
    if (!textToSend.trim() || isLoading) return

    const userMessage: Message = {
      role: 'user',
      content: textToSend
    }

    // Store current messages before updating state
    const currentMessages = [...messages, userMessage]
    
    setMessages(prev => [...prev, userMessage])
    setInputMessage('')
    setIsLoading(true)
    setShowStarterQuestions(false)

    // Prepare initial assistant message placeholder
    const initialAssistantMessage: Message = {
      role: 'assistant',
      content: ''
    }

    setMessages(prev => [...prev, initialAssistantMessage])

    try {
      // Use production readiness API if in production mode
      if (isProductionMode) {
        const endpoint = useSimpleEndpoint 
          ? `${API_URL}/api/production-readiness-simple`
          : `${API_URL}/api/production-readiness`
        
        const response = await fetch(endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            service: currentService,
            messages: currentMessages
          })
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()

        // Detect SERVICE_DETECTED marker emitted by the backend prompt when
        // the user has not yet selected a service. Strip it from the displayed
        // message and update currentService so subsequent requests use the
        // full production readiness workflow prompt.
        let assistantMessage = data.message
        if (assistantMessage && typeof assistantMessage.content === 'string') {
          const match = assistantMessage.content.match(/^\s*SERVICE_DETECTED:\s*(.+?)\s*$/m)
          if (match) {
            const detectedService = match[1].trim()
            if (detectedService) {
              setCurrentService(detectedService)
            }
            assistantMessage = {
              ...assistantMessage,
              content: assistantMessage.content.replace(/^\s*SERVICE_DETECTED:\s*.+?\s*$/m, '').trim()
            }
          }
        }

        setMessages(prev => prev.map((msg, index) => 
          index === prev.length - 1 && msg.role === 'assistant'
            ? assistantMessage
            : msg
        ))
        
        setIsLoading(false)
        return
      }

      // Original streaming logic for regular chat
      console.log('🚀 Starting streaming request to /api/chat/stream...')
      
      const response = await fetch(`${API_URL}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          messages: currentMessages,
          stream: true
        })
      })

      console.log('📡 Response status:', response.status)
      console.log('📡 Response headers:', Object.fromEntries(response.headers.entries()))

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No reader available')
      }

      const decoder = new TextDecoder()
      let accumulatedContent = ''
      
      console.log('📡 Starting to read stream chunks...')

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          console.log('📡 Stream reading complete (done=true)')
          break
        }
        
        // Decode the chunk
        const chunk = decoder.decode(value, { stream: true })
        console.log('📦 Raw chunk received:', JSON.stringify(chunk))
        
        // Split by lines and process each
        const lines = chunk.split('\n')
        
        for (const line of lines) {
          if (!line.trim()) {
            console.log('📋 Skipping empty line')
            continue
          }
          
          console.log('📋 Processing line:', JSON.stringify(line))
          
          if (!line.startsWith('data: ')) {
            console.log('📋 Line does not start with "data: " - skipping')
            continue
          }
          
          // Check for completion signal
          if (line.includes('[DONE]')) {
            console.log('✅ [DONE] signal received - ending stream')
            setIsLoading(false)
            return
          }

          try {
            // Parse the JSON data after "data: "
            const jsonData = line.slice(5).trim()
            if (!jsonData) {
              console.log('📋 No JSON data after "data: " - skipping')
              continue
            }
            
            const data = JSON.parse(jsonData)
            console.log('📄 Parsed chunk data:', data)
            
            // Handle chunk data
            if (data.chunk) {
              const newChunk = data.chunk
              accumulatedContent += newChunk
              
              console.log(`📝 New chunk: ${JSON.stringify(newChunk)}`)
              console.log(`📝 Total accumulated (${accumulatedContent.length} chars): "${accumulatedContent.slice(-100)}"`)
              
              // Force immediate UI update
              setMessages(prevMessages => {
                console.log('🔄 Updating messages state with new chunk...')
                const updatedMessages = prevMessages.map((msg, index) => {
                  if (index === prevMessages.length - 1 && msg.role === 'assistant') {
                    const updatedMsg = { ...msg, content: accumulatedContent }
                    console.log(`🔄 Updated assistant message (${updatedMsg.content.length} chars): "${updatedMsg.content.slice(-50)}"`)
                    return updatedMsg
                  }
                  return msg
                })
                return updatedMessages
              })
              
              // Auto-scroll during streaming
              scrollToBottom()
              
              // Small delay to ensure React processes the update
              await new Promise(resolve => setTimeout(resolve, 0))
            }
            
            // Handle done flag
            if (data.done === true) {
              console.log('✅ Done flag received in data')
              setIsLoading(false)
              return
            }
            
            // Handle error
            if (data.error) {
              throw new Error(data.error)
            }
            
          } catch (parseError) {
            console.warn('⚠️ Parse error (skipping):', parseError)
            console.warn('⚠️ Line that failed:', JSON.stringify(line))
            continue
          }
        }
      }
      
    } catch (error) {
      console.error('❌ Error in sendMessage:', error)
      setMessages(prev => prev.map((msg, index) => 
        index === prev.length - 1 && msg.role === 'assistant'
          ? { ...msg, content: 'Sorry, I encountered an error. Please try again.' }
          : msg
      ))
    } finally {
      console.log('🏁 Finally block - setting isLoading to false')
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-screen bg-gray-900">
      {/* Sidebar - ChatGPT Style */}
      <div className="w-80 bg-gray-900 text-white flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 bg-white rounded-lg flex items-center justify-center">
              <Sparkles className="text-gray-900" size={18} />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Production Readiness Agent</h1>
            </div>
          </div>
        </div>

        {/* Suggested Prompts Section */}
        <div className="flex-1 overflow-y-auto px-4 pb-4 dark-scrollbar">
          <h3 className="text-sm font-medium text-gray-400 px-2 py-3 uppercase tracking-wider">
            Suggested Prompts
          </h3>
          <div className="space-y-2">
            <button
              onClick={() => sendMessage("Generate a production readiness checklist and export it as a Word document. Don't show me the list here yet.")}
              className="w-full text-left p-3 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 text-gray-100 rounded-lg transition-all duration-200 text-sm"
            >
              📄 Export checklist as Word doc
            </button>
            <button
              onClick={() => sendMessage("Generate a production readiness checklist and export it as an Excel file. Don't show me the list here yet.")}
              className="w-full text-left p-3 bg-gray-800 hover:bg-gray-700 border border-gray-700 hover:border-gray-600 text-gray-100 rounded-lg transition-all duration-200 text-sm"
            >
              📊 Export checklist as Excel file
            </button>
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-gray-800">
        {/* Chat Header */}
        <div className="bg-gray-800 border-b border-gray-700 p-6">
        </div>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto bg-gray-800">
          {messages.length === 0 ? (
            <div className="h-full flex items-center justify-center p-8">
              <div className="text-center space-y-6 max-w-2xl">
                <div className="flex items-center justify-center space-x-4">
                  <div className="w-16 h-16 bg-gradient-to-r from-blue-500 to-purple-600 rounded-3xl flex items-center justify-center shadow-lg">
                    <Sparkles className="text-white" size={24} />
                  </div>
                  <h3 className="text-4xl font-medium text-white tracking-tight">Production Readiness Agent</h3>
                </div>
                {isLoading ? (
                  <p className="text-gray-300 text-xl font-light leading-relaxed">
                    Loading your assistant...
                  </p>
                ) : (
                  <div className="space-y-5 text-left bg-gray-700/30 border border-gray-700/40 rounded-2xl p-8 shadow-lg">
                    <p className="text-gray-100 text-lg font-normal leading-relaxed">
                      👋 Hi! I'm your <strong className="text-white">Azure Production Readiness Assistant</strong>. I help account managers prepare for production-deployment conversations with their customers by generating tailored checklists based on the <strong className="text-white">Azure Well-Architected Framework</strong>.
                    </p>
                    <div className="space-y-2">
                      <p className="text-gray-200 text-base font-medium">Here's how I can help:</p>
                      <ul className="list-disc list-inside text-gray-300 text-base space-y-1 ml-2">
                        <li>Generate a production readiness checklist for your Azure services</li>
                        <li>Walk through each item with you in a systematic review</li>
                        <li>Export the final checklist as a Word document or Excel file</li>
                      </ul>
                    </div>
                    <div className="space-y-2 pt-2 border-t border-gray-600/40">
                      <p className="text-gray-200 text-base font-medium">To get started:</p>
                      <p className="text-gray-300 text-base leading-relaxed">
                        Tell me which Azure service(s) you'd like to review. For example: <span className="text-blue-300">Azure OpenAI</span>, <span className="text-blue-300">Azure App Service</span>, <span className="text-blue-300">Azure SQL Database</span>, <span className="text-blue-300">Azure Cosmos DB</span>, <span className="text-blue-300">Azure Functions</span>, <span className="text-blue-300">Azure Container Apps</span>, etc.
                      </p>
                      <p className="text-gray-400 text-sm italic">
                        You can list multiple services in one message if your workload uses more than one.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="px-8 py-12">
              <div className="space-y-12 max-w-5xl mx-auto">
                {messages.map((message, index) => (
                  <div
                    key={index}
                    className={`flex items-start ${
                      message.role === 'user' ? 'justify-end' : 'space-x-4'
                    } animate-fadeIn`}
                  >
                    {message.role === 'assistant' && (
                      <div className="w-6 h-6 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0 mt-1">
                        <Sparkles className="text-white" size={14} />
                      </div>
                    )}
                    <div className={`flex-1 ${message.role === 'user' ? 'text-right' : ''}`}>
                      <div className={`inline-block max-w-[90%] ${
                        message.role === 'user'
                          ? 'bg-gray-600 text-white rounded-3xl rounded-tr-xl shadow-lg px-6 py-5'
                          : 'bg-transparent text-gray-100 py-2'
                      }`}>
                        {message.role === 'user' ? (
                          <p className="text-base font-medium leading-relaxed whitespace-pre-wrap">
                            {message.content}
                          </p>
                        ) : (
                          <div className="text-lg font-normal leading-relaxed tracking-wide">
                            <ReactMarkdown 
                              remarkPlugins={[remarkGfm]}
                              components={{
                                // Customize heading styles
                                h1: ({children}) => <h1 className="text-2xl font-bold mb-4 text-white">{children}</h1>,
                                h2: ({children}) => <h2 className="text-xl font-semibold mb-3 text-white">{children}</h2>,
                                h3: ({children}) => <h3 className="text-lg font-medium mb-2 text-white">{children}</h3>,
                                // Customize list styles
                                ul: ({children}) => <ul className="list-disc list-inside mb-4 space-y-1">{children}</ul>,
                                ol: ({children}) => <ol className="list-decimal list-inside mb-4 space-y-1">{children}</ol>,
                                li: ({children}) => <li className="text-gray-100">{children}</li>,
                                // Customize paragraph styles
                                p: ({children}) => <p className="mb-3 text-gray-100 leading-relaxed">{children}</p>,
                                // Customize code styles
                                code: ({children, className}) => {
                                  const isInline = !className?.includes('language-')
                                  return isInline ? (
                                    <code className="bg-gray-700 text-blue-300 px-2 py-1 rounded text-sm font-mono">
                                      {children}
                                    </code>
                                  ) : (
                                    <code className="block bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-sm font-mono">
                                      {children}
                                    </code>
                                  )
                                },
                                // Customize blockquote styles
                                blockquote: ({children}) => (
                                  <blockquote className="border-l-4 border-blue-500 pl-4 italic text-gray-300 my-4">
                                    {children}
                                  </blockquote>
                                ),
                                // Customize strong/bold styles
                                strong: ({children}) => <strong className="font-semibold text-white">{children}</strong>,
                                // Customize link styles
                                a: ({href, children}) => (
                                  <a 
                                    href={href} 
                                    target="_blank" 
                                    rel="noopener noreferrer"
                                    className="text-blue-400 hover:text-blue-300 underline font-medium"
                                  >
                                    {children}
                                  </a>
                                ),
                              }}
                            >
                              {stripInternalChecklist(message.content) || (isLoading ? '●' : '')}
                            </ReactMarkdown>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
                
                <div ref={messagesEndRef} />
              </div>
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="px-8 py-8 bg-gray-800 border-t border-gray-700/50">
          <div className="max-w-5xl mx-auto">
            <div className="flex items-end space-x-6">
              <div className="flex-1 relative">
                <textarea
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask me anything..."
                  disabled={isLoading}
                  className="w-full px-6 py-5 bg-gray-700/60 border border-gray-600/40 rounded-3xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 placeholder-gray-400 text-gray-100 text-lg font-normal leading-relaxed shadow-lg backdrop-blur-sm transition-all duration-200"
                  rows={1}
                  style={{ minHeight: '64px', maxHeight: '160px' }}
                />
              </div>
              <button
                onClick={() => sendMessage()}
                disabled={!inputMessage.trim() || isLoading}
                className="px-6 py-5 bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 text-white rounded-3xl disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 flex items-center shadow-xl hover:shadow-2xl disabled:hover:shadow-xl transform hover:scale-105 disabled:hover:scale-100"
              >
                <Send size={22} />
              </button>
            </div>
            <p className="text-sm text-gray-400 mt-6 text-center font-light">
              Press Enter to send • Shift+Enter for new line
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}