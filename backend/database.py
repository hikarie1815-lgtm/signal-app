"""SQLite保存: シグナル履歴・バックテスト統計・トレード記録(損失管理用)。"""
import json
import sqlite3
from datetime import date, datetime

import config


def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS signal_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, time TEXT, score REAL, signal TEXT,
            price REAL, sl REAL, tp REAL
        );
        CREATE TABLE IF NOT EXISTS stats(
            symbol TEXT PRIMARY KEY, data TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS journal(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT, symbol TEXT, direction TEXT, pnl_jpy REAL
        );
        """)


def add_signal(symbol, score, signal, price, sl, tp):
    with conn() as c:
        c.execute(
            "INSERT INTO signal_history(symbol,time,score,signal,price,sl,tp) VALUES(?,?,?,?,?,?,?)",
            (symbol, datetime.now().isoformat(timespec="seconds"), score, signal, price, sl, tp),
        )


def last_signal(symbol):
    with conn() as c:
        r = c.execute(
            "SELECT signal FROM signal_history WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return r["signal"] if r else None


def signal_history(symbol, limit=50):
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM signal_history WHERE symbol=? ORDER BY id DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def save_stats(symbol, stats: dict):
    with conn() as c:
        c.execute(
            "INSERT INTO stats(symbol,data,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (symbol, json.dumps(stats, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )


def load_stats(symbol):
    with conn() as c:
        r = c.execute("SELECT data FROM stats WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(r["data"]) if r else None


def add_trade(symbol, direction, pnl_jpy):
    with conn() as c:
        c.execute(
            "INSERT INTO journal(time,symbol,direction,pnl_jpy) VALUES(?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), symbol, direction, pnl_jpy),
        )


def journal_status():
    """本日の合計損益と連敗数。"""
    today = date.today().isoformat()
    with conn() as c:
        rows = c.execute(
            "SELECT pnl_jpy FROM journal WHERE time >= ? ORDER BY id ASC", (today,)
        ).fetchall()
    pnls = [r["pnl_jpy"] for r in rows]
    consec = 0
    for p in reversed(pnls):
        if p < 0:
            consec += 1
        else:
            break
    total = sum(pnls)
    return {
        "today_pnl": round(total),
        "trades_today": len(pnls),
        "consec_losses": consec,
        "daily_loss_hit": total <= -config.DAILY_MAX_LOSS_JPY,
        "consec_warning": consec >= config.MAX_CONSEC_LOSSES,
        "daily_max_loss": config.DAILY_MAX_LOSS_JPY,
    }


def journal_list(limit=100):
    with conn() as c:
        rows = c.execute("SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
