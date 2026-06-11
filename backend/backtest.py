"""バックテスト: シグナルエンジンと同一ロジックで過去検証。
未来データ参照禁止 → エントリーは判定の次バー始値、指標は当該バーまでのみ使用。"""
import csv
from datetime import datetime

import numpy as np
import pandas as pd

import config
from indicators import resample_ohlcv
from signal_engine import prepare, score_at, label_of

MAX_HOLD_BARS = 100  # 保有上限(バー数)


def run_backtest(symbol: str, df_1m: pd.DataFrame, tf: str = None) -> dict:
    tf = tf or config.MAIN_TF
    df = resample_ohlcv(df_1m, tf)
    if len(df) < 120:
        return {"ok": False, "error": "データ不足(120本以上必要)"}

    d, t15s, t1hs = prepare(df)
    n = len(d)
    trades = []
    pos = None  # {"dir":1/-1,"entry":..,"sl":..,"tp":..,"time":..,"bars":0}

    for i in range(60, n - 1):
        row = d.iloc[i]
        nxt = d.iloc[i + 1]
        score, _, _, _, _ = score_at(d, i, float(t15s.iloc[i]), float(t1hs.iloc[i]))
        sig = label_of(score)

        # --- 決済判定(次バーの高安で約定: SL優先=保守的) ---
        if pos is not None:
            pos["bars"] += 1
            exit_price, reason = None, None
            if pos["dir"] == 1:
                if nxt.low <= pos["sl"]:
                    exit_price, reason = pos["sl"], "損切り"
                elif nxt.high >= pos["tp"]:
                    exit_price, reason = pos["tp"], "利確"
                elif sig in ("SELL", "STRONG SELL"):
                    exit_price, reason = float(nxt.open), "逆シグナル"
            else:
                if nxt.high >= pos["sl"]:
                    exit_price, reason = pos["sl"], "損切り"
                elif nxt.low <= pos["tp"]:
                    exit_price, reason = pos["tp"], "利確"
                elif sig in ("BUY", "STRONG BUY"):
                    exit_price, reason = float(nxt.open), "逆シグナル"
            if exit_price is None and pos["bars"] >= MAX_HOLD_BARS:
                exit_price, reason = float(nxt.open), "時間切れ"
            if exit_price is not None:
                risk = abs(pos["entry"] - pos["sl"])
                pnl_r = pos["dir"] * (exit_price - pos["entry"]) / risk if risk > 0 else 0.0
                trades.append({
                    "entry_time": pos["time"],
                    "exit_time": str(d.index[i + 1]),
                    "dir": "BUY" if pos["dir"] == 1 else "SELL",
                    "entry": pos["entry"],
                    "exit": exit_price,
                    "sl": pos["sl"],
                    "tp": pos["tp"],
                    "pnl_r": round(pnl_r, 3),
                    "score": pos["score"],
                    "reason": reason,
                })
                pos = None

        # --- エントリー判定(次バー始値で約定) ---
        if pos is None:
            atr_v = float(row.atr) if row.atr and not np.isnan(row.atr) else 0.0
            if atr_v <= 0:
                continue
            entry = float(nxt.open)
            if sig in ("BUY", "STRONG BUY"):
                pos = {"dir": 1, "entry": entry, "sl": entry - 1.5 * atr_v,
                       "tp": entry + 3.0 * atr_v, "time": str(d.index[i + 1]),
                       "bars": 0, "score": score}
            elif sig in ("SELL", "STRONG SELL"):
                pos = {"dir": -1, "entry": entry, "sl": entry + 1.5 * atr_v,
                       "tp": entry - 3.0 * atr_v, "time": str(d.index[i + 1]),
                       "bars": 0, "score": score}

    return {"ok": True, "symbol": symbol, "tf": tf, "trades": trades,
            "stats": calc_stats(trades),
            "stats_buy": calc_stats([t for t in trades if t["dir"] == "BUY"]),
            "stats_sell": calc_stats([t for t in trades if t["dir"] == "SELL"]),
            "period": {"from": str(d.index[0]), "to": str(d.index[-1]), "bars": n}}


def calc_stats(trades: list) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "pf": 0.0, "ev_r": 0.0,
                "ev_jpy": 0.0, "max_dd_r": 0.0, "total_r": 0.0}
    rs = np.array([t["pnl_r"] for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    ev_r = rs.mean()
    eq = np.cumsum(rs)
    dd = eq - np.maximum.accumulate(eq)
    risk_jpy = config.CAPITAL_JPY * config.RISK_PERCENT / 100.0
    return {
        "trades": int(len(rs)),
        "win_rate": round(float(len(wins) / len(rs) * 100), 1),
        "pf": round(float(min(pf, 99.0)), 2),
        "ev_r": round(float(ev_r), 3),
        "ev_jpy": round(float(ev_r * risk_jpy)),
        "max_dd_r": round(float(-dd.min()), 2) if len(dd) else 0.0,
        "total_r": round(float(rs.sum()), 2),
    }


def save_csv(symbol: str, result: dict) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = config.BACKTEST_DIR / f"{symbol}_{result['tf']}_{ts}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["エントリー日時", "決済日時", "方向", "エントリー価格", "決済価格",
                    "損切り", "利確", "損益(R)", "スコア", "決済理由"])
        for t in result["trades"]:
            w.writerow([t["entry_time"], t["exit_time"], t["dir"], t["entry"],
                        t["exit"], t["sl"], t["tp"], t["pnl_r"], t["score"], t["reason"]])
    return str(path)
