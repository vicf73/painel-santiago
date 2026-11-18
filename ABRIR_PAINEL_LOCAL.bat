@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EDEC DPO - Painel Santiago Local (com Exportacao para santiago\exportacoes)

echo A iniciar servidor local em http://127.0.0.1:8765/painel_santiago.html ...
echo As exportacoes CSV serao guardadas automaticamente em:
echo   %~dp0exportacoes\
echo.
start "" "http://127.0.0.1:8765/painel_santiago.html"
python servidor_painel.py
pause
