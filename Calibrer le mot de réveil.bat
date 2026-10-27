@echo off
rem Double-clic : calibrage guidé du mot de réveil de la configuration (aucune commande exécutée). v0.8.0
rem Fermer d abord le serveur satellite s il tourne (même port 8765).
chcp 65001 >nul
set LLM_FOURNISSEUR=claude
"%~dp0.venv\Scripts\python.exe" "%~dp0poc\serveur_satellite.py" --calibrer --essai
pause
