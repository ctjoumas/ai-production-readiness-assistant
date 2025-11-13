# Azure Container Apps Deployment Guide
## Production Readiness Chatbot

This guide provides step-by-step instructions to deploy your Production Readiness Chatbot to Azure Container Apps with Azure AD authentication.

---

## 📋 Prerequisites

Before you begin, ensure you have:

1. ✅ **Azure Subscription** with appropriate permissions (Contributor or Owner role)
2. ✅ **Azure CLI installed** - [Download here](https://aka.ms/installazurecliwindows)
3. ✅ **Azure AI Project created** with a deployed model (e.g., GPT-4)
4. ✅ **Your Azure AD Tenant ID** - Find it in [Azure Portal](https://portal.azure.com) > Azure Active Directory > Overview
5. ✅ **PowerShell 5.1 or higher** (comes with Windows)

---

## 🚀 Step-by-Step Deployment

### Step 1: Gather Required Information

Before running the deployment script, collect these values:

| Parameter | Description | Example | Where to Find |
|-----------|-------------|---------|---------------|
| `ResourceGroupName` | Name for new resource group | `architect-agent-rg` | Choose any name |
| `Location` | Azure region | `eastus` | [Azure regions](https://azure.microsoft.com/en-us/explore/global-infrastructure/geographies/) |
| `AppName` | Application name (prefix) | `architect-agent` | Choose any name (lowercase, hyphens) |
| `TenantId` | Azure AD Tenant ID | `12345678-1234-...` | Azure Portal > Azure Active Directory > Overview |
| `ProjectEndpoint` | Azure AI Project endpoint | `https://myproject.cognitiveservices.azure.com/` | Azure AI Studio > Your Project > Overview |
| `ModelDeploymentName` | Model deployment name | `gpt-4` | Azure AI Studio > Deployments |

**To find your Project Endpoint:**
1. Go to [Azure AI Studio](https://ai.azure.com)
2. Select your project
3. Click on "Overview" or "Settings"
4. Copy the endpoint URL

**To find your Model Deployment Name:**
1. In Azure AI Studio, go to "Deployments"
2. Note the name of your deployed model (e.g., `gpt-4`, `gpt-35-turbo`)

---

### Step 2: Open PowerShell and Navigate to Project

```powershell
# Open PowerShell as Administrator (recommended)
cd C:\PreProdChecklistAgent\architect_agent
```

---

### Step 3: Run the Deployment Script

```powershell
.\scripts\deploy-aca.ps1 `
    -ResourceGroupName "architect-agent-rg" `
    -Location "eastus" `
    -AppName "architect-agent" `
    -TenantId "YOUR_TENANT_ID" `
    -ProjectEndpoint "YOUR_PROJECT_ENDPOINT" `
    -ModelDeploymentName "gpt-4"
```

**Replace the values above with your actual values!**

Example with real values:
```powershell
.\scripts\deploy-aca.ps1 `
    -ResourceGroupName "prod-readiness-chatbot-rg" `
    -Location "eastus" `
    -AppName "prod-readiness-chatbot" `
    -TenantId "a1b2c3d4-e5f6-7890-abcd-ef1234567890" `
    -ProjectEndpoint "https://myaiproject.cognitiveservices.azure.com/" `
    -ModelDeploymentName "gpt-4"
```

---

### Step 4: Wait for Deployment (20-30 minutes)

The script will:
1. ✅ Create Resource Group
2. ✅ Create Azure Container Registry
3. ✅ Build Backend Docker image (~5-10 minutes)
4. ✅ Build Frontend Docker image (~5-10 minutes)
5. ✅ Create Log Analytics Workspace
6. ✅ Create Container Apps Environment
7. ✅ Deploy Backend Container App
8. ✅ Deploy Frontend Container App
9. ✅ Enable Managed Identity

**You'll see progress messages throughout the deployment.**

At the end, you'll see your application URLs:
- Frontend: `https://architect-agent-frontend.something.azurecontainerapps.io`
- Backend: `https://architect-agent-backend.something.azurecontainerapps.io`

**⚠️ IMPORTANT:** Copy these URLs! You'll need them in the next steps.

---

### Step 5: Grant Backend Access to Azure AI Project

The backend needs permission to use your Azure AI Project. Run this command:

```powershell
# Get your AI Project Resource ID from Azure Portal
# Portal > Your AI Project > Properties > Resource ID

az role assignment create `
    --assignee YOUR_BACKEND_MANAGED_IDENTITY_ID `
    --role "Cognitive Services User" `
    --scope YOUR_AI_PROJECT_RESOURCE_ID
```

**Example:**
```powershell
az role assignment create `
    --assignee "12345678-1234-1234-1234-123456789abc" `
    --role "Cognitive Services User" `
    --scope "/subscriptions/abcd1234-ab12-cd34-ef56-abcdef123456/resourceGroups/my-ai-rg/providers/Microsoft.CognitiveServices/accounts/my-ai-project"
```

**Alternative - Using Azure Portal:**
1. Go to your Azure AI Project in Azure Portal
2. Click "Access control (IAM)"
3. Click "Add" > "Add role assignment"
4. Select "Cognitive Services User"
5. Click "Next"
6. Click "Select members"
7. Search for your backend app name (e.g., `architect-agent-backend`)
8. Select it and click "Review + assign"

---

### Step 6: Configure Azure AD Authentication

Now we'll set up Azure AD so only people in your organization can access the app.

#### 6.1: Create App Registration

1. Go to [Azure Portal - App Registrations](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps)

2. Click **"New registration"**

3. Fill in the form:
   - **Name:** `architect-agent-frontend` (or your frontend app name)
   - **Supported account types:** Select **"Accounts in this organizational directory only (Single tenant)"**
   - **Redirect URI:** 
     - Platform: **Web**
     - URL: `https://YOUR_FRONTEND_URL/.auth/login/aad/callback`
     - Example: `https://architect-agent-frontend.niceriver-12345678.eastus.azurecontainerapps.io/.auth/login/aad/callback`

4. Click **"Register"**

5. **Copy the "Application (client) ID"** - you'll need this!

#### 6.2: Create Client Secret

1. In your app registration, go to **"Certificates & secrets"**

2. Click **"New client secret"**

3. Fill in:
   - **Description:** `Container App Authentication`
   - **Expires:** Choose **"180 days"** or **"1 year"** (recommended)

4. Click **"Add"**

5. **⚠️ IMMEDIATELY copy the secret VALUE** (not the Secret ID) - you can't see it again!

#### 6.3: Configure Container App Authentication

Now configure your Container App to use Azure AD:

```powershell
# Replace with your actual values
az containerapp auth microsoft update `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg `
    --client-id "YOUR_CLIENT_ID" `
    --client-secret "YOUR_CLIENT_SECRET" `
    --issuer "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0" `
    --allowed-audiences "https://YOUR_FRONTEND_URL"
```

**Example with real values:**
```powershell
az containerapp auth microsoft update `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg `
    --client-id "a1b2c3d4-e5f6-7890-abcd-ef1234567890" `
    --client-secret "abc123~DefGhI456jKlMnO789pQrStUvWxYz" `
    --issuer "https://login.microsoftonline.com/a1b2c3d4-e5f6-7890-abcd-ef1234567890/v2.0" `
    --allowed-audiences "https://architect-agent-frontend.niceriver-12345678.eastus.azurecontainerapps.io"
```

#### 6.4: Enable Authentication

```powershell
az containerapp auth update `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg `
    --enabled true `
    --action RedirectToLoginPage `
    --redirect-provider azureactivedirectory
```

---

### Step 7: Test Your Application! 🎉

1. Open your browser to your frontend URL with a service parameter:
   ```
   https://YOUR_FRONTEND_URL?service=Azure%20OpenAI
   ```

2. You should be **automatically redirected** to the Microsoft sign-in page

3. Sign in with your **corporate email** (e.g., yourname@yourcompany.com)

4. After successful sign-in, you'll be redirected back to the chatbot

5. The chatbot should ask you about Azure services for production readiness review!

**Test with the query string:**
```
https://YOUR_FRONTEND_URL?service=Azure%20OpenAI
```

---

## 🔐 Security Verification

### Test Authentication Works:

1. **Open in a private/incognito browser window** (to test from "not logged in" state)
2. You should be redirected to Microsoft login
3. Only users from your organization should be able to sign in

### Test Unauthorized Access:

1. Try accessing with a personal Microsoft account (e.g., @outlook.com)
2. You should see **"Access Denied"** or similar error

---

## 📊 Monitoring & Management

### View Application Logs

**Backend logs:**
```powershell
az containerapp logs show `
    --name architect-agent-backend `
    --resource-group architect-agent-rg `
    --follow
```

**Frontend logs:**
```powershell
az containerapp logs show `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg `
    --follow
```

### View Application Metrics

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your Resource Group
3. Click on your Container App (frontend or backend)
4. Click "Metrics" to see requests, response times, CPU, memory, etc.

### Restart an App

```powershell
az containerapp revision restart `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg
```

---

## 🔄 Updating Your Application

When you make code changes, rebuild and redeploy:

### Update Backend:

```powershell
# Build new image
az acr build `
    --registry architectagentacr `
    --image architect-agent-backend:latest `
    --file Dockerfile.backend `
    .

# Deploy new image
az containerapp update `
    --name architect-agent-backend `
    --resource-group architect-agent-rg `
    --image architectagentacr.azurecr.io/architect-agent-backend:latest
```

### Update Frontend:

```powershell
# Build new image
az acr build `
    --registry architectagentacr `
    --image architect-agent-frontend:latest `
    --file Dockerfile.frontend `
    .

# Deploy new image
az containerapp update `
    --name architect-agent-frontend `
    --resource-group architect-agent-rg `
    --image architectagentacr.azurecr.io/architect-agent-frontend:latest
```

**Note:** Replace `architectagentacr` with your actual ACR name.

---

## 🛠️ Troubleshooting

### Problem: "Authentication not working"

**Check:**
1. Redirect URI in App Registration matches exactly (including `/.auth/login/aad/callback`)
2. Client secret hasn't expired
3. Tenant ID is correct
4. Run: `az containerapp auth show --name architect-agent-frontend --resource-group architect-agent-rg` to verify config

### Problem: "Backend can't access Azure AI"

**Check:**
1. Managed Identity has "Cognitive Services User" role on AI Project
2. PROJECT_ENDPOINT environment variable is correct
3. Check backend logs: `az containerapp logs show --name architect-agent-backend -g architect-agent-rg`

### Problem: "Container won't start"

**Check logs:**
```powershell
az containerapp logs show `
    --name architect-agent-backend `
    --resource-group architect-agent-rg `
    --tail 100
```

**Common issues:**
- Missing environment variables
- Wrong Docker image
- Insufficient memory/CPU

### Problem: "Port errors or connection refused"

**Check:**
- Backend target-port is 8000
- Frontend target-port is 3000
- Ingress is set to "external" for both apps

---

## 💰 Cost Estimates

Approximate monthly costs (USD, as of 2025):

| Service | Configuration | Estimated Cost |
|---------|--------------|----------------|
| Container Apps Environment | Shared | ~$50/month |
| Backend Container | 1 vCPU, 2GB RAM | ~$40/month |
| Frontend Container | 0.5 vCPU, 1GB RAM | ~$20/month |
| Azure Container Registry | Basic tier | ~$5/month |
| Log Analytics | Variable | ~$10-20/month |
| **Total** | | **~$125-135/month** |

**Note:** This does NOT include Azure AI Project costs (OpenAI model usage).

**To reduce costs:**
- Scale down to 0 replicas when not in use (dev/test only)
- Use consumption plan for Container Apps Environment
- Delete resources when not needed

---

## 🗑️ Cleanup / Delete Resources

To delete everything and stop incurring costs:

```powershell
az group delete --name architect-agent-rg --yes --no-wait
```

**⚠️ WARNING:** This deletes EVERYTHING in the resource group permanently!

---

## 📚 Additional Resources

- [Azure Container Apps Documentation](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Easy Auth Configuration](https://learn.microsoft.com/en-us/azure/container-apps/authentication)
- [Azure AI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/)
- [Managed Identity](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)

---

## ❓ Need Help?

If you encounter issues:

1. Check the **Troubleshooting** section above
2. Review the logs using the commands provided
3. Verify all prerequisites are met
4. Ensure all values (URLs, IDs) are copied correctly

---

## ✅ Success Checklist

- [ ] Deployment script completed successfully
- [ ] Frontend and Backend URLs are accessible
- [ ] Backend has access to Azure AI Project
- [ ] Azure AD app registration created
- [ ] Client secret generated and copied
- [ ] Authentication configured on Container App
- [ ] Can access app with corporate account
- [ ] Personal accounts are denied access
- [ ] Chatbot responds to production readiness questions
- [ ] Query string with `?service=Azure%20OpenAI` works

**Congratulations! Your Production Readiness Chatbot is now live! 🎉**
