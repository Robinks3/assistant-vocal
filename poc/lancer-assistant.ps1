# Lance le POC complet : LLM (s'il ne tourne pas déjà) puis l'assistant au micro.
# Assistant vocal local v0.6.0, 2026-10-12.
# Usage : powershell -ExecutionPolicy Bypass -File poc\lancer-assistant.ps1 [-Reveil] [-Essai]
#   -Reveil : écoute le mot de réveil de la configuration au lieu de la touche Entrée
#   -Essai  : comprend et répond, mais n'agit sur rien dans la maison
param([switch]$Reveil, [switch]$Essai)
$ErrorActionPreference = 'Stop'
$projet = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projet '.venv\Scripts\python.exe'

function LlmPret {
  try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8080/health).StatusCode -eq 200 }
  catch { $false }
}

if (-not (LlmPret)) {
  Write-Host 'Démarrage du LLM dans une fenêtre séparée (Qwen3.5-9B sur la carte graphique)...'
  Start-Process powershell -WindowStyle Minimized -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'lancer-llm.ps1'))
  $t0 = Get-Date
  while (-not (LlmPret)) {
    if (((Get-Date) - $t0).TotalSeconds -gt 90) { throw 'Le LLM ne répond pas après 90 s, voir la fenêtre réduite.' }
    Start-Sleep -Seconds 1
  }
  Write-Host ("LLM prêt en {0:N0} s." -f ((Get-Date) - $t0).TotalSeconds)
} else {
  Write-Host 'LLM déjà en marche.'
}

$options = @((Join-Path $PSScriptRoot 'assistant.py'))
if ($Reveil) { $options += '--reveil' }
if ($Essai) { $options += '--essai' }
& $python @options
