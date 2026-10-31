# Lance le LLM de l'assistant vocal (llama-server Vulkan, Qwen3.5-9B Q6_K) sur 127.0.0.1:8080.
# Assistant vocal local v0.2.0, 2026-10-11.
# LM Studio n'est pas utilisé ici : il ignore enable_thinking=false et Qwen réfléchit alors
# 300 tokens avant de répondre (8 s au lieu d'une seconde).
$ErrorActionPreference = 'Stop'
# Chemins lus dans l'environnement ou dans poc/.env (LLM_SERVEUR, LLM_MODELE), seules clés lues de ce fichier.
function Lire-Chemin($cle, $defaut) {
    $v = [Environment]::GetEnvironmentVariable($cle)
    if ($v) { return $v }
    $env_fichier = Join-Path $PSScriptRoot '.env'
    if (Test-Path $env_fichier) {
        $l = Select-String -Path $env_fichier -Pattern "^$cle=(.+)$" | Select-Object -First 1
        if ($l) { return $l.Matches[0].Groups[1].Value.Trim().Trim('"') }
    }
    return $defaut
}
$serveur = Lire-Chemin 'LLM_SERVEUR' (Join-Path $PSScriptRoot 'llm\llama-server.exe')
$modele = Lire-Chemin 'LLM_MODELE' (Join-Path $PSScriptRoot 'modeles\llm.gguf')
# Contournement Resizable BAR désactivée.
$env:GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM = '1'
& $serveur -m $modele -dev Vulkan0 -ngl 99 -fa on -c 8192 -ctk q8_0 -ctv q8_0 -np 1 `
  --jinja --reasoning-budget 0 --chat-template-kwargs '{\"enable_thinking\":false}' `
  --host 127.0.0.1 --port 8080 --alias assistant-vocal
