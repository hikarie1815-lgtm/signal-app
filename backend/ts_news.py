"""
ts_news.py — 経済指標カレンダー連携（TradeScope用）

データ源: Forex Factory 週間カレンダー(無料・キー不要)
  https://nfs.faireconomy.media/ff_calendar_thisweek.json
  形式: [{"title","country","date","impact","forecast","actual"}, ...]

提供機能:
  - upcoming(currencies, within_min): 指定通貨のこれから来る指標
  - recent_results(currencies, since_min): 発表済みの結果（予想比バイアス付き）
  - bias(): 結果が予想より通貨にとって強いか弱いかの教科書的解釈
    ※「失業率」「失業保険申請」「在庫」等は数値が高い=悪材料として反転
"""
import re
import time
import logging
from datetime import datetime, timezone

import httpx

log = logging.getLogger("ts_news")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# 数値が「高いほど通貨にマイナス」の指標キーワード
INVERTED = ("unemployment", "jobless", "claims", "inventories", "inventory")

_cache = {"t": 0.0, "events": []}


def _num(s):
    """'3.2%', '204K', '-0.5M' などを数値化。無理ならNone。"""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    m = re.match(r"^(-?\d+(?:\.\d+)?)\s*([%KMBT]?)$", s.replace(",", ""), re.I)
    if not m:
        return None
    v = float(m.group(1))
    mul = {"": 1, "%": 1, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2).upper()]
    return v * mul


async def fetch_events(force=False):
    """カレンダーを取得（通常10分キャッシュ / force時は2分）。"""
    ttl = 120 if force else 600
    if _cache["events"] and time.time() - _cache["t"] < ttl:
        return _cache["events"]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(FF_URL, headers={"User-Agent": "TradeScope/2.1"})
            r.raise_for_status()
            raw = r.json()
        events = []
        for e in raw:
            try:
                ts = datetime.fromisoformat(e["date"]).timestamp()
            except Exception:  # noqa: BLE001
                continue
            events.append({
                "id": f"{e.get('title','')}|{e.get('country','')}|{e.get('date','')}",
                "title": e.get("title", ""),
                "cur": (e.get("country") or "").upper(),
                "ts": ts,
                "impact": (e.get("impact") or "").capitalize(),  # High/Medium/Low
                "forecast": e.get("forecast") or "",
                "actual": e.get("actual") or "",
            })
        _cache["events"] = events
        _cache["t"] = time.time()
    except Exception as ex:  # noqa: BLE001
        log.warning("カレンダー取得失敗: %s", ex)
    return _cache["events"]


def bias(ev):
    """結果の教科書的解釈。+1=通貨に強材料 / -1=弱材料 / 0=判定不能・予想通り"""
    a, f = _num(ev.get("actual")), _num(ev.get("forecast"))
    if a is None or f is None or a == f:
        return 0
    better = 1 if a > f else -1
    if any(k in ev.get("title", "").lower() for k in INVERTED):
        better = -better
    return better


def bias_text(ev, b):
    d = "上振れ" if _num(ev.get("actual")) > _num(ev.get("forecast")) else "下振れ"
    if b > 0:
        return f"{d}（{ev['cur']}買い材料）"
    if b < 0:
        return f"{d}（{ev['cur']}売り材料）"
    return "ほぼ予想通り（初動の往復に注意）"


def upcoming(events, currencies, within_min=60, min_impact="High"):
    now = time.time()
    ranks = {"High": 3, "Medium": 2, "Low": 1}
    need = ranks.get(min_impact, 3)
    out = []
    for e in events:
        if e["cur"] not in currencies:
            continue
        if ranks.get(e["impact"], 0) < need:
            continue
        dt = e["ts"] - now
        if 0 <= dt <= within_min * 60:
            out.append(dict(e, in_min=int(dt // 60)))
    return sorted(out, key=lambda x: x["ts"])


def recent_results(events, currencies, since_min=45, min_impact="High"):
    now = time.time()
    ranks = {"High": 3, "Medium": 2, "Low": 1}
    need = ranks.get(min_impact, 3)
    out = []
    for e in events:
        if e["cur"] not in currencies or not e["actual"]:
            continue
        if ranks.get(e["impact"], 0) < need:
            continue
        ago = now - e["ts"]
        if 0 <= ago <= since_min * 60:
            b = bias(e)
            out.append(dict(e, ago_min=int(ago // 60), bias=b,
                            bias_text=bias_text(e, b)))
    return sorted(out, key=lambda x: -x["ts"])


def currencies_of(sym_id: str):
    s = sym_id.upper()
    if s.endswith("USDT"):
        return ["USD"]  # 仮想通貨も米指標の影響を受ける
    if s.startswith("XAU") or s.startswith("XAG") or s.startswith("XPT") or s.startswith("XPD"):
        return ["USD"]
    if len(s) == 6:
        return [s[:3], s[3:]]
    return []
