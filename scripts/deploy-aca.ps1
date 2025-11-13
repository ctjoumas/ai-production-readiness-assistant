# PowerShell Deployment Script for Azure Container Apps
# This script deploys the Production Readiness Chatbot to Azure Container Apps with Azure AD authentication

param(
    [Parameter(Mandatory=$true, HelpMessage="Azure Resource Group name")]
    [string]$ResourceGroupName,
    
    [Parameter(Mandatory=$true, HelpMessage="Azure region (e.g., eastus, westus2)")]
    [string]$Location,
    
    [Parameter(Mandatory=$true, HelpMessage="Application name (will be used as prefix)")]
    [string]$AppName,
    
    [Parameter(Mandatory=$true, HelpMessage="Your Azure AD Tenant ID")]
    [string]$TenantId,
    
    [Parameter(Mandatory=$false, HelpMessage="Azure Container Registry name (auto-generated if not provided)")]
    [string]$AcrName = "",
    
    [Parameter(Mandatory=$true, HelpMessage="Azure AI Project endpoint URL")]
    [string]$ProjectEndpoint,
    
    [Parameter(Mandatory=$true, HelpMessage="Model deployment name (e.g., gpt-4, gpt-35-turbo)")]
    [string]$ModelDeploymentName
)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Azure Container Apps Deployment" -ForegroundColor Cyan
Write-Host "   Production Readiness Chatbot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Variables
$containerAppEnvName = "$AppName-env"
$backendAppName = "$AppName-backend"
$frontendAppName = "$AppName-frontend"
$logAnalyticsName = "$AppName-logs"

# Create ACR name if not provided
if ([string]::IsNullOrEmpty($AcrName)) {
    $AcrName = $AppName.Replace("-", "").Replace("_", "").ToLower() + "acr"
    Write-Host " Generated ACR name: $AcrName" -ForegroundColor Yellow
}

# Verify Azure CLI is installed
try {
    az version | Out-Null
    Write-Host " Azure CLI is installed" -ForegroundColor Green
} catch {
    Write-Host " Azure CLI is not installed. Please install it from https://aka.ms/installazurecliwindows" -ForegroundColor Red
    exit 1
}

# Verify logged in to Azure
Write-Host "`n Checking Azure login status..." -ForegroundColor Cyan
$account = az account show 2>$null
if (-not $account) {
    Write-Host " Not logged in to Azure. Running 'az login'..." -ForegroundColor Yellow
    az login
}

$subscriptionName = az account show --query name -o tsv
Write-Host " Logged in to subscription: $subscriptionName" -ForegroundColor Green

Write-Host "`n Deployment Configuration:" -ForegroundColor Cyan
Write-Host "   Resource Group: $ResourceGroupName" -ForegroundColor White
Write-Host "   Location: $Location" -ForegroundColor White
Write-Host "   App Name: $AppName" -ForegroundColor White
Write-Host "   Container Registry: $AcrName" -ForegroundColor White
Write-Host "   Tenant ID: $TenantId" -ForegroundColor White

Write-Host "`n⏸️  Press any key to continue or Ctrl+C to cancel..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

# Step 1: Create Resource Group
Write-Host "`n[1/9]  Creating Resource Group..." -ForegroundColor Green
az group create `
    --name $ResourceGroupName `
    --location $Location `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "       Resource Group created" -ForegroundColor Green
} else {
    Write-Host "       Failed to create Resource Group" -ForegroundColor Red
    exit 1
}

# Step 2: Create Azure Container Registry
Write-Host "`n[2/9]  Creating Azure Container Registry..." -ForegroundColor Green
Write-Host "      This may take a few minutes..." -ForegroundColor Yellow

