"""リスク管理: 1回の損失を資金の1%以内に抑えるロット自動計算。"""
import config


def risk_jpy() -> float:
    return config.CAPITAL_JPY * config.RISK_PERCENT / 100.0


def calc_position(symbol: str, price: float, sl: float, usdjpy: float) -> dict:
    """損切り幅から推奨数量を計算。
    FX: ロット(1ロット=10万通貨) / 仮想通貨・金属: 数量"""
    meta = config.SYMBOLS[symbol]
    sl_dist = abs(price - sl)
    if sl_dist <= 0:
        return {"lots": 0, "qty": 0, "risk_jpy": risk_jpy(), "sl_pips": 0}

    quote_to_jpy = 1.0 if meta.get("jpy_quote") else usdjpy  # USD建て→円換算
    rj = risk_jpy()

    if meta["type"] == "fx":
        units = rj / (sl_dist * quote_to_jpy)        # 許容損失 ÷ 1通貨あたり損失
        lots = units / 100000.0
        return {
            "lots": round(lots, 2),
            "qty": int(units),
            "risk_jpy": rj,
            "sl_pips": round(sl_dist / meta["pip"], 1),
        }
    # 仮想通貨・金属・指数: 数量ベース
    qty = rj / (sl_dist * quote_to_jpy)
    return {
        "lots": round(qty, 4),
        "qty": round(qty, 4),
        "risk_jpy": rj,
        "sl_pips": round(sl_dist / meta["pip"], 1),
    }
