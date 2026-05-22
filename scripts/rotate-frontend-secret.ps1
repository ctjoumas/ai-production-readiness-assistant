# Script to rotate the frontend Container App client secret
# Run this monthly when you generate a new client secret in Azure AD

param(
    [Parameter(Mandatory=$true)]
    [string]$NewClientSecret
)

$subscriptionId = "dc260a42-f9db-45cb-9feb-cfc082d05f62"
$resourceGroup = "rg-architect-agent"
$containerAppName = "prod-readiness-chatbot-frontend"
$secretName = "aad-client-secret"

Write-Host "Setting subscription..." -ForegroundColor Cyan
az account set --subscription $subscriptionId

Write-Host "Removing old secret..." -ForegroundColor Cyan
az containerapp secret remove `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --secret-names $secretName

Write-Host "Adding new secret..." -ForegroundColor Cyan
az containerapp secret set `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --secrets "$secretName=$NewClientSecret"

Write-Host "Updating auth configuration..." -ForegroundColor Cyan
az containerapp auth update `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --set identityProviders.azureActiveDirectory.registration.clientSecretSettingName=$secretName

Write-Host "Getting active revision..." -ForegroundColor Cyan
$revision = az containerapp revision list `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --query "[?properties.active].name" `
    -o tsv

Write-Host "Restarting revision: $revision" -ForegroundColor Cyan
az containerapp revision restart `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --revision $revision

Write-Host "`nSecret rotation complete!" -ForegroundColor Green
Write-Host "Test your app at: https://prod-readiness-chatbot-frontend.purplepond-cf7bd915.eastus.azurecontainerapps.io" -ForegroundColor Yellow
