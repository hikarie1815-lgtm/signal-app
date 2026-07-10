"""
ts_api.py — TradeScope用データ配信API（signal-desk アドオン）

役割:
  ブラウザ版TradeScopeに、FX・金のローソク足とリアルタイム価格を配信する。
  - FX主要10ペア: GMOコイン 外国為替FX Public API（キー不要・無料）
  - 金(XAUUSD): Binance PAXGUSDT（金現物価格に連動するトークン）で代替
  - その他の銘柄: TWELVEDATA_API_KEY（Render環境変数）があればTwelve Data
  サーバー側で強力にキャッシュするため、ブラウザが何秒ごとに叩いても
  外部APIの消費はごく少量で済む。

組み込み方（backend/main.py に2行追加するだけ）:
    import ts_api
    app.include_router(ts_api.router)

エンドポイント:
    GET /api/ts/health
    GET /api/ts/price?symbol=USDJPY
    GET /api/ts/klines?symbol=USDJPY&tf=15m&limit=300
        tf: 1m / 5m / 15m / 1h / 4h / 1d
"""
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
JST = timezone(timedelta(hours=9))
TD_KEY = os.environ.get("TWELVEDATA_API_KEY", "")

GMO_BASE = "https://forex-api.coin.z.com/public"
BINANCE_BASE = "https://api.binance.com/api/v3"
TD_BASE = "https://api.twelvedata.com"

# 内部シンボル → GMO為替シンボル（GMOが対応する主要ペア）
GMO_FX = {
    "USDJPY": "USD_JPY", "EURJPY": "EUR_JPY", "GBPJPY": "GBP_JPY",
    "AUDJPY": "AUD_JPY", "NZDJPY": "NZD_JPY", "CADJPY": "CAD_JPY",
    "CHFJPY": "CHF_JPY", "EURUSD": "EUR_USD", "GBPUSD": "GBP_USD",
    "AUDUSD": "AUD_USD",
}
# 内部シンボル → Binanceシンボル（金はPAXG=金連動トークンで代替）
BINANCE_MAP = {"XAUUSD": "PAXGUSDT"}

TF_GMO = {"1m": "1min", "5m": "5min", "15m": "15min",
          "1h": "1hour", "4h": "4hour", "1d": "1day"}
TF_TD = {"1m": "1min", "5m": "5min", "15m": "15min",
         "1h": "1h", "4h": "4h", "1d": "1day"}
# 当日/最新データのキャッシュ保持秒数
TTL_GMO = {"1m": 45, "5m": 120, "15m": 240, "1h": 600, "4h": 1800, "1d": 3600}
TTL_TD = {"1m": 120, "5m": 240, "15m": 480, "1h": 1200, "4h": 3600, "1d": 7200}

# ---------------- キャッシュ（メモリ） ----------------
_cache: dict = {}


def cget(key):
    v = _cache.get(key)
    if not v:
        return None
    exp, data = v
    if exp is not None and time.time() > exp:
        _cache.pop(key, None)
        return None
    return data


def cset(key, data, ttl=None):
    # ttl=None は「変化しない過去データ」なので無期限保持
    _cache[key] = (None if ttl is None else time.time() + ttl, data)
    # メモリ保護: 2000件超えたら古い期限付きから捨てる
    if len(_cache) > 2000:
        for k in list(_cache.keys())[:500]:
            _cache.pop(k, None)


# ---------------- Twelve Data 1日分の消費上限（無料枠800/日を保護） ----------------
_td_budget = {"date": "", "count": 0}
TD_DAILY_LIMIT = 700


def td_spend() -> bool:
    today = datetime.now(JST).strftime("%Y%m%d")
    if _td_budget["date"] != today:
        _td_budget["date"] = today
        _td_budget["count"] = 0
    if _td_budget["count"] >= TD_DAILY_LIMIT:
        return False
    _td_budget["count"] += 1
    return True


def ok(data, status=200):
    return JSONResponse(
        data,
        status_code=status,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Cache-Control": "no-store",
        },
    )