az acr create `
    --resource-group $ResourceGroupName `
    --name $AcrName `
    --sku Basic `
    --admin-enabled true `
    --output none

if ($LASTEXITCODE -ne 0) {
    Write-Host "       Failed to create ACR" -ForegroundColor Red
    exit 1
}

$acrLoginServer = az acr show --name $AcrName --query loginServer --output tsv
$acrUsername = az acr credential show --name $AcrName --query username --output tsv
$acrPassword = az acr credential show --name $AcrName --query passwords[0].value --output tsv

Write-Host "       ACR created: $acrLoginServer" -ForegroundColor Green

# Step 3: Build and Push Backend Docker Image
Write-Host "`n[3/9]  Building and pushing Backend image..." -ForegroundColor Green
Write-Host "      This may take 5-10 minutes..." -ForegroundColor Yellow

az acr build `
    --registry $AcrName `
    --image architect-agent-backend:latest `
    --file Dockerfile.backend `
    . `
    --output table

if ($LASTEXITCODE -ne 0) {
    Write-Host "       Failed to build Backend image" -ForegroundColor Red
    exit 1
}

Write-Host "       Backend image built and pushed" -ForegroundColor Green

# Step 4: Build and Push Frontend Docker Image
Write-Host "`n[4/9]  Building and pushing Frontend image..." -ForegroundColor Green
Write-Host "      This may take 5-10 minutes..." -ForegroundColor Yellow

az acr build `
    --registry $AcrName `
    --image architect-agent-frontend:latest `
    --file Dockerfile.frontend `
    . `
    --output table

if ($LASTEXITCODE -ne 0) {
    Write-Host "       Failed to build Frontend image" -ForegroundColor Red
    exit 1
}

Write-Host "       Frontend image built and pushed" -ForegroundColor Green

# Step 5: Create Log Analytics Workspace
Write-Host "`n[5/9]  Creating Log Analytics Workspace..." -ForegroundColor Green

az monitor log-analytics workspace create `
    --resource-group $ResourceGroupName `
    --workspace-name $logAnalyticsName `
    --location $Location `
    --output none

$logAnalyticsId = az monitor log-analytics workspace show `
    --resource-group $ResourceGroupName `
    --workspace-name $logAnalyticsName `
    --query customerId `
    --output tsv

$logAnalyticsKey = az monitor log-analytics workspace get-shared-keys `
    --resource-group $ResourceGroupName `
    --workspace-name $logAnalyticsName `
    --query primarySharedKey `
    --output tsv

Write-Host "       Log Analytics Workspace created" -ForegroundColor Green

# Step 6: Create Container Apps Environment
Write-Host "`n[6/9]  Creating Container Apps Environment..." -ForegroundColor Green
Write-Host "      This may take a few minutes..." -ForegroundColor Yellow

az containerapp env create `
    --name $containerAppEnvName `
    --resource-group $ResourceGroupName `
    --location $Location `
    --logs-workspace-id $logAnalyticsId `
    --logs-workspace-key $logAnalyticsKey `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "       Container Apps Environment created" -ForegroundColor Green
} else {
    Write-Host "       Failed to create Container Apps Environment" -ForegroundColor Red
    exit 1
}

# Step 7: Deploy Backend Container App
Write-Host "`n[7/9]  Deploying Backend Container App..." -ForegroundColor Green

az containerapp create `
    --name $backendAppName `
    --resource-group $ResourceGroupName `
    --environment $containerAppEnvName `
    --image "$acrLoginServer/architect-agent-backend:latest" `
    --registry-server $acrLoginServer `
    --registry-username $acrUsername `
    --registry-password $acrPassword `
    --target-port 8000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars `
        "PROJECT_ENDPOINT=$ProjectEndpoint" `
        "MODEL_DEPLOYMENT_NAME=$ModelDeploymentName" `
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true" `
        "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true" `
        "OTEL_SERVICE_NAME=architect-agent" `
    --output none

$backendUrl = az containerapp show `
    --name $backendAppName `
    --resource-group $ResourceGroupName `
    --query properties.configuration.ingress.fqdn `
    --output tsv

