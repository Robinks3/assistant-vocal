@echo off
rem Double-clic : lance le POC complet de l'assistant vocal (LLM puis micro). v0.6.0
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0poc\lancer-assistant.ps1" %*
pause