async def _get(url, params=None):
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def _gmo_get_data(params):
    """GMO klines取得。404はその日付のデータ未生成（深夜・休日）を意味するので空扱い。"""
    try:
        j = await _get(f"{GMO_BASE}/v1/klines", params)
        return j.get("data") or []
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return []
        raise


# ---------------- GMO 為替 ----------------
async def gmo_klines(gsym: str, tf: str, limit: int):
    iv = TF_GMO[tf]
    if tf in ("4h", "1d"):
        # 年単位で取得。今年＋去年で十分な本数を確保
        year = datetime.now(JST).year
        rows = []
        for y in (year - 1, year):
            key = f"gmo|{gsym}|{iv}|{y}"
            data = cget(key)
            if data is None:
                data = await _gmo_get_data({"symbol": gsym, "priceType": "BID",
                                            "interval": iv, "date": str(y)})
                cset(key, data, TTL_GMO[tf] if y == year else None)
            rows += data
    else:
        # 日単位で当日から過去へ遡る（土日は空なので自動スキップ）
        rows = []
        chunks = []
        d = datetime.now(JST)
        total = 0
        for i in range(14):
            ds = d.strftime("%Y%m%d")
            key = f"gmo|{gsym}|{iv}|{ds}"
            data = cget(key)
            if data is None:
                data = await _gmo_get_data({"symbol": gsym, "priceType": "BID",
                                            "interval": iv, "date": ds})
                # 当日と直近日は短期キャッシュ、それ以前の確定データは無期限
                cset(key, data, TTL_GMO[tf] if i <= 1 else None)
            chunks.append(data)
            total += len(data)
            d -= timedelta(days=1)
            if total >= limit + 5:
                break
        for data in reversed(chunks):
            rows += data
    candles = [
        {
            "time": int(int(x["openTime"]) / 1000),
            "open": float(x["open"]), "high": float(x["high"]),
            "low": float(x["low"]), "close": float(x["close"]),
            "volume": 0,
        }
        for x in rows
    ]
    candles.sort(key=lambda c: c["time"])
    return candles[-limit:]


async def gmo_price(gsym: str):
    key = "gmo|ticker"
    data = cget(key)
    if data is None:
        j = await _get(f"{GMO_BASE}/v1/ticker")
        data = j.get("data") or []
        cset(key, data, 2)  # 全銘柄一括なので2秒キャッシュで十分リアルタイム
    for row in data:
        if row.get("symbol") == gsym:
            bid = float(row.get("bid", 0) or 0)
            ask = float(row.get("ask", 0) or 0)
            price = (bid + ask) / 2 if bid and ask else (bid or ask)
            return price, row.get("status", "")
    raise ValueError(f"GMO ticker: {gsym} not found")


# ---------------- Binance（金PAXG・予備の仮想通貨中継） ----------------
async def binance_klines(bsym: str, tf: str, limit: int):
    key = f"bn|{bsym}|{tf}"
    data = cget(key)
    if data is None:
        j = await _get(f"{BINANCE_BASE}/klines",
                       {"symbol": bsym, "interval": tf, "limit": limit})
        data = [
            {"time": int(k[0] / 1000), "open": float(k[1]),
             "high": float(k[2]), "low": float(k[3]),
             "close": float(k[4]), "volume": float(k[5])}
            for k in j
        ]
        cset(key, data, TTL_GMO[tf])
    return data[-limit:]


async def binance_price(bsym: str):
    key = f"bn|price|{bsym}"
    p = cget(key)
    if p is None:
        j = await _get(f"{BINANCE_BASE}/ticker/price", {"symbol": bsym})
        p = float(j["price"])
        cset(key, p, 2)
    return p


# ---------------- Twelve Data（その他銘柄の予備） ----------------
def td_symbol(internal: str) -> str:
    s = internal.upper()
    return f"{s[:3]}/{s[3:]}" if len(s) == 6 else s


