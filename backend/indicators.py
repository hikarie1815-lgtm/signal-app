"""テクニカル指標。すべて過去データのみで計算(未来参照なし)。"""
import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    ru = up.ewm(alpha=1 / n, adjust=False).mean()
    rd = dn.ewm(alpha=1 / n, adjust=False).mean()
    rs = ru / rd.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def macd(close: pd.Series, fast=12, slow=26, sig=9):
    line = ema(close, fast) - ema(close, slow)
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14):
    h, l = df["high"], df["low"]
    up = h.diff()
    dn = -l.diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    atr_ = true_range(df).ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    pdi = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    mdi = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    dx = ((pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)) * 100
    adx_ = dx.ewm(alpha=1 / n, adjust=False).mean()
    return adx_.fillna(0.0), pdi.fillna(0.0), mdi.fillna(0.0)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    return mid, mid + k * sd, mid - k * sd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrameに全指標カラムを追加して返す。"""
    out = df.copy()
    c = out["close"]
    out["ema9"] = ema(c, 9)
    out["ema21"] = ema(c, 21)
    out["ema50"] = ema(c, 50)
    out["ema200"] = ema(c, 200)
    out["rsi"] = rsi(c, 14)
    out["macd"], out["macd_sig"], out["macd_hist"] = macd(c)
    out["atr"] = atr(out, 14)
    out["adx"], out["pdi"], out["mdi"] = adx(out, 14)
    out["bb_mid"], out["bb_up"], out["bb_low"] = bollinger(c, 20, 2.0)
    out["vol_ma"] = out["volume"].rolling(20).mean()
    # サポレジ: 直近50本の高値/安値(当該バーを含まない → shift(1)で未来参照防止)
    out["resistance"] = out["high"].rolling(50).max().shift(1)
    out["support"] = out["low"].rolling(50).min().shift(1)
    # 直近20本の高値/安値ブレイク判定用
    out["hh20"] = out["high"].rolling(20).max().shift(1)
    out["ll20"] = out["low"].rolling(20).min().shift(1)
    out["atr_ma"] = out["atr"].rolling(50).mean()
    out["bb_width"] = (out["bb_up"] - out["bb_low"]) / out["bb_mid"].replace(0, np.nan)
    out["bb_width_med"] = out["bb_width"].rolling(50).median()
    return out


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """1分/5分足から上位足を生成。"""
    o = df.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return o.dropna(subset=["close"])


def htf_trend_series(df_main: pd.DataFrame, rule: str) -> pd.Series:
    """上位足トレンド(+1/-1/0)をメイン足に展開。
    確定済み上位足のみ使用するため shift(1)(未来参照防止)。"""
    h = resample_ohlcv(df_main, rule)
    if len(h) < 25:
        return pd.Series(0, index=df_main.index, dtype=float)
    t = np.sign(ema(h["close"], 9) - ema(h["close"], 21))
    t = t.shift(1)  # 確定足のみ
    return t.reindex(df_main.index, method="ffill").fillna(0.0)
