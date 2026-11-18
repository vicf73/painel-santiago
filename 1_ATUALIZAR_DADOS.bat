@echo off
chcp 65001 >nul
cd /d "%~dp0"
title EDEC DPO - 1. Atualizar Dados Lakehouse (Bronze - Silver - Gold)

echo ========================================================================
echo  ATUALIZACAO DE DADOS LAKEHOUSE - SANTIAGO (DPO)
echo ========================================================================
echo.
echo [1/3] A organizar e descompactar novos ficheiros de fontes (scrip -^> Atual_script)...
python organizar_fontes_mensais.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao organizar as fontes mensais.
    pause
    exit /b 1
)

echo.
echo [2/3] A executar ETL completo (Bronze - Silver - Gold + Supabase)...
python etl_lakehouse.py
if errorlevel 1 (
    echo.
    echo [ERRO] Falha no ETL Lakehouse. Verifique os ficheiros fonte.
    pause
    exit /b 1
)

echo.
echo [3/3] A executar testes de integridade e qualidade de dados...
python testar_lakehouse.py
if errorlevel 1 (
    echo.
    echo [ERRO] Testes de qualidade falharam.
    pause
    exit /b 1
)

echo.
echo ========================================================================
echo  DADOS ATUALIZADOS E SINCRONIZADOS COM SUCESSO!
echo ========================================================================
pause
