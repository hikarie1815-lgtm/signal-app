"""データ取得:
- 仮想通貨: Binance公開API(キー不要)。WebSocketで秒単位の価格、1分足を常時更新。
- FX/金属: Twelve Data REST。無料枠は8リクエスト/分 → 銘柄をローテーションして更新。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx
import pandas as pd
import websockets

import config

log = logging.getLogger("fetcher")

BINANCE_REST = "https://api.binance.com/api/v3/klines"
BINANCE_WS = "wss://stream.binance.com:9443/stream"
TD_URL = "https://api.twelvedata.com/time_series"
TD_WS = "wss://ws.twelvedata.com/v1/quotes/price"


class DataStore:
    """銘柄ごとの1分足とリアルタイム価格をメモリ保持。"""

    def __init__(self):
        self.candles: dict[str, pd.DataFrame] = {}
        self.prices: dict[str, float] = {}
        self.last_update: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    def set_df(self, symbol: str, df: pd.DataFrame):
        self.candles[symbol] = df.tail(2000)
        if len(df):
            self.prices[symbol] = float(df["close"].iloc[-1])
        self.last_update[symbol] = datetime.now().isoformat(timespec="seconds")
        self.errors.pop(symbol, None)

    def update_candle(self, symbol: str, ts: pd.Timestamp, o, h, l, c, v):
        df = self.candles.get(symbol)
        row = pd.DataFrame(
            {"open": [o], "high": [h], "low": [l], "close": [c], "volume": [v]},
            index=[ts],
        )
        if df is None:
            self.candles[symbol] = row
        else:
            if ts in df.index:
                df.loc[ts, ["open", "high", "low", "close", "volume"]] = [o, h, l, c, v]
            else:
                self.candles[symbol] = pd.concat([df, row]).tail(2000)
        self.prices[symbol] = float(c)
        self.last_update[symbol] = datetime.now().isoformat(timespec="seconds")

    def set_price(self, symbol: str, price: float):
        self.prices[symbol] = float(price)
        self.last_update[symbol] = datetime.now().isoformat(timespec="seconds")

    def apply_tick(self, symbol: str, price: float):
        """秒単位ティックで価格と最新足(close/high/low)を更新。"""
        price = float(price)
        self.prices[symbol] = price
        self.last_update[symbol] = datetime.now().isoformat(timespec="seconds")
        df = self.candles.get(symbol)
        if df is not None and len(df):
            i = df.index[-1]
            df.loc[i, "close"] = price
            if price > df.at[i, "high"]:
                df.loc[i, "high"] = price
            if price < df.at[i, "low"]:
                df.loc[i, "low"] = price

    def get_df(self, symbol: str):
        return self.candles.get(symbol)

    def usdjpy(self) -> float:
        return self.prices.get("USDJPY", config.FALLBACK_USDJPY)


store = DataStore()


# ============ Binance(仮想通貨) ============

async def binance_load_history():
    syms = [(s, m["api"]) for s, m in config.SYMBOLS.items() if m["source"] == "binance"]
    async with httpx.AsyncClient(timeout=20) as client:
        for sym, api in syms:
            try:
                r = await client.get(BINANCE_REST, params={"symbol": api, "interval": "1m", "limit": 1000})
                r.raise_for_status()
                rows = r.json()
                df = pd.DataFrame(
                    [{"ts": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                      "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])} for x in rows]
                )
                df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True).dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
                store.set_df(sym, df)
                log.info("Binance履歴取得: %s %d本", sym, len(df))
            except Exception as e:
                store.errors[sym] = f"履歴取得失敗: {e}"
                log.warning("Binance履歴失敗 %s: %s", sym, e)


async def binance_ws_loop():
    """kline_1m(足の更新)+ miniTicker(秒単位価格)を購読。自動再接続。"""
    syms = {m["api"].lower(): s for s, m in config.SYMBOLS.items() if m["source"] == "binance"}
    if not syms:
        return
    streams = "/".join(f"{a}@kline_1m" for a in syms) + "/" + "/".join(f"{a}@miniTicker" for a in syms)
    url = f"{BINANCE_WS}?streams={streams}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                log.info("Binance WebSocket接続")
                async for msg in ws:
                    data = json.loads(msg).get("data", {})
                    ev = data.get("e")
                    if ev == "kline":
                        k = data["k"]
                        sym = syms.get(k["s"].lower())
                        if not sym:
                            continue
                        ts = pd.to_datetime(int(k["t"]), unit="ms", utc=True).tz_convert("Asia/Tokyo").tz_localize(None)
                        store.update_candle(sym, ts, float(k["o"]), float(k["h"]),
                                            float(k["l"]), float(k["c"]), float(k["v"]))
                    elif ev == "24hrMiniTicker":
                        sym = syms.get(data["s"].lower())
                        if sym:
                            store.set_price(sym, float(data["c"]))
        except Exception as e:
            log.warning("Binance WS切断: %s → 5秒後に再接続", e)
            await asyncio.sleep(5)


# ============ Twelve Data(FX・金属・指数) ============

async def twelvedata_poll_loop():
    syms = [(s, m["api"]) for s, m in config.SYMBOLS.items() if m["source"] == "twelvedata"]
    if not syms:
        return
    if not config.TWELVEDATA_API_KEY:
        for s, _ in syms:
            store.errors[s] = "TWELVEDATA_API_KEY未設定(.envを確認)"
        log.warning("Twelve Data APIキー未設定 → FX/金属はスキップ")
        return
    idx = 0
    async with httpx.AsyncClient(timeout=20) as client:
        while True:
            sym, api = syms[idx % len(syms)]
            idx += 1
            try:
                r = await client.get(TD_URL, params={
                    "symbol": api, "interval": "1min", "outputsize": 1500,
                    "timezone": "Asia/Tokyo", "apikey": config.TWELVEDATA_API_KEY,
                })
                j = r.json()
                if j.get("status") == "error" or "values" not in j:
                    store.errors[sym] = j.get("message", "取得エラー")[:120]
                else:
                    vals = j["values"]
                    df = pd.DataFrame([{
                        "ts": v["datetime"], "open": float(v["open"]), "high": float(v["high"]),
                        "low": float(v["low"]), "close": float(v["close"]),
                        "volume": float(v.get("volume") or 0),
                    } for v in vals])
                    df.index = pd.to_datetime(df.pop("ts"))
                    df = df.sort_index()
                    store.set_df(sym, df)
            except Exception as e:
                store.errors[sym] = f"通信エラー: {e}"
            await asyncio.sleep(config.TD_POLL_INTERVAL)


async def twelvedata_ws_loop():
    """Twelve Data WebSocket: FX・金銀の価格を秒単位で受信(無料枠: 8銘柄/1接続)。
    切断時は自動再接続。エラー時はREST更新だけで動き続ける。"""
    syms = {m["api"]: s for s, m in config.SYMBOLS.items() if m["source"] == "twelvedata"}
    if not syms or not config.TWELVEDATA_API_KEY:
        return
    sub = list(syms.keys())[:8]  # 無料枠上限の8銘柄
    url = f"{TD_WS}?apikey={config.TWELVEDATA_API_KEY}"
    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                await ws.send(json.dumps({"action": "subscribe",
                                          "params": {"symbols": ",".join(sub)}}))
                log.info("Twelve Data WebSocket接続(%d銘柄・秒単位)", len(sub))
                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    except asyncio.TimeoutError:
                        await ws.send(json.dumps({"action": "heartbeat"}))
                        continue
                    d = json.loads(msg)
                    ev = d.get("event")
                    if ev == "price" and d.get("symbol") in syms and d.get("price") is not None:
                        store.apply_tick(syms[d["symbol"]], float(d["price"]))
                    elif ev == "subscribe-status":
                        fails = d.get("fails") or []
                        if fails:
                            log.warning("TD WS購読失敗: %s", fails)
        except Exception as e:
            log.warning("Twelve Data WS切断: %s → 15秒後に再接続", e)
            await asyncio.sleep(15)
