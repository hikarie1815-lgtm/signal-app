"""
ts_watch.py — TradeScope 24時間監視エンジン（signal-desk常駐）

役割:
  サーバー上で数分おきに監視銘柄をマルチタイムフレーム分析し、
  条件を満たしたらLINEに通知する。ブラウザを閉じていても動く。

通知の種類とクールダウン:
  - エントリー候補（判定S/A）: 同一銘柄90分に1回
  - 全時間足の方向一致: 4時間に1回
  - 急変動 / だましブレイク: 1時間に1回
  1日の合計上限80通。FX・金は土日スキップ（仮想通貨は24時間）。

監視銘柄は WATCH を編集（TradeScope本体の銘柄設定とは独立）。
状態確認: GET /api/ts/watch
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("ts_watch")
JST = timezone(timedelta(hours=9))

# ---- 監視銘柄（id, 表示名, 種別, 小数桁） ----
WATCH = [
    ("USDJPY", "ドル円", "fx", 3),
    ("EURUSD", "ユーロドル", "fx", 5),
    ("GBPJPY", "ポンド円", "fx", 3),
    ("XAUUSD", "ゴールド", "metal", 2),
    ("BTCUSDT", "ビットコイン", "crypto", 1),
    ("ETHUSDT", "イーサリアム", "crypto", 2),
    ("SOLUSDT", "ソラナ", "crypto", 2),
]

INTERVAL_SEC = 180          # 監視周期
DAILY_CAP = 80              # 1日の通知上限
COOLDOWN = {"entry": 120 * 60, "near": 3 * 3600, "align": 4 * 3600, "spike": 3600, "fake": 3600}

STATE = {"last_run": None, "heartbeat": None, "boot_time": None,
         "results": {}, "sent_today": 0,
         "sent_date": "", "errors": {}, "started": False,
         "news_upcoming": [], "news_recent": []}

# ---- シグナル成績の記録（自動採点） ----
import json as _json
from pathlib import Path as _Path
SIG_FILE = _Path(__file__).parent / "ts_signals.json"
SIGNALS: list = []
try:
    if SIG_FILE.exists():
        SIGNALS = _json.loads(SIG_FILE.read_text())
except Exception:  # noqa: BLE001
    SIGNALS = []


def _save_signals():
    try:
        SIG_FILE.write_text(_json.dumps(SIGNALS[-500:], ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def record_signal(sym_id, name, grade, direction, price, plan):
    SIGNALS.append({
        "t": time.time(), "sym": sym_id, "name": name, "grade": grade,
        "dir": direction, "entry": price, "sl": plan["sl"], "tp": plan["tp"],
        "status": "open"})
    _save_signals()


async def evaluate_signals():
    """未決着シグナルを5分足で自動採点。SL先タッチ=負け / TP先タッチ=勝ち / 24時間で期限切れ。"""
    now = time.time()
    for sig in SIGNALS:
        if sig["status"] != "open":
            continue
        try:
            if now - sig["t"] > 24 * 3600:
                sig["status"] = "expired"
                continue
            cs = await fetch_tf(sig["sym"], "5m", 300)
            hit = None
            for c in cs:
                if c["time"] <= sig["t"]:
                    continue
                if sig["dir"] == "buy":
                    if c["low"] <= sig["sl"]:
                        hit = "loss"
                        break
                    if c["high"] >= sig["tp"]:
                        hit = "win"
                        break
                else:
                    if c["high"] >= sig["sl"]:
                        hit = "loss"
                        break
                    if c["low"] <= sig["tp"]:
                        hit = "win"
                        break
            if hit:
                sig["status"] = hit
        except Exception:  # noqa: BLE001
            continue
    _save_signals()


def stats_summary():
    out = {"by_grade": {}, "by_symbol": {}, "total": {"win": 0, "loss": 0, "open": 0, "expired": 0}}
    for sig in SIGNALS:
        st = sig["status"]
        for key, bucket in ((sig["grade"], out["by_grade"]), (sig["sym"], out["by_symbol"])):
            b = bucket.setdefault(key, {"win": 0, "loss": 0, "open": 0, "expired": 0})
            b[st] = b.get(st, 0) + 1
        out["total"][st] = out["total"].get(st, 0) + 1
    for bucket in (out["by_grade"], out["by_symbol"]):
        for k, b in bucket.items():
            done = b["win"] + b["loss"]
            b["hit_rate"] = round(b["win"] / done * 100, 1) if done else None
    done = out["total"]["win"] + out["total"]["loss"]
    out["total"]["hit_rate"] = round(out["total"]["win"] / done * 100, 1) if done else None
    out["count"] = len(SIGNALS)
    return out
_last_sent: dict = {}
_task = None  # タスクへの強い参照（GC回収防止）


def start():
    """main.pyのlifespanから呼ぶ。タスク参照を保持して起動する。"""
    global _task
    import asyncio as _aio
    _task = _aio.create_task(watch_loop())
    return _task


# ================= テクニカル指標（純Python） =================
def ema_arr(vals, p):
    k = 2 / (p + 1)
    out, e = [None] * len(vals), None
    for i, v in enumerate(vals):
        e = v if e is None else v * k + e * (1 - k)
        if i >= p - 1:
            out[i] = e
    return out


def rsi_last(closes, p=14):
    if len(closes) < p + 2:
        return 50.0
    g = l = 0.0
    for i in range(1, p + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g, l = g / p, l / p
    for i in range(p + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        g = (g * (p - 1) + max(d, 0)) / p
        l = (l * (p - 1) + max(-d, 0)) / p
    if l == 0:
        return 100.0
    return 100 - 100 / (1 + g / l)


def atr_last(cs, p=14):
    if len(cs) < p + 2:
        return max(cs[-1]["high"] - cs[-1]["low"], 1e-9)
    a = None
    for i in range(1, len(cs)):
        tr = max(cs[i]["high"] - cs[i]["low"],
                 abs(cs[i]["high"] - cs[i - 1]["close"]),
                 abs(cs[i]["low"] - cs[i - 1]["close"]))
        a = tr if a is None else (a * (p - 1) + tr) / p
    return max(a, 1e-9)


def swings(cs, look=2):
    highs, lows = [], []
    for i in range(look, len(cs) - look):
        hi = all(cs[i]["high"] >= cs[i + j]["high"] and cs[i]["high"] >= cs[i - j]["high"]
                 for j in range(1, look + 1))
        lo = all(cs[i]["low"] <= cs[i + j]["low"] and cs[i]["low"] <= cs[i - j]["low"]
                 for j in range(1, look + 1))
        if hi:
            highs.append((i, cs[i]["high"]))
        if lo:
            lows.append((i, cs[i]["low"]))
    return highs, lows


def sr_levels(highs, lows, atr, max_levels=6):
    pts = sorted([p for _, p in highs] + [p for _, p in lows])
    tol = atr * 0.6 or 1e-9
    clusters = []
    for p in pts:
        for c in clusters:
            if abs(c["p"] - p) <= tol:
                c["p"] = (c["p"] * c["n"] + p) / (c["n"] + 1)
                c["n"] += 1
                break
        else:
            clusters.append({"p": p, "n": 1})
    good = [c for c in clusters if c["n"] >= 2]
    good.sort(key=lambda c: -c["n"])
    return sorted(good[:max_levels], key=lambda c: c["p"])


def analyze_tf(cs):
    closes = [c["close"] for c in cs]
    n = len(cs)
    last = cs[-1]
    e9, e21, e200 = ema_arr(closes, 9), ema_arr(closes, 21), ema_arr(closes, 200)
    a = atr_last(cs)
    highs, lows = swings(cs)
    sr = sr_levels(highs, lows, a)
    rsi = rsi_last(closes)
    up = (e9[-1] and e21[-1] and e9[-1] > e21[-1] and closes[-1] > e21[-1]
          and (e200[-1] is None or closes[-1] > e200[-1]))
    dn = (e9[-1] and e21[-1] and e9[-1] < e21[-1] and closes[-1] < e21[-1]
          and (e200[-1] is None or closes[-1] < e200[-1]))
    slope = ((e21[-1] - e21[-6]) / a) if (e21[-1] and n > 6 and e21[-6]) else 0
    trend = "up" if (up and slope > 0.15) else "down" if (dn and slope < -0.15) else "flat"
    last_high = highs[-1][1] if highs else max(c["high"] for c in cs[-40:])
    last_low = lows[-1][1] if lows else min(c["low"] for c in cs[-40:])
    r3 = sum(c["high"] - c["low"] for c in cs[-3:]) / 3
    vol_spike = r3 > a * 2.2
    fake = None
    ref_h = highs[-2][1] if len(highs) > 1 else None
    ref_l = lows[-2][1] if len(lows) > 1 else None
    for c in cs[max(1, n - 5):]:
        if ref_h and c["high"] > ref_h and c["close"] < ref_h and (ref_h - c["close"]) > a * 0.3:
            fake = "up"
        if ref_l and c["low"] < ref_l and c["close"] > ref_l and (c["close"] - ref_l) > a * 0.3:
            fake = "down"
    dist_e21 = (closes[-1] - e21[-1]) / a if e21[-1] else 99
    body = abs(last["close"] - last["open"])
    rng = max(last["high"] - last["low"], 1e-9)
    bull = last["close"] > last["open"] and body > rng * 0.45
    bear = last["close"] < last["open"] and body > rng * 0.45
    pb_buy = trend == "up" and abs(dist_e21) < 0.7 and 32 < rsi < 58 and bull
    pb_sell = trend == "down" and abs(dist_e21) < 0.7 and 42 < rsi < 68 and bear
    move5 = closes[-1] - closes[max(0, n - 6)]
    return {"trend": trend, "atr": a, "sr": sr, "last_high": last_high,
            "last_low": last_low, "vol_spike": vol_spike, "fake": fake,
            "pb_buy": pb_buy, "pb_sell": pb_sell, "rsi": rsi,
            "e21": e21[-1], "close": closes[-1],
            "chase": abs(move5) > a * 3}


# ================= 総合判定（ブラウザ版と同ロジック） =================
def judge(sym_id, name, kind, digits, tfs):
    d1, h4, h1 = tfs["1d"], tfs["4h"], tfs["1h"]
    m15, m5 = tfs["15m"], tfs["5m"]
    price = m5["close"]
    f = lambda v: f"{v:.{digits}f}"
    reasons = []
    higher = d1["trend"] if d1["trend"] == h4["trend"] else (
        h4["trend"] if h4["trend"] != "flat" else d1["trend"])
    mid = h1["trend"] if h1["trend"] != "flat" else m15["trend"]
    lower = m5["trend"]
    score, direction = 0, "none"
    if higher in ("up", "down"):
        direction = "buy" if higher == "up" else "sell"
        score += 2
        reasons.append("上位足（日足・4時間足）の方向が明確")
        if mid == higher:
            score += 2
            reasons.append("1時間足も同方向")
        elif mid != "flat":
            score -= 1
        pb = (m15["pb_buy"] or m5["pb_buy"]) if higher == "up" else (m15["pb_sell"] or m5["pb_sell"])
        if pb:
            score += 2
            reasons.append("押し目/戻りの反発初動を確認")
        if lower != "flat" and lower != higher:
            score -= 2
            reasons.append("5分足が逆行中")
        elif lower == higher:
            score += 1
    sr_all = [(s["p"], "4h") for s in h4["sr"]] + [(s["p"], "1h") for s in h1["sr"]]
    above = sorted([p for p, _ in sr_all if p > price])
    below = sorted([p for p, _ in sr_all if p < price], reverse=True)
    a1 = h1["atr"]
    if direction == "buy" and above and (above[0] - price) < a1 * 1.2:
        score -= 2
        reasons.append(f"直上{f(above[0])}に抵抗帯")
    if direction == "sell" and below and (price - below[0]) < a1 * 1.2:
        score -= 2
        reasons.append(f"直下{f(below[0])}に支持帯")
    fake = m15["fake"] or m5["fake"]
    if fake:
        score -= 2
    if m5["chase"] or m15["chase"]:
        score -= 2
        reasons.append("急変動直後の飛び乗り危険")
    if m5["vol_spike"]:
        score -= 1
    plan = None
    if direction in ("buy", "sell"):
        ae = m15["atr"]
        if direction == "buy":
            pull = max(m15["e21"] or price - ae, below[0] if below else price - ae)
            entry = price if (m15["pb_buy"] or m5["pb_buy"]) else min(price, pull)
            sl = min(m15["last_low"], m5["last_low"]) - ae * 0.3
            if sl >= entry - ae * 0.4:
                sl = entry - ae * 1.2
            tp = above[0] if (above and above[0] > entry + ae * 0.5) else entry + ae * 2
        else:
            pull = min(m15["e21"] or price + ae, above[0] if above else price + ae)
            entry = price if (m15["pb_sell"] or m5["pb_sell"]) else max(price, pull)
            sl = max(m15["last_high"], m5["last_high"]) + ae * 0.3
            if sl <= entry + ae * 0.4:
                sl = entry + ae * 1.2
            tp = below[0] if (below and below[0] < entry - ae * 0.5) else entry - ae * 2
        risk = abs(entry - sl)
        rr = abs(tp - entry) / risk if risk > 0 else 0
        plan = {"entry": entry, "sl": sl, "tp": tp, "rr": rr}
        if rr >= 2:
            score += 2
            reasons.append(f"リスクリワード1:{rr:.1f}")
        elif rr >= 1.3:
            score += 1
        else:
            score -= 1
    if direction == "none":
        grade = "D"
    elif score >= 7:
        grade = "S"
    elif score >= 5:
        grade = "A"
    elif score >= 3:
        grade = "B"
    elif score >= 1:
        grade = "C"
    else:
        grade = "D"
    aligned = (d1["trend"] != "flat" and d1["trend"] == h4["trend"] == h1["trend"]
               == m15["trend"] == m5["trend"])
    return {"grade": grade, "dir": direction, "price": price, "plan": plan,
            "reasons": reasons[:4], "aligned": aligned, "fake": fake,
            "spike": m5["vol_spike"], "fmt": f}


# ================= 通知 =================
def _cool_ok(sym, typ):
    now = time.time()
    today = datetime.now(JST).strftime("%Y%m%d")
    if STATE["sent_date"] != today:
        STATE["sent_date"] = today
        STATE["sent_today"] = 0
    if STATE["sent_today"] >= DAILY_CAP:
        return False
    key = (sym, typ)
    if now - _last_sent.get(key, 0) < COOLDOWN[typ]:
        return False
    _last_sent[key] = now
    STATE["sent_today"] += 1
    return True


MONTHLY_LINE_CAP = 190  # LINE無料枠200通を超えないための予算
_month_budget = {"month": "", "count": 0}


def _line_budget_ok(priority="normal"):
    """月間予算チェック。残りわずかならS判定など高優先のみ通す。"""
    m = datetime.now(JST).strftime("%Y%m")
    if _month_budget["month"] != m:
        _month_budget["month"] = m
        _month_budget["count"] = 0
    used = _month_budget["count"]
    if used >= MONTHLY_LINE_CAP:
        return False
    if used >= MONTHLY_LINE_CAP - 30 and priority != "high":
        return False  # 残り30通は重要通知専用に温存
    _month_budget["count"] += 1
    STATE["line_sent_month"] = _month_budget["count"]
    return True


async def _line(text, priority="normal"):
    if not _line_budget_ok(priority):
        return
    import notifier
    await notifier.send_line("【TradeScope監視】" + text)


async def maybe_notify(sym_id, name, kind, r):
    f = r["fmt"]
    dir_j = "買い" if r["dir"] == "buy" else "売り"
    if r.get("news_wait"):
        return  # 重要指標の直前直後はエントリー系通知を止める
    if r["grade"] in ("S", "A") and r["dir"] != "none" and _cool_ok(sym_id, "entry"):
        record_signal(sym_id, name, r["grade"], r["dir"], r["price"], r["plan"])
        p = r["plan"]
        body = (f"{name}({sym_id}) {dir_j}候補 判定{r['grade']}\n"
                f"現在値 {f(r['price'])}\n"
                f"目安: エントリー{f(p['entry'])} / 損切り{f(p['sl'])} / "
                f"利確{f(p['tp'])} (RR 1:{p['rr']:.1f})\n"
                f"根拠: {'・'.join(r['reasons'])}\n"
                f"※飛び乗らず引き付けて。最終判断はご自身で。")
        await _line(body, priority="high")
    if r["grade"] == "B" and r["dir"] != "none" and _cool_ok(sym_id, "near"):
        record_signal(sym_id, name, "B", r["dir"], r["price"], r["plan"])
        # B判定は記録のみ（LINE無料枠の節約。成績集計には反映される）
    # 方向一致・急変動・だましはLINE送信せず（無料枠節約。アプリ内通知は従来どおり）


# ================= データ取得（ts_apiを再利用） =================
async def fetch_tf(sym_id, tf, limit):
    import ts_api
    if sym_id in ts_api.GMO_FX:
        return await ts_api.gmo_klines(ts_api.GMO_FX[sym_id], tf, limit)
    if sym_id in ts_api.BINANCE_MAP:
        return await ts_api.binance_klines(ts_api.BINANCE_MAP[sym_id], tf, limit)
    if sym_id.endswith("USDT"):
        return await ts_api.binance_klines(sym_id, tf, limit)
    return await ts_api.td_klines(sym_id, tf, limit)


async def analyze_symbol(sym_id, name, kind, digits):
    tfs = {}
    for tf, limit in (("5m", 300), ("15m", 300), ("1h", 300), ("4h", 300), ("1d", 260)):
        cs = await fetch_tf(sym_id, tf, limit)
        if len(cs) < 60:
            raise ValueError(f"{tf}のデータ不足({len(cs)}本)")
        tfs[tf] = analyze_tf(cs)
    return judge(sym_id, name, kind, digits, tfs)


# ================= 常駐ループ =================
_news_warned: set = set()
_news_resulted: set = set()


async def process_news():
    """事前警告（発表35分前）と結果速報（発表後20分以内）をLINEへ。"""
    import ts_news
    all_cur = set()
    for sym_id, _, _, _ in WATCH:
        all_cur.update(ts_news.currencies_of(sym_id))
    # 直近に指標がある時はカレンダーを高頻度更新（結果値を早く拾う）
    events = await ts_news.fetch_events()
    near = ts_news.upcoming(events, all_cur, within_min=10) or         ts_news.recent_results(events, all_cur, since_min=10)
    if near:
        events = await ts_news.fetch_events(force=True)
    # 画面用の要約をSTATEへ
    STATE["news_upcoming"] = [
        {"title": e["title"], "cur": e["cur"], "in_min": e["in_min"], "impact": e["impact"]}
        for e in ts_news.upcoming(events, all_cur, within_min=120)][:6]
    STATE["news_recent"] = [
        {"title": e["title"], "cur": e["cur"], "ago_min": e["ago_min"],
         "actual": e["actual"], "forecast": e["forecast"], "bias_text": e["bias_text"]}
        for e in ts_news.recent_results(events, all_cur, since_min=90)][:6]
    # 事前警告
    for e in ts_news.upcoming(events, all_cur, within_min=35):
        if e["id"] in _news_warned:
            continue
        _news_warned.add(e["id"])
        rel = [n for sid, n, k, _ in WATCH
               if e["cur"] in ts_news.currencies_of(sid) and k != "crypto"]
        if _cool_ok("NEWS", "spike"):
            await _line(f"⏰ {e['in_min']}分後に重要指標【{e['cur']}】{e['title']}\n"
                        f"関連: {'・'.join(rel[:4])}\n"
                        f"発表前後は値が飛びます。新規エントリーは通過後に。")
    # 結果速報
    for e in ts_news.recent_results(events, all_cur, since_min=20):
        if e["id"] in _news_resulted:
            continue
        _news_resulted.add(e["id"])
        move = ""
        try:
            fx = next((sid for sid, _, k, _ in WATCH
                       if k == "fx" and e["cur"] in ts_news.currencies_of(sid)), None)
            if fx and e["bias"] != 0:
                cs = await fetch_tf(fx, "5m", 6)
                drift = cs[-1]["close"] - cs[-3]["close"]
                base_up = fx.startswith(e["cur"])  # 通貨が基軸なら買い材料=上
                expect_up = (e["bias"] > 0) == base_up
                agree = (drift > 0) == expect_up
                move = f"\n{fx}の値動きは結果と{'一致（順張り検討可）' if agree else '逆行（手出し無用・様子見）'}"
        except Exception:  # noqa: BLE001
            pass
        await _line(f"📊 指標結果【{e['cur']}】{e['title']}\n"
                    f"結果 {e['actual']} / 予想 {e['forecast']} → {e['bias_text']}{move}\n"
                    f"※初動は乱高下しやすい。15分足の確定を待つのが安全。")


async def watch_loop():
    if STATE["started"]:
        return
    STATE["started"] = True
    STATE["boot_time"] = datetime.now(JST).isoformat(timespec="seconds")
    log.info("TradeScope 24時間監視を開始（%d銘柄・%d秒周期）", len(WATCH), INTERVAL_SEC)
    await asyncio.sleep(5)
    import ts_news
    cycle = 0
    while True:
        jst = datetime.now(JST)
        STATE["heartbeat"] = jst.isoformat(timespec="seconds")
        weekend = jst.weekday() >= 5
        try:
            await process_news()
        except Exception as e:  # noqa: BLE001
            log.warning("指標処理エラー: %s", e)
        events = await ts_news.fetch_events()
        for sym_id, name, kind, digits in WATCH:
            if weekend and kind in ("fx", "metal"):
                continue
            try:
                r = await analyze_symbol(sym_id, name, kind, digits)
                # 重要指標が45分以内なら判定を強制的に「待ち」へ
                ups = ts_news.upcoming(events, ts_news.currencies_of(sym_id), within_min=45)
                if ups and r["grade"] in ("S", "A", "B"):
                    r["news_wait"] = ups[0]["title"]
                    r["grade"] = "C"
                STATE["results"][sym_id] = {
                    "grade": r["grade"], "dir": r["dir"],
                    "price": round(r["price"], digits),
                    "news_wait": r.get("news_wait"),
                    "time": jst.isoformat(timespec="seconds")}
                STATE["errors"].pop(sym_id, None)
                await maybe_notify(sym_id, name, kind, r)
            except Exception as e:  # noqa: BLE001
                STATE["errors"][sym_id] = str(e)[:200]
                log.warning("監視エラー %s: %s", sym_id, e)
            await asyncio.sleep(2)
        cycle += 1
        if cycle % 2 == 0:  # 6分ごとにシグナル採点
            try:
                await evaluate_signals()
            except Exception:  # noqa: BLE001
                pass
        STATE["last_run"] = datetime.now(JST).isoformat(timespec="seconds")
        await asyncio.sleep(INTERVAL_SEC)
