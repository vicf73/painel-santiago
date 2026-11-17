@echo off
chcp 65001 >nul
title EDEC - Pipeline ETL Contratos Santiago (Supabase)
cd /d "%~dp0"
echo ========================================================================
echo   EDEC - ATUALIZACAO UNIFICADA SANTIAGO (ETL + LAKEHOUSE + PUBLICACAO)
echo ========================================================================
echo.
python etl_santiago_supabase.py
if %ERRORLEVEL% NEQ 0 echo [ERRO] Falha no etl_santiago_supabase.py
echo.
python etl_lakehouse.py
if %ERRORLEVEL% NEQ 0 echo [ERRO] Falha no etl_lakehouse.py
echo.
python publicar_painel_web.py
echo.
if /i "%~1" NEQ "--auto" pause
