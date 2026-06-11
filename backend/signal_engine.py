"""AIスコア(0〜100)とシグナル判定。ライブ分析とバックテストで同じロジックを共有。"""
import numpy as np
import pandas as pd

import config
from indicators import add_indicators, resample_ohlcv, htf_trend_series


def label_of(score: float) -> str:
    if score >= config.TH_STRONG_BUY:
        return "STRONG BUY"
    if score >= config.TH_BUY:
        return "BUY"
    if score <= config.TH_STRONG_SELL:
        return "STRONG SELL"
    if score <= config.TH_SELL:
        return "SELL"
    return "WAIT"


def score_at(df: pd.DataFrame, i: int, t15: float, t1h: float):
    """指標付きDataFrameのi行目時点のスコアを計算。
    戻り値: (score, reasons, avoid_reasons, parts)
    すべて i 行目以前の値のみ使用(未来参照なし)。"""
    r = df.iloc[i]
    rp = df.iloc[i - 1] if i > 0 else r
    reasons, avoid = [], []
    total = 0.0
    parts = {}

    # --- EMA方向 (±20) ---
    pts = 0.0
    pts += 8 if r.ema9 > r.ema21 else -8
    pts += 6 if r.ema21 > r.ema50 else -6
    pts += 6 if r.close > r.ema200 else -6
    parts["EMA"] = pts
    total += pts
    if pts >= 14:
        reasons.append("EMAパーフェクトオーダー(上昇)")
    elif pts <= -14:
        reasons.append("EMAパーフェクトオーダー(下降)")

    # --- RSI (±10) ---
    pts = float(np.clip((r.rsi - 50) * 0.6, -10, 10))
    if r.rsi > 78:
        pts -= 5
        avoid.append(f"RSI買われすぎ({r.rsi:.0f})")
    elif r.rsi < 22:
        pts += 5
        avoid.append(f"RSI売られすぎ({r.rsi:.0f})")
    parts["RSI"] = pts
    total += pts

    # --- MACD (±15) ---
    pts = 8.0 if r.macd > r.macd_sig else -8.0
    pts += 7.0 if r.macd_hist > rp.macd_hist else -7.0
    parts["MACD"] = pts
    total += pts
    if pts >= 15:
        reasons.append("MACD強気(ヒストグラム拡大)")
    elif pts <= -15:
        reasons.append("MACD弱気(ヒストグラム拡大)")

    # --- ADX + DI (±10) トレンドの強さと方向 ---
    direction = 1.0 if r.pdi > r.mdi else -1.0
    pts = direction * min(10.0, r.adx / 4.0)
    parts["ADX"] = pts
    total += pts
    if r.adx >= 25:
        reasons.append(f"ADX {r.adx:.0f}: トレンド強い")

    # --- ボリンジャーバンド位置 (±10) ---
    band = r.bb_up - r.bb_mid
    pos = (r.close - r.bb_mid) / band if band and band > 0 else 0.0
    pts = float(np.clip(pos * 8, -10, 10))
    parts["BB"] = pts
    total += pts

    # --- 出来高 (±5) ---
    pts = 0.0
    if r.vol_ma and r.vol_ma > 0:
        ratio = r.volume / r.vol_ma
        body_dir = 1.0 if r.close >= r.open else -1.0
        pts = body_dir * float(np.clip((ratio - 1.0) * 5, 0, 5))
        if ratio >= 1.8:
            reasons.append(f"出来高急増(平均の{ratio:.1f}倍)")
    parts["出来高"] = pts
    total += pts

    # --- 上位足一致 (±15) ---
    pts = t15 * 7 + t1h * 8
    parts["上位足"] = pts
    total += pts
    if t15 > 0 and t1h > 0:
        reasons.append("15分足・1時間足とも上昇トレンド")
    elif t15 < 0 and t1h < 0:
        reasons.append("15分足・1時間足とも下降トレンド")

    # --- サポレジ位置 (±10) ---
    pts = 0.0
    if r.atr and r.atr > 0 and not np.isnan(r.support) and not np.isnan(r.resistance):
        dist_sup = (r.close - r.support) / r.atr
        dist_res = (r.resistance - r.close) / r.atr
        if r.close > r.resistance:
            pts += 4
            reasons.append("レジスタンス上抜け")
        elif dist_res < 1.5:
            pts -= 6
            avoid.append("レジスタンス直下(買い注意)")
        if r.close < r.support:
            pts -= 4
            reasons.append("サポート下抜け")
        elif dist_sup < 1.5:
            pts += 6
            avoid.append("サポート直上(売り注意)")
    parts["サポレジ"] = pts
    total += pts

    # --- 直近高値安値ブレイク (±5) ---
    pts = 0.0
    if not np.isnan(r.hh20) and r.close > r.hh20:
        pts = 5.0
        reasons.append("直近20本高値ブレイク")
    elif not np.isnan(r.ll20) and r.close < r.ll20:
        pts = -5.0
        reasons.append("直近20本安値ブレイク")
    parts["高値安値"] = pts
    total += pts

    score = 50 + total / 2.0

    # --- レンジ判定(ダマシ除外フィルター) ---
    is_range = False
    if r.adx < 18 and not np.isnan(r.bb_width_med) and r.bb_width < r.bb_width_med * 0.8:
        is_range = True
        score = 50 + (score - 50) * 0.4
        avoid.append("レンジ相場(ADX低・バンド収縮)→ シグナル抑制")

    # --- 高ボラ判定 ---
    if r.atr_ma and not np.isnan(r.atr_ma) and r.atr_ma > 0 and r.atr / r.atr_ma > 2.0:
        score = 50 + (score - 50) * 0.8
        avoid.append("高ボラティリティ警戒(ATR急拡大)")

    score = float(np.clip(round(score), 0, 100))
    return score, reasons, avoid, parts, is_range


