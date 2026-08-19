#!/bin/bash
# ダブルクリック（またはターミナルで bash start_mac.sh）で起動します。
cd "$(dirname "$0")" || exit 1

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "Python が見つかりません。https://www.python.org/ からインストールしてください。"
  read -r -p "Enterキーで閉じます" _
  exit 1
fi

if [ ! -d .venv ]; then
  echo "初回準備をしています（1〜2分かかります）…"
  "$PY" -m venv .venv || exit 1
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q -r requirements.txt || exit 1

PORT=${PORT:-8000}
( sleep 2
  if command -v open > /dev/null; then open "http://localhost:$PORT"
  elif command -v xdg-open > /dev/null; then xdg-open "http://localhost:$PORT"
  fi ) &

echo ""
echo "  KI-LEAGUE 対戦表を起動しました → http://localhost:$PORT"
echo "  同じWi-Fiのスマホからは http://<このPCのIPアドレス>:$PORT"
echo "  終わるときは Control + C"
echo ""
python -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
