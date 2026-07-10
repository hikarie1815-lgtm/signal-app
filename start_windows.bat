@echo off
rem SIGNAL DESK 起動スクリプト（Windows）
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo python が見つかりません。https://www.python.org/ からインストールし、
    echo 「Add Python to PATH」にチェックを入れてください。
    pause
    exit /b 1
)

if not exist .env (
    copy .env.example .env >nul
    echo .env を作成しました。メモ帳で開いて TWELVEDATA_API_KEY を設定後、
    echo もう一度このファイルを実行してください。
    notepad .env
    exit /b 0
)

python -m pip install -r requirements.txt
cd backend
python main.py
pause
