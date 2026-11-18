@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EDEC DPO - Atualizacao Mensal Lakehouse e Relatorios Executivos

echo ========================================================================
echo  ATUALIZACAO MENSAL AUTOMATIZADA - SANTIAGO (DPO)
echo ========================================================================
echo.
echo [1/4] A organizar e descompactar novos ficheiros de fontes (scrip -^> Atual_script)...
python organizar_fontes_mensais.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao organizar as fontes mensais.
    pause
    exit /b 1
)

echo.
echo [2/4] A executar ETL completo (Bronze - Silver - Gold + Supabase)...
python etl_lakehouse.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha no ETL Lakehouse. Verifique os ficheiros fonte.
    pause
    exit /b 1
)

echo.
echo [3/4] A executar testes de integridade e qualidade de dados...
python testar_lakehouse.py
if errorlevel 1 (
    echo.
    echo [ERRO] Testes de qualidade falharam.
    pause
    exit /b 1
)

echo.
echo [4/4] A gerar Relatorios Executivos (.docx e .pdf)...
python gerar_relatorio_executivo.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao gerar os relatorios. Feche o Word/PDF se estiver aberto.
    pause
    exit /b 1
)

echo.
echo ========================================================================
echo  PROCESSO CONCLUIDO COM SUCESSO! A abrir pasta relatorios...
echo ========================================================================
explorer "%~dp0relatorios"
pause
