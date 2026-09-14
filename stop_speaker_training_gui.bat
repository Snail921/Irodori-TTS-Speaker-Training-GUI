@echo off
setlocal
chcp 65001 >nul
title Stop Irodori Speaker Training GUI
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_speaker_training_gui.ps1" -Port 7862
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Speaker Training GUI stop check completed.
) else (
  echo Speaker Training GUI could not be stopped safely. Exit code: %EXIT_CODE%
)
pause
exit /b %EXIT_CODE%
