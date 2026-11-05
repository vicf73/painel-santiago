@echo off
chcp 65001 >nul
title EDEC - Agendador Automatico do ETL Santiago
cd /d "%~dp0"
echo ============================================================================
echo   EDEC - CONFIGURACAO DE AGENDAMENTO AUTOMATICO MENSAL (WINDOWS SCHEDULER)
echo ============================================================================
echo.
echo A registar tarefa automatica "EDEC_ETL_Santiago_Mensal" para correr
echo no dia 2 de cada mes as 07:00...
echo.
schtasks /Create /F /SC MONTHLY /D 2 /ST 07:00 /TN "EDEC_ETL_Santiago_Mensal" /TR "\"%~dp0Atualizar_Base_Santiago.bat\""
echo.
if %ERRORLEVEL% EQU 0 (
    echo [OK] Tarefa agendada com sucesso no Windows Task Scheduler!
    echo      Para consultar: schtasks /Query /TN "EDEC_ETL_Santiago_Mensal"
) else (
    echo [AVISO] Execute este ficheiro como Administrador se desejar alterar a tarefa do sistema.
)
echo.
pause
