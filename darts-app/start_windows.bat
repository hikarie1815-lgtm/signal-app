@echo off
rem ダブルクリックで起動します。
cd /d "%~dp0"
chcp 65001 > nul

where python > nul 2>&1
if errorlevel 1 (
  echo Python が見つかりません。https://www.python.org/ からインストールしてください。
  echo インストール時は「Add Python to PATH」に必ずチェックを入れてください。
  pause
  exit /b 1
)

if not exist .venv (
  echo 初回準備をしています^(1〜2分かかります^)...
  python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt || (pause & exit /b 1)

if "%PORT%"=="" set PORT=8000
start "" http://localhost:%PORT%
echo.
echo   KI-LEAGUE 対戦表を起動しました -^> http://localhost:%PORT%
echo   同じWi-Fiのスマホからは http://^<このPCのIPアドレス^>:%PORT%
echo   終わるときは Ctrl + C
echo.
python -m uvicorn backend.main:app --host 0.0.0.0 --port %PORT%
pause