async def td_klines(internal: str, tf: str, limit: int):
    if not TD_KEY:
        raise ValueError("この銘柄は未対応です（サーバーにTwelve Dataキーなし）")
    key = f"td|{internal}|{tf}"
    data = cget(key)
    if data is None:
        if not td_spend():
            raise ValueError("Twelve Dataの1日の利用枠を使い切りました")
        j = await _get(f"{TD_BASE}/time_series",
                       {"symbol": td_symbol(internal), "interval": TF_TD[tf],
                        "outputsize": limit, "apikey": TD_KEY})
        vals = j.get("values")
        if not vals:
            raise ValueError(f"TwelveData: {j.get('message', 'no data')}")
        data = [
            {"time": int(datetime.fromisoformat(
                v["datetime"].replace(" ", "T")).replace(
                tzinfo=timezone.utc).timestamp()),
             "open": float(v["open"]), "high": float(v["high"]),
             "low": float(v["low"]), "close": float(v["close"]),
             "volume": float(v.get("volume") or 0)}
            for v in vals
        ]
        data.sort(key=lambda c: c["time"])
        cset(key, data, TTL_TD[tf])
    return data[-limit:]


async def td_price(internal: str):
    if not TD_KEY:
        raise ValueError("この銘柄は未対応です（サーバーにTwelve Dataキーなし）")
    key = f"td|price|{internal}"
    p = cget(key)
    if p is None:
        if not td_spend():
            raise ValueError("Twelve Dataの1日の利用枠を使い切りました")
        j = await _get(f"{TD_BASE}/price",
                       {"symbol": td_symbol(internal), "apikey": TD_KEY})
        if "price" not in j:
            raise ValueError(f"TwelveData: {j.get('message', 'no price')}")
        p = float(j["price"])
        cset(key, p, 30)
    return p