$backendUrl = "https://$backendUrl"
Write-Host "       Backend deployed: $backendUrl" -ForegroundColor Green

# Step 8: Deploy Frontend Container App
Write-Host "`n[8/9]  Deploying Frontend Container App..." -ForegroundColor Green

az containerapp create `
    --name $frontendAppName `
    --resource-group $ResourceGroupName `
    --environment $containerAppEnvName `
    --image "$acrLoginServer/architect-agent-frontend:latest" `
    --registry-server $acrLoginServer `
    --registry-username $acrUsername `
    --registry-password $acrPassword `
    --target-port 3000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --env-vars "NEXT_PUBLIC_API_URL=$backendUrl" `
    --output none

$frontendUrl = az containerapp show `
    --name $frontendAppName `
    --resource-group $ResourceGroupName `
    --query properties.configuration.ingress.fqdn `
    --output tsv

$frontendUrl = "https://$frontendUrl"
Write-Host "       Frontend deployed: $frontendUrl" -ForegroundColor Green

# Step 9: Enable Managed Identity for Backend
Write-Host "`n[9/9]  Enabling Managed Identity for Backend..." -ForegroundColor Green

az containerapp identity assign `
    --name $backendAppName `
    --resource-group $ResourceGroupName `
    --system-assigned `
    --output none

$backendIdentityId = az containerapp identity show `
    --name $backendAppName `
    --resource-group $ResourceGroupName `
    --query principalId `
    --output tsv

Write-Host "       Backend Managed Identity: $backendIdentityId" -ForegroundColor Green

