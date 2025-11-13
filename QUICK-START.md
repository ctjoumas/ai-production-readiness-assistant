# Quick Start Deployment Checklist

## Before You Begin
- [ ] Azure CLI installed: https://aka.ms/installazurecliwindows
- [ ] Logged into Azure: Run `az login`
- [ ] Have your Azure AI Project endpoint URL
- [ ] Have your model deployment name (e.g., gpt-4)
- [ ] Know your Azure AD Tenant ID (from Azure Portal)

## Step 1: Gather Information

Fill in your values here:

```
Resource Group Name: _________________________________
Location (e.g., eastus): _____________________________
App Name: ___________________________________________
Tenant ID: __________________________________________
Project Endpoint: ___________________________________
Model Deployment Name: _______________________________
```

## Step 2: Run Deployment Script

```powershell
cd C:\PreProdChecklistAgent\architect_agent

.\scripts\deploy-aca.ps1 `
    -ResourceGroupName "YOUR_RG_NAME" `
    -Location "YOUR_LOCATION" `
    -AppName "YOUR_APP_NAME" `
    -TenantId "YOUR_TENANT_ID" `
    -ProjectEndpoint "YOUR_PROJECT_ENDPOINT" `
    -ModelDeploymentName "YOUR_MODEL_NAME"
```

Wait 20-30 minutes for deployment to complete.

## Step 3: Copy Your URLs

After deployment completes, copy these:

```
Frontend URL: ________________________________________
Backend URL: _________________________________________
Backend Identity ID: __________________________________
```

## Step 4: Grant Backend Access to AI Project

Option A - Azure CLI:
```powershell
az role assignment create `
    --assignee YOUR_BACKEND_IDENTITY_ID `
    --role "Cognitive Services User" `
    --scope YOUR_AI_PROJECT_RESOURCE_ID
```

Option B - Azure Portal:
1. Go to your AI Project > Access control (IAM)
2. Add role assignment > Cognitive Services User
3. Select your backend app (e.g., architect-agent-backend)
4. Save

## Step 5: Create Azure AD App Registration

1. Go to: https://portal.azure.com (App Registrations)
2. Click "New registration"
3. Name: (your frontend app name)
4. Single tenant
5. Redirect URI: https://YOUR_FRONTEND_URL/.auth/login/aad/callback
6. Click Register
7. Copy the "Application (client) ID": ____________________________

## Step 6: Create Client Secret

1. Go to Certificates & secrets
2. New client secret
3. Description: "Container App Auth"
4. Expires: 180 days or 1 year
5. Add
6. Copy the secret VALUE: ____________________________

## Step 7: Configure Authentication

Replace with your values and run:

```powershell
az containerapp auth microsoft update `
    --name YOUR_FRONTEND_APP_NAME `
    --resource-group YOUR_RESOURCE_GROUP `
    --client-id "YOUR_CLIENT_ID" `
    --client-secret "YOUR_CLIENT_SECRET" `
    --issuer "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0" `
    --allowed-audiences "https://YOUR_FRONTEND_URL"

az containerapp auth update `
    --name YOUR_FRONTEND_APP_NAME `
    --resource-group YOUR_RESOURCE_GROUP `
    --enabled true `
    --action RedirectToLoginPage `
    --redirect-provider azureactivedirectory
```

## Step 8: Test!

Open in browser:
```
https://YOUR_FRONTEND_URL?service=Azure%20OpenAI
```

You should:
- [ ] Be redirected to Microsoft sign-in
- [ ] Sign in with your corporate email
- [ ] See the Production Readiness Chatbot
- [ ] Chatbot asks about Azure services

## Done! ✅

Your chatbot is now live and secured with Azure AD!

---

## Quick Commands Reference

### View Logs
```powershell
az containerapp logs show --name YOUR_BACKEND_NAME -g YOUR_RG --follow
```

### Update Backend
```powershell
az acr build --registry YOUR_ACR --image architect-agent-backend:latest --file Dockerfile.backend .
az containerapp update --name YOUR_BACKEND_NAME -g YOUR_RG --image YOUR_ACR.azurecr.io/architect-agent-backend:latest
```

### Update Frontend
```powershell
az acr build --registry YOUR_ACR --image architect-agent-frontend:latest --file Dockerfile.frontend .
az containerapp update --name YOUR_FRONTEND_NAME -g YOUR_RG --image YOUR_ACR.azurecr.io/architect-agent-frontend:latest
```

### Delete Everything
```powershell
az group delete --name YOUR_RG --yes --no-wait
```

---

For detailed instructions, see DEPLOYMENT.md
