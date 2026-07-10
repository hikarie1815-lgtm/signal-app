#!/bin/bash
# SIGNAL DESK 起動スクリプト（Mac / Linux）
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 が見つかりません。https://www.python.org/ からインストールしてください。"
    exit 1
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo ".env を作成しました。TWELVEDATA_API_KEY を設定後、もう一度実行してください。"
    exit 0
fi

python3 -m pip install -r requirements.txt
cd backend
python3 main.py
