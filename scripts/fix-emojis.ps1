# Fix emoji encoding issues in deploy-aca.ps1
$scriptPath = "c:\PreProdChecklistAgent\architect_agent\scripts\deploy-aca.ps1"
$content = Get-Content $scriptPath -Raw -Encoding UTF8

# Replace emojis with text equivalents
$replacements = @{
    '✅' = '[OK]'
    '❌' = '[ERROR]'
    '📦' = '[ACR]'
    '🔐' = '[AUTH]'
    '📋' = '[INFO]'
    '⏸️' = ''
    '📁' = '[RG]'
    '🔨' = '[BUILD]'
    '📊' = '[LOGS]'
    '🌐' = '[ENV]'
    '🚀' = '[DEPLOY]'
    '🔒' = '[ID]'
}

foreach ($emoji in $replacements.Keys) {
    $content = $content.Replace($emoji, $replacements[$emoji])
}

# Write back with UTF8 encoding
$content | Out-File $scriptPath -Encoding UTF8 -NoNewline

Write-Host "Fixed emojis in deploy-aca.ps1" -ForegroundColor Green
