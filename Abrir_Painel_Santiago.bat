@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ====================================================================
echo   EDEC - PAINEL SANTIAGO (SERVIDOR LOCAL SEGURO + NUVEM 24/7)
echo ====================================================================
start "" "http://localhost:8080"
echo.
echo [1] Acesso na Nuvem (4G/5G/Qualquer Lugar): https://vicf73.github.io/painel-santiago/
echo [2] Tabela Story Executivo (Nuvem):         https://vicf73.github.io/painel-santiago/apresentacao.html
echo [3] A iniciar Servidor HTTP Local Seguro na porta 8080...
echo     (Nota: Tunel SSH publico desativado por seguranca - Etapa 2)
echo.
python servidor_painel_santiago.py
pause
