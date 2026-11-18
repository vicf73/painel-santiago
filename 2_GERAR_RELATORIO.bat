@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EDEC DPO - 2. Gerar Relatorios Executivos (DOCX e PDF)

echo ========================================================================
echo  GERACAO DE RELATORIOS EXECUTIVOS (VISAO EXECUTIVA GOLD - DPO)
echo ========================================================================
echo.
echo A gerar Relatorios Executivos (.docx e .pdf)...
python gerar_relatorio_executivo.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao gerar os relatorios. Feche o Word/PDF se estiver aberto.
    pause
    exit /b 1
)

echo.
echo ========================================================================
echo  RELATORIOS GERADOS COM SUCESSO! A abrir pasta relatorios...
echo ========================================================================
explorer "%~dp0relatorios"
pause
