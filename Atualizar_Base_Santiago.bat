@echo off
chcp 65001 >nul
title EDEC - Pipeline ETL Contratos Santiago (Supabase)
cd /d "%~dp0"
echo ========================================================================
echo   EDEC - ATUALIZACAO AUTOMATICA DA BASE DE SANTIAGO PARA O SUPABASE
echo ========================================================================
echo.
python etl_santiago_supabase.py
echo.
python publicar_painel_web.py
echo.
if /i "%~1" NEQ "--auto" pause
