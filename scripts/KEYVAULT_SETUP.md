# Automated Client Secret Management with Azure Key Vault
# This eliminates the need for monthly manual rotation!

## Overview
Instead of manually rotating secrets in Container Apps, use Azure Key Vault:
1. Store the client secret in Key Vault
2. Configure Container App to reference the Key Vault secret
3. When you rotate the secret in Key Vault, Container App automatically picks it up

## Benefits
- No manual Container App updates needed
- Secrets are centrally managed
- Audit trail in Key Vault
- Can set up automatic rotation policies

## Setup Steps

### 1. Create or Use Existing Key Vault
```powershell
$subscriptionId = "<YOUR_SUBSCRIPTION_ID>"
$resourceGroup = "<YOUR_RESOURCE_GROUP>"
$keyVaultName = "<YOUR_KEYVAULT_NAME>"  # Must be globally unique
$location = "eastus"

az account set --subscription $subscriptionId

# Create Key Vault if it doesn't exist
az keyvault create `
    --name $keyVaultName `
    --resource-group $resourceGroup `
    --location $location
```

### 2. Store the Client Secret in Key Vault
```powershell
$clientSecret = "<YOUR_CLIENT_SECRET>"

az keyvault secret set `
    --vault-name $keyVaultName `
    --name "aad-client-secret" `
    --value $clientSecret
```

### 3. Enable Managed Identity on Container App (if not already enabled)
```powershell
$containerAppName = "prod-readiness-chatbot-frontend"

az containerapp identity assign `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --system-assigned
```

### 4. Grant Container App Access to Key Vault
```powershell
# Get the managed identity principal ID
$principalId = az containerapp show `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --query "identity.principalId" `
    -o tsv

# Grant Key Vault Secrets User role
az role assignment create `
    --assignee $principalId `
    --role "Key Vault Secrets User" `
    --scope "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.KeyVault/vaults/$keyVaultName"
```

### 5. Update Container App to Reference Key Vault
```powershell
# Get the Key Vault secret URI
$secretUri = az keyvault secret show `
    --vault-name $keyVaultName `
    --name "aad-client-secret" `
    --query "id" `
    -o tsv

# Remove the old secret from Container App
az containerapp secret remove `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --secret-names "aad-client-secret"

# Add Key Vault reference (note: different syntax for Key Vault-backed secrets)
az containerapp update `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --set-env-vars "AAD_CLIENT_SECRET=secretref:aad-client-secret" `
    --secrets "aad-client-secret=keyvaultref:$secretUri,identityref:system"

# Update auth to use the secret
az containerapp auth update `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --set identityProviders.azureActiveDirectory.registration.clientSecretSettingName=aad-client-secret
```

### 6. Monthly Rotation (Now Much Simpler!)
When you need to rotate the secret each month:

```powershell
# 1. Generate new client secret in Azure AD App Registration (in Azure Portal)

# 2. Update ONLY Key Vault (Container App picks it up automatically)
$newClientSecret = "YOUR_NEW_SECRET_HERE"

az keyvault secret set `
    --vault-name $keyVaultName `
    --name "aad-client-secret" `
    --value $newClientSecret

# 3. Restart the Container App (optional, but recommended to pick up immediately)
$revision = az containerapp revision list `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --query "[?properties.active].name" `
    -o tsv

az containerapp revision restart `
    --name $containerAppName `
    --resource-group $resourceGroup `
    --revision $revision
```

## Alternative: Even Better with Logic App
For fully automated rotation without manual steps:

### Option A: Logic App Triggered by Key Vault Expiration
1. Set up Event Grid subscription on Key Vault for "Secret Near Expiry" events
2. Logic App receives event and:
   - Calls Azure AD API to create new client secret
   - Updates Key Vault with new secret
   - Restarts Container App

### Option B: Scheduled Logic App
1. Runs on the 1st of each month
2. Creates new client secret via Azure AD API
3. Updates Key Vault
4. Archives old secret
5. Sends notification

## Recommended Approach
Start with Key Vault integration (Steps 1-5 above), then monthly you only need:
1. Generate new secret in Azure Portal (App Registration)
2. Run: `az keyvault secret set --vault-name kv-architect-agent --name aad-client-secret --value "NEW_SECRET"`
3. Done! Much simpler than updating Container App directly.

For full automation, implement the Logic App solution later when you have time.
