"""シグナルアプリ メインサーバー。
起動: python main.py  → http://localhost:8000 をスマホ/PCで開く"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import backtest as bt
import config
import database as db
import notifier
import risk
import signal_engine as engine
from data_fetcher import (store, binance_load_history, binance_ws_loop,
                          twelvedata_poll_loop, twelvedata_ws_loop)
from indicators import resample_ohlcv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("main")

STATE = {"snapshot": {}, "journal": {}, "stats": {}}
CLIENTS: set[WebSocket] = set()


# ============ バックグラウンドループ ============

async def analysis_loop():
    """全銘柄のシグナルを定期計算。"""
    await asyncio.sleep(5)
    while True:
        journal = db.journal_status()
        STATE["journal"] = journal
        snap = {}
        for sym in config.SYMBOLS:
            df = store.get_df(sym)
            if df is None or len(df) < 200:
                snap[sym] = {"symbol": sym, "ready": False,
                             "name": config.SYMBOLS[sym]["name"],
                             "error": store.errors.get(sym, "データ取得中…")}
                continue
            try:
                res = engine.analyze(sym, df, store.prices.get(sym))
                if res.get("ready"):
                    res["position"] = risk.calc_position(sym, res["price"], res["sl"], store.usdjpy())
                    res["last_update"] = store.last_update.get(sym, "")
                    stats = STATE["stats"].get(sym) or db.load_stats(sym)
                    if stats:
                        STATE["stats"][sym] = stats
                        res["stats"] = stats.get("stats")
                        res["stats_buy"] = stats.get("stats_buy")
                        res["stats_sell"] = stats.get("stats_sell")
                    # シグナル変化時のみ履歴保存+通知判定
                    if db.last_signal(sym) != res["signal"]:
                        db.add_signal(sym, res["score"], res["signal"], res["price"], res["sl"], res["tp"])
                        await notifier.check_and_notify(res, stats, journal)
                snap[sym] = res
            except Exception as e:
                log.exception("分析エラー %s", sym)
                snap[sym] = {"symbol": sym, "ready": False,
                             "name": config.SYMBOLS[sym]["name"], "error": str(e)[:120]}
        STATE["snapshot"] = snap
        await asyncio.sleep(config.ANALYZE_INTERVAL)


async def broadcast_loop():
    """秒単位で価格+スナップショットを全クライアントに配信。"""
    while True:
        if CLIENTS:
            msg = {
                "type": "snapshot",
                "prices": store.prices,
                "data": STATE["snapshot"],
                "journal": STATE["journal"],
                "alerts": notifier.pop_browser_alerts(),
                "capital": config.CAPITAL_JPY,
            }
            dead = []
            for ws in CLIENTS:
                try:
                    await ws.send_json(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                CLIENTS.discard(ws)
        await asyncio.sleep(config.BROADCAST_INTERVAL)


async def stats_loop():
    """起動時+1時間ごとに簡易バックテストで勝率/PF/期待値を更新。"""
    await asyncio.sleep(20)
    while True:
        for sym in config.SYMBOLS:
            df = store.get_df(sym)
            if df is None or len(df) < 600:
                continue
            try:
                res = await asyncio.to_thread(bt.run_backtest, sym, df)
                if res.get("ok"):
                    cache = {"stats": res["stats"], "stats_buy": res["stats_buy"],
                             "stats_sell": res["stats_sell"], "period": res["period"]}
                    STATE["stats"][sym] = cache
                    db.save_stats(sym, cache)
            except Exception:
                log.exception("統計更新エラー %s", sym)
            await asyncio.sleep(1)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    asyncio.create_task(binance_load_history())
    asyncio.create_task(binance_ws_loop())
    asyncio.create_task(twelvedata_poll_loop())
    asyncio.create_task(twelvedata_ws_loop())
    asyncio.create_task(analysis_loop())
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(stats_loop())
    import ts_watch
    asyncio.create_task(ts_watch.watch_loop())  # TradeScope 24時間監視
    log.info("起動完了 → http://localhost:8000")
    yield


app = FastAPI(title="シグナルダッシュボード", lifespan=lifespan)

# TradeScope用データ配信API（GMOコイン為替・PAXG金価格の中継）
import ts_api
app.include_router(ts_api.router)
STATIC = Path(__file__).parent / "static"


# ============ WebSocket ============

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    CLIENTS.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        CLIENTS.discard(ws)


# ============ REST API ============

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/snapshot")
async def snapshot():
    return {"data": STATE["snapshot"], "prices": store.prices,
            "journal": STATE["journal"], "capital": config.CAPITAL_JPY}


@app.get("/api/symbol/{symbol}")
async def symbol_detail(symbol: str):
    if symbol not in config.SYMBOLS:
        return JSONResponse({"error": "未対応の銘柄"}, status_code=404)
    df = store.get_df(symbol)
    candles = []
    if df is not None and len(df):
        d5 = resample_ohlcv(df, config.MAIN_TF).tail(200)
        candles = [{"time": int(pd.Timestamp(t).timestamp()), "open": r.open, "high": r.high,
                    "low": r.low, "close": r.close} for t, r in d5.iterrows()]
    return {
        "symbol": symbol,
        "analysis": STATE["snapshot"].get(symbol, {}),
        "candles": candles,
        "history": db.signal_history(symbol, 50),
        "stats": STATE["stats"].get(symbol) or db.load_stats(symbol),
    }


@app.post("/api/backtest/{symbol}")
async def run_backtest_api(symbol: str, tf: str = "5min"):
    if symbol not in config.SYMBOLS:
        return JSONResponse({"error": "未対応の銘柄"}, status_code=404)
    if tf not in ("1min", "5min", "15min", "1h"):
        return JSONResponse({"error": "tfは 1min/5min/15min/1h"}, status_code=400)
    df = store.get_df(symbol)
    if df is None or len(df) < 300:
        return JSONResponse({"error": "データがまだ足りません(数分後に再実行)"}, status_code=400)
    res = await asyncio.to_thread(bt.run_backtest, symbol, df, tf)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)
    csv_path = bt.save_csv(symbol, res)
    res["csv"] = Path(csv_path).name
    res["trades"] = res["trades"][-100:]  # 直近100件のみ返す
    return res


@app.get("/api/backtest/csv/{filename}")
async def download_csv(filename: str):
    path = config.BACKTEST_DIR / Path(filename).name
    if not path.exists():
        return JSONResponse({"error": "ファイルが見つかりません"}, status_code=404)
    return FileResponse(path, media_type="text/csv", filename=path.name)


class TradeIn(BaseModel):
    symbol: str
    direction: str
    pnl_jpy: float


@app.post("/api/journal")
async def add_journal(t: TradeIn):
    db.add_trade(t.symbol, t.direction, t.pnl_jpy)
    return db.journal_status()


@app.get("/api/journal")
async def get_journal():
    return {"status": db.journal_status(), "trades": db.journal_list(50)}


if __name__ == "__main__":
    import os
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