# ---------------- ルート ----------------
@router.get("/app")
async def ts_app():
    """TradeScope本体を配信（同一オリジンなのでCORS問題が発生しない）。"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "static" / "tradescope.html"
    if not p.exists():
        return ok({"error": "tradescope.htmlが未配置です"}, 404)
    return FileResponse(p, media_type="text/html")


@router.options("/api/ts/{rest:path}")
async def ts_options(rest: str):
    return ok({})


@router.get("/api/ts/watch")
async def ts_watch_status():
    """24時間監視の状態確認。"""
    try:
        import ts_watch
        return ok({"watching": ts_watch.STATE["started"],
                   "boot_time": ts_watch.STATE.get("boot_time"),
                   "heartbeat": ts_watch.STATE.get("heartbeat"),
                   "symbols": [w[0] for w in ts_watch.WATCH],
                   "last_run": ts_watch.STATE["last_run"],
                   "sent_today": ts_watch.STATE["sent_today"],
                   "results": ts_watch.STATE["results"],
                   "errors": ts_watch.STATE["errors"]})
    except Exception as e:  # noqa: BLE001
        return ok({"watching": False, "error": str(e)}, 502)


@router.get("/api/ts/news")
async def ts_news_api(symbol: str = ""):
    """経済指標: 今後2時間の予定と直近90分の結果（銘柄指定で絞り込み）。"""
    try:
        import ts_news
        events = await ts_news.fetch_events()
        curs = ts_news.currencies_of(symbol) if symbol else             ["USD", "JPY", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF"]
        up = [{"title": e["title"], "cur": e["cur"], "in_min": e["in_min"],
               "impact": e["impact"], "forecast": e["forecast"]}
              for e in ts_news.upcoming(events, curs, within_min=120,
                                        min_impact="Medium")][:8]
        rc = [{"title": e["title"], "cur": e["cur"], "ago_min": e["ago_min"],
               "actual": e["actual"], "forecast": e["forecast"],
               "bias": e["bias"], "bias_text": e["bias_text"]}
              for e in ts_news.recent_results(events, curs, since_min=120,
                                              min_impact="Medium")][:8]
        return ok({"upcoming": up, "recent": rc})
    except Exception as e:  # noqa: BLE001
        return ok({"error": str(e)}, 502)


@router.get("/api/ts/stats")
async def ts_stats():
    """シグナル自動採点の集計（判定別・銘柄別の勝率）。"""
    try:
        import ts_watch
        return ok(ts_watch.stats_summary())
    except Exception as e:  # noqa: BLE001
        return ok({"error": str(e)}, 502)


@router.get("/app/icon.png")
async def ts_icon():
    from pathlib import Path
    from fastapi.responses import FileResponse
    p = Path(__file__).parent / "static" / "ts-icon.png"
    if not p.exists():
        return ok({"error": "icon未配置"}, 404)
    return FileResponse(p, media_type="image/png")


@router.get("/api/ts/health")
async def ts_health():
    return ok({
        "ok": True,
        "gmo_pairs": sorted(GMO_FX.keys()),
        "gold_via": "PAXGUSDT (Binance)",
        "twelvedata_key": bool(TD_KEY),
        "td_used_today": _td_budget["count"],
    })


@router.get("/api/ts/price")
async def ts_price(symbol: str = ""):
    sym = symbol.strip().upper()
    try:
        if sym in GMO_FX:
            price, status = await gmo_price(GMO_FX[sym])
            return ok({"symbol": sym, "price": price,
                       "market": status, "source": "gmo"})
        if sym in BINANCE_MAP:
            price = await binance_price(BINANCE_MAP[sym])
            return ok({"symbol": sym, "price": price,
                       "source": "binance-paxg"})
        if sym.endswith("USDT"):
            price = await binance_price(sym)
            return ok({"symbol": sym, "price": price, "source": "binance"})
        price = await td_price(sym)
        return ok({"symbol": sym, "price": price, "source": "twelvedata"})
    except Exception as e:  # noqa: BLE001
        return ok({"error": str(e), "symbol": sym}, status=502)


@router.get("/api/ts/klines")
async def ts_klines(symbol: str = "", tf: str = "15m", limit: int = 300):
    sym = symbol.strip().upper()
    tf = tf.strip()
    limit = max(10, min(int(limit or 300), 1000))
    if tf not in TF_GMO:
        return ok({"error": f"tfは {'/'.join(TF_GMO)} のいずれかです"}, 400)
    try:
        if sym in GMO_FX:
            candles = await gmo_klines(GMO_FX[sym], tf, limit)
            src = "gmo"
        elif sym in BINANCE_MAP:
            candles = await binance_klines(BINANCE_MAP[sym], tf, limit)
            src = "binance-paxg"
        elif sym.endswith("USDT"):
            candles = await binance_klines(sym, tf, limit)
            src = "binance"
        else:
            candles = await td_klines(sym, tf, limit)
            src = "twelvedata"
        if not candles:
            return ok({"error": "データが空でした（市場休場の可能性）",
                       "symbol": sym}, 502)
        return ok({"symbol": sym, "tf": tf, "source": src,
                   "candles": candles})
    except Exception as e:  # noqa: BLE001
        return ok({"error": str(e), "symbol": sym}, status=502)


# ---------------- LINE通知（signal-deskのnotifierを再利用） ----------------
from pydantic import BaseModel


class NotifyIn(BaseModel):
    title: str = ""
    body: str = ""


_notify_hist: list = []


@router.post("/api/ts/notify")
async def ts_notify(n: NotifyIn):
    """TradeScopeのアラームをLINEに転送する。
    乱用防止のため 1分5件・1日200件 まで。"""
    now = time.time()
    _notify_hist[:] = [t for t in _notify_hist if now - t < 86400]
    recent = [t for t in _notify_hist if now - t < 60]
    if len(recent) >= 5:
        return ok({"sent": False, "error": "1分あたりの通知上限（5件）"}, 429)
    if len(_notify_hist) >= 200:
        return ok({"sent": False, "error": "1日あたりの通知上限（200件）"}, 429)
    _notify_hist.append(now)
    try:
        import notifier
        text = (f"【TradeScope】{n.title}\n{n.body}")[:900]
        await notifier.send_line(text)
        return ok({"sent": True})
    except Exception as e:  # noqa: BLE001
        return ok({"sent": False, "error": str(e)}, 502)