def prepare(df_main: pd.DataFrame):
    """メイン足DataFrame(OHLCV)に指標+上位足トレンドを付与。"""
    d = add_indicators(df_main)
    t15 = htf_trend_series(df_main, "15min")
    t1h = htf_trend_series(df_main, "1h")
    return d, t15, t1h


def analyze(symbol: str, df_1m: pd.DataFrame, latest_price: float | None = None) -> dict:
    """1分足からメイン足(5分)を作りライブ分析。"""
    meta = config.SYMBOLS[symbol]
    df5 = resample_ohlcv(df_1m, config.MAIN_TF)
    if len(df5) < 60:
        return {"symbol": symbol, "ready": False, "name": meta["name"]}

    d, t15s, t1hs = prepare(df5)
    i = len(d) - 1
    t15, t1h = float(t15s.iloc[i]), float(t1hs.iloc[i])
    score, reasons, avoid, parts, is_range = score_at(d, i, t15, t1h)
    r = d.iloc[i]
    price = float(latest_price if latest_price else r.close)
    atr_v = float(r.atr) if r.atr and not np.isnan(r.atr) else price * 0.001

    sig = label_of(score)
    is_buy_side = score >= 50
    if is_buy_side:
        sl = price - 1.5 * atr_v
        tp = price + 3.0 * atr_v
    else:
        sl = price + 1.5 * atr_v
        tp = price - 3.0 * atr_v
    rr = abs(tp - price) / abs(price - sl) if price != sl else 0.0

    def trend_label(t):
        return "上昇" if t > 0 else "下降" if t < 0 else "中立"

    return {
        "symbol": symbol,
        "name": meta["name"],
        "type": meta["type"],
        "ready": True,
        "price": price,
        "score": score,
        "signal": sig,
        "direction": "買い" if score >= config.TH_BUY else "売り" if score <= config.TH_SELL else "様子見",
        "sl": float(sl),
        "tp": float(tp),
        "atr": atr_v,
        "rr": round(rr, 2),
        "reasons": reasons,
        "avoid_reasons": avoid,
        "parts": {k: float(round(float(v), 1)) for k, v in parts.items()},
        "htf": {"15m": trend_label(t15), "1h": trend_label(t1h)},
        "is_range": is_range,
        "rsi": round(float(r.rsi), 1),
        "adx": round(float(r.adx), 1),
        "time": d.index[i].isoformat(),
    }
