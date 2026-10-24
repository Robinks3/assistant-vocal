# Lance le LLM de l'assistant vocal (llama-server Vulkan, Qwen3.5-9B Q6_K) sur 127.0.0.1:8080.
# Assistant vocal local v0.2.0, 2026-10-11.
# LM Studio n'est pas utilisé ici : il ignore enable_thinking=false et Qwen réfléchit alors
# 300 tokens avant de répondre (8 s au lieu d'une seconde).
$ErrorActionPreference = 'Stop'
$serveur = "$HOME\Documents\PROJET\LABO\llm\llama.cpp\llama-server.exe"
$modele = "$HOME\.lmstudio\models\lmstudio-community\Qwen3.5-9B-GGUF\Qwen3.5-9B-Q6_K.gguf"
# Contournement Resizable BAR désactivée (voir la note ia-locale du vault).
$env:GGML_VK_DISABLE_HOST_VISIBLE_VIDMEM = '1'
& $serveur -m $modele -dev Vulkan0 -ngl 99 -fa on -c 8192 -ctk q8_0 -ctv q8_0 -np 1 `
  --jinja --reasoning-budget 0 --chat-template-kwargs '{\"enable_thinking\":false}' `
  --host 127.0.0.1 --port 8080 --alias assistant-vocal
