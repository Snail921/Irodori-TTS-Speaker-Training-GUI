@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
title Irodori Speaker Training GUI - KEEP THIS WINDOW OPEN
set "GUI_ROOT=%~dp0"
set "IRODORI_CANDIDATE="
for %%F in (speaker_training_gui.py speaker_training_job_runner.py speaker_training_transcribe_client.py speaker_training_test_worker.py open_when_ready.ps1) do (
  if not exist "%GUI_ROOT%%%F" (
    echo [ERROR] Missing GUI file: %%F
    echo Copy all six GUI files into the same folder.
    pause
    exit /b 1
  )
)

call :select_irodori "%GUI_ROOT%"
if not defined IRODORI_CANDIDATE if defined IRODORI_TTS_ROOT call :select_irodori "%IRODORI_TTS_ROOT%"
if not defined IRODORI_CANDIDATE call :select_irodori "%GUI_ROOT%.."
if not defined IRODORI_CANDIDATE call :select_irodori "%GUI_ROOT%..\Irodori-TTS"
if not defined IRODORI_CANDIDATE (
  for /d %%D in ("%GUI_ROOT%..\*") do if not defined IRODORI_CANDIDATE call :select_irodori "%%~fD"
)
if not defined IRODORI_CANDIDATE (
  echo [ERROR] The official Irodori-TTS repository could not be found.
  echo Copy the Speaker Training GUI files into your configured Irodori-TTS folder.
  echo For a separate installation, set:
  echo   IRODORI_TTS_ROOT=C:\path\to\Irodori-TTS
  pause
  exit /b 1
)
set "IRODORI_TTS_ROOT=%IRODORI_CANDIDATE%"
cd /d "%IRODORI_TTS_ROOT%"
where uv.exe >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv could not be executed.
  echo Install uv and run the official Irodori-TTS setup first.
  pause
  exit /b 1
)
uv run --no-sync python -c "import gradio, torch, irodori_tts" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] The official Irodori-TTS uv environment is not ready.
  echo Run the setup command appropriate for your hardware, for example:
  echo   uv sync --extra cu128
  pause
  exit /b 1
)

if not defined MIRAI_WHISPER_URL set "MIRAI_WHISPER_URL=http://127.0.0.1:8000"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-RestMethod -Uri ($env:MIRAI_WHISPER_URL.TrimEnd('/') + '/health') -TimeoutSec 5; if ($r.status -notin @('ok','loading')) { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
  echo [ERROR] The Whisper server is not ready: %MIRAI_WHISPER_URL%
  echo Start MiRai-Server-for-Whisper first, then run this batch again.
  pause
  exit /b 1
)

set "PORT_PID="
for /f "tokens=5" %%P in ('netstat.exe -ano -p tcp ^| findstr /R /C:"127.0.0.1:7862 .*LISTENING"') do set "PORT_PID=%%P"
if defined PORT_PID (
  echo ============================================================
  echo [ERROR] Port 7862 is already in use by PID %PORT_PID%.
  echo An older Speaker Training GUI may still be running.
  echo Press Ctrl+C in the existing GUI console, then start this batch again.
  echo ============================================================
  pause
  exit /b 2
)
echo ============================================================
echo  Irodori Speaker Training GUI
echo  KEEP THIS WINDOW OPEN while using the GUI.
echo  Press Ctrl+C in this window to stop the GUI and its jobs.
echo  GUI: http://127.0.0.1:7862
echo  Whisper: %MIRAI_WHISPER_URL%
echo  Irodori repository: %IRODORI_TTS_ROOT%
echo  GUI data: %GUI_ROOT%
echo  UI Version: persistent-test-worker-v3 / 2026-10-06
echo  Long jobs run in the background and can be stopped in the GUI.
echo ============================================================
uv run --no-sync python "%GUI_ROOT%speaker_training_gui.py" --server-name 127.0.0.1 --server-port 7862
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Speaker Training GUI has stopped. Exit code: %EXIT_CODE%
echo This window will remain open until you press a key.
pause
exit /b %EXIT_CODE%

:select_irodori
if defined IRODORI_CANDIDATE exit /b 0
if not exist "%~1\pyproject.toml" exit /b 0
if not exist "%~1\train.py" exit /b 0
if not exist "%~1\infer.py" exit /b 0
if not exist "%~1\prepare_manifest.py" exit /b 0
if not exist "%~1\configs\train_v4_small_speaker_inversion.yaml" exit /b 0
for %%R in ("%~1") do set "IRODORI_CANDIDATE=%%~fR"
exit /b 0