# Summary and Next Steps
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "              DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Application URLs:" -ForegroundColor Cyan
Write-Host "   Frontend: $frontendUrl" -ForegroundColor White
Write-Host "   Backend:  $backendUrl" -ForegroundColor White
Write-Host ""
Write-Host "Backend Managed Identity:" -ForegroundColor Cyan
Write-Host "   Principal ID: $backendIdentityId" -ForegroundColor White
Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host "NEXT STEPS - Complete these manually:" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "STEP 1: Grant Backend Access to Azure AI Project" -ForegroundColor Green
Write-Host "-----------------------------------------------------------" -ForegroundColor Gray
Write-Host ""
Write-Host "Run this command (replace YOUR_AI_PROJECT_RESOURCE_ID):" -ForegroundColor White
Write-Host ""
Write-Host "az role assignment create `` " -ForegroundColor Cyan
Write-Host "  --assignee $backendIdentityId `` " -ForegroundColor Cyan
Write-Host "  --role `"Cognitive Services User`" `` " -ForegroundColor Cyan
Write-Host "  --scope YOUR_AI_PROJECT_RESOURCE_ID" -ForegroundColor Cyan
Write-Host ""
Write-Host "To find your AI Project Resource ID:" -ForegroundColor White
Write-Host "1. Go to Azure Portal" -ForegroundColor White
Write-Host "2. Navigate to your Azure AI Project" -ForegroundColor White
Write-Host "3. Go to Properties" -ForegroundColor White
Write-Host "4. Copy the Resource ID" -ForegroundColor White
Write-Host ""
Write-Host "STEP 2: Configure Azure AD Authentication" -ForegroundColor Green
Write-Host "-----------------------------------------------------------" -ForegroundColor Gray
Write-Host ""
Write-Host "1. Go to: https://portal.azure.com (App Registrations)" -ForegroundColor White
Write-Host ""
Write-Host "2. Click 'New registration'" -ForegroundColor White
Write-Host "   - Name: $frontendAppName" -ForegroundColor White
Write-Host "   - Supported account types: Single tenant" -ForegroundColor White
Write-Host "   - Redirect URI: Web - $frontendUrl/.auth/login/aad/callback" -ForegroundColor White
Write-Host "   - Click Register" -ForegroundColor White
Write-Host ""
Write-Host "3. Copy the 'Application (client) ID'" -ForegroundColor White
Write-Host ""
Write-Host "4. Go to 'Certificates `& secrets'" -ForegroundColor White
Write-Host "   - Click 'New client secret'" -ForegroundColor White
Write-Host "   - Description: Container App Auth" -ForegroundColor White
Write-Host "   - Expires: Choose duration" -ForegroundColor White
Write-Host "   - Click Add" -ForegroundColor White
Write-Host "   - Copy the secret VALUE (not the Secret ID)" -ForegroundColor White
Write-Host ""
Write-Host "5. Run this command with your values:" -ForegroundColor White
Write-Host ""
Write-Host "az containerapp auth microsoft update `` " -ForegroundColor Cyan
Write-Host "  --name $frontendAppName `` " -ForegroundColor Cyan
Write-Host "  --resource-group $ResourceGroupName `` " -ForegroundColor Cyan
Write-Host "  --client-id YOUR_CLIENT_ID `` " -ForegroundColor Cyan
Write-Host "  --client-secret YOUR_CLIENT_SECRET `` " -ForegroundColor Cyan
Write-Host "  --issuer https://login.microsoftonline.com/$TenantId/v2.0 `` " -ForegroundColor Cyan
Write-Host "  --allowed-audiences $frontendUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "6. Enable authentication:" -ForegroundColor White
Write-Host ""
Write-Host "az containerapp auth update `` " -ForegroundColor Cyan
Write-Host "  --name $frontendAppName `` " -ForegroundColor Cyan
Write-Host "  --resource-group $ResourceGroupName `` " -ForegroundColor Cyan
Write-Host "  --enabled true `` " -ForegroundColor Cyan
Write-Host "  --action RedirectToLoginPage `` " -ForegroundColor Cyan
Write-Host "  --redirect-provider azureactivedirectory" -ForegroundColor Cyan
Write-Host ""
Write-Host "STEP 3: Test Your Application" -ForegroundColor Green
Write-Host "-----------------------------------------------------------" -ForegroundColor Gray
Write-Host ""
Write-Host "Open your browser to:" -ForegroundColor White
Write-Host "$frontendUrl?service=Azure%20OpenAI" -ForegroundColor Cyan
Write-Host ""
Write-Host "You should be redirected to Microsoft login page." -ForegroundColor White
Write-Host "After signing in with your corporate account, you'll see the app." -ForegroundColor White
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Deployment details saved to: deployment-info.txt" -ForegroundColor Green
Write-Host ""

# Save deployment info to file
$deploymentDate = Get-Date
$deploymentInfo = @"
Deployment Information
======================
Date: $deploymentDate
Resource Group: $ResourceGroupName
Location: $Location

Application URLs:
  Frontend: $frontendUrl
  Backend: $backendUrl

Container Registry: $acrLoginServer

Backend Managed Identity: $backendIdentityId

Container Apps:
  Frontend: $frontendAppName
  Backend: $backendAppName
  Environment: $containerAppEnvName

Log Analytics: $logAnalyticsName

Update Commands:
================

Update Backend:
az acr build --registry $AcrName --image architect-agent-backend:latest --file Dockerfile.backend .
az containerapp update --name $backendAppName --resource-group $ResourceGroupName --image $acrLoginServer/architect-agent-backend:latest

Update Frontend:
az acr build --registry $AcrName --image architect-agent-frontend:latest --file Dockerfile.frontend .
az containerapp update --name $frontendAppName --resource-group $ResourceGroupName --image $acrLoginServer/architect-agent-frontend:latest

View Logs:
az containerapp logs show --name $backendAppName --resource-group $ResourceGroupName --follow
az containerapp logs show --name $frontendAppName --resource-group $ResourceGroupName --follow
"@

$deploymentInfo | Out-File -FilePath "deployment-info.txt" -Encoding UTF8

Write-Host "[SUCCESS] All done! Follow the NEXT STEPS above to complete the setup.`n" -ForegroundColor Green
