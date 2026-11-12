# One-shot local start for Windows: builds the frontend and serves everything on http://localhost:8000
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Pick up tools installed after this terminal was opened (e.g. Node.js)
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "npm not found - install Node.js LTS: winget install OpenJS.NodeJS.LTS" }

if (-not (Test-Path backend\.env)) { Copy-Item backend\.env.example backend\.env; Write-Host "Created backend\.env - fill in COMPASS_API_KEY" }

Push-Location frontend
if (-not (Test-Path node_modules)) { npm install }
npm run build
Pop-Location

Push-Location backend
pip install -q -r requirements.txt
Write-Host "FlowHub -> http://localhost:8000"
python -m uvicorn app.main:app --port 8000
Pop-Location
