@echo off
rem Double-clic : lance le serveur qui écoute le téléphone satellite (port 8765). v0.7.0
rem Cerveau Claude par API pour laisser la carte graphique libre. Ajouter --essai pour ne rien exécuter.
chcp 65001 >nul
set LLM_FOURNISSEUR=claude
"%~dp0.venv\Scripts\python.exe" "%~dp0poc\serveur_satellite.py" %*
pause
