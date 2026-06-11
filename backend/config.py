"""アプリ全体の設定。銘柄リスト・APIキー・リスク設定。"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# ---- リスク設定 ----
CAPITAL_JPY = float(os.getenv("CAPITAL_JPY", "1000000"))
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "1.0"))
DAILY_MAX_LOSS_JPY = float(os.getenv("DAILY_MAX_LOSS_JPY", "30000"))
MAX_CONSEC_LOSSES = int(os.getenv("MAX_CONSEC_LOSSES", "3"))
FALLBACK_USDJPY = float(os.getenv("FALLBACK_USDJPY", "150"))

# ---- APIキー ----
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "").strip()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_USER_ID = os.getenv("LINE_USER_ID", "").strip()
ENABLE_INDICES = os.getenv("ENABLE_INDICES", "false").lower() == "true"

# ---- データ保存先 ----
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "signal.db"
BACKTEST_DIR = DATA_DIR / "backtests"
BACKTEST_DIR.mkdir(exist_ok=True)

# ---- 銘柄定義 ----
# source: binance(無料・WebSocketで秒単位) / twelvedata(無料枠は約90秒間隔のローテーション更新)
# pip: 表示用のpip/ポイント単位, jpy_quote: 決済通貨がJPYか
SYMBOLS = {
    # 仮想通貨 (Binance公開API: キー不要・秒単位)
    "BTCUSD": {"source": "binance", "api": "BTCUSDT", "type": "crypto", "pip": 1.0,    "name": "ビットコイン"},
    "ETHUSD": {"source": "binance", "api": "ETHUSDT", "type": "crypto", "pip": 0.1,    "name": "イーサリアム"},
    "SOLUSD": {"source": "binance", "api": "SOLUSDT", "type": "crypto", "pip": 0.01,   "name": "ソラナ"},
    "XRPUSD": {"source": "binance", "api": "XRPUSDT", "type": "crypto", "pip": 0.0001, "name": "リップル"},
    # FX (Twelve Data 無料枠)
    "USDJPY": {"source": "twelvedata", "api": "USD/JPY", "type": "fx", "pip": 0.01,   "jpy_quote": True,  "name": "ドル円"},
    "EURUSD": {"source": "twelvedata", "api": "EUR/USD", "type": "fx", "pip": 0.0001, "jpy_quote": False, "name": "ユーロドル"},
    "GBPUSD": {"source": "twelvedata", "api": "GBP/USD", "type": "fx", "pip": 0.0001, "jpy_quote": False, "name": "ポンドドル"},
    "AUDUSD": {"source": "twelvedata", "api": "AUD/USD", "type": "fx", "pip": 0.0001, "jpy_quote": False, "name": "豪ドル米ドル"},
    "EURJPY": {"source": "twelvedata", "api": "EUR/JPY", "type": "fx", "pip": 0.01,   "jpy_quote": True,  "name": "ユーロ円"},
    "GBPJPY": {"source": "twelvedata", "api": "GBP/JPY", "type": "fx", "pip": 0.01,   "jpy_quote": True,  "name": "ポンド円"},
    # 貴金属 (Twelve Data 無料枠)
    "XAUUSD": {"source": "twelvedata", "api": "XAU/USD", "type": "metal", "pip": 0.1,   "jpy_quote": False, "name": "ゴールド"},
    "XAGUSD": {"source": "twelvedata", "api": "XAG/USD", "type": "metal", "pip": 0.01,  "jpy_quote": False, "name": "シルバー"},
}

# 株価指数・原油はTwelve Dataの有料プラン(Grow以上)が必要 → .envでONにできる
INDEX_SYMBOLS = {
    "NAS100": {"source": "twelvedata", "api": "NDX",     "type": "index", "pip": 1.0,  "jpy_quote": False, "name": "ナスダック100"},
    "US30":   {"source": "twelvedata", "api": "DJI",     "type": "index", "pip": 1.0,  "jpy_quote": False, "name": "NYダウ"},
    "SPX500": {"source": "twelvedata", "api": "SPX",     "type": "index", "pip": 0.1,  "jpy_quote": False, "name": "S&P500"},
    "USOIL":  {"source": "twelvedata", "api": "WTI/USD", "type": "cfd",   "pip": 0.01, "jpy_quote": False, "name": "WTI原油"},
}
if ENABLE_INDICES:
    SYMBOLS.update(INDEX_SYMBOLS)

# ---- シグナル判定しきい値 (仕様準拠) ----
TH_STRONG_BUY = 85
TH_BUY = 70
TH_SELL = 39   # 20〜39: SELL
TH_STRONG_SELL = 19  # 0〜19: STRONG SELL

# ---- 分析設定 ----
MAIN_TF = "5min"          # メイン時間足
ANALYZE_INTERVAL = 3      # 分析更新間隔(秒)
BROADCAST_INTERVAL = 1    # 配信間隔(秒) ※価格は秒単位
TD_POLL_INTERVAL = 8.5    # Twelve Data無料枠: 8回/分 → 約8.5秒に1リクエスト
NOTIFY_COOLDOWN_SEC = 900 # 同一銘柄・同一シグナルの再通知は15分空ける
