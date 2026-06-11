"""通知: Discord Webhook / LINE Messaging API / ブラウザ(WebSocket経由)。
同一銘柄・同一シグナルはクールダウン時間内は再通知しない。"""
import logging
import time

import httpx

import config

log = logging.getLogger("notifier")

_last_sent: dict[tuple, float] = {}
_browser_queue: list[dict] = []  # main.pyがWebSocketで配信


def _cooldown_ok(key: tuple) -> bool:
    now = time.time()
    if now - _last_sent.get(key, 0) < config.NOTIFY_COOLDOWN_SEC:
        return False
    _last_sent[key] = now
    return True


async def send_discord(text: str):
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(config.DISCORD_WEBHOOK_URL, json={"content": text})
    except Exception as e:
        log.warning("Discord通知失敗: %s", e)


async def send_line(text: str):
    if not (config.LINE_CHANNEL_ACCESS_TOKEN and config.LINE_USER_ID):
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}"},
                json={"to": config.LINE_USER_ID, "messages": [{"type": "text", "text": text}]},
            )
    except Exception as e:
        log.warning("LINE通知失敗: %s", e)


def queue_browser(title: str, body: str):
    _browser_queue.append({"title": title, "body": body})


def pop_browser_alerts() -> list:
    global _browser_queue
    q, _browser_queue = _browser_queue, []
    return q


async def notify_all(key: tuple, title: str, body: str):
    if not _cooldown_ok(key):
        return
    text = f"【{title}】\n{body}"
    await send_discord(text)
    await send_line(text)
    queue_browser(title, body)
    log.info("通知: %s", title)


async def check_and_notify(res: dict, stats: dict | None, journal: dict):
    """通知条件の判定(仕様準拠)。"""
    sym, sig = res["symbol"], res["signal"]
    price = res["price"]
    base = (f"{res['name']}({sym})\n価格: {price:,.4g}\nスコア: {res['score']}点\n"
            f"推奨SL: {res['sl']:,.4g} / TP: {res['tp']:,.4g} (RR {res['rr']})")

    # 1) STRONG BUY / STRONG SELL
    if sig in ("STRONG BUY", "STRONG SELL"):
        await notify_all((sym, sig), f"{sig} シグナル", base)

    # 2) 勝率60%以上 かつ PF1.5以上 かつ 期待値プラス(売買シグナル時)
    if stats and sig in ("BUY", "SELL", "STRONG BUY", "STRONG SELL"):
        s = stats.get("stats", {})
        if s.get("win_rate", 0) >= 60 and s.get("pf", 0) >= 1.5 and s.get("ev_r", 0) > 0:
            await notify_all(
                (sym, "high_quality", sig),
                f"高勝率シグナル {sig}",
                base + f"\n勝率{s['win_rate']}% / PF{s['pf']} / 期待値+{s['ev_jpy']:,}円",
            )

    # 3) 1日最大損失到達
    if journal.get("daily_loss_hit"):
        await notify_all(("journal", "daily_loss"), "⚠️ 1日最大損失に到達",
                         f"本日の損益: {journal['today_pnl']:,}円\n本日の取引は停止を推奨します。")

    # 4) 連敗警告
    if journal.get("consec_warning"):
        await notify_all(("journal", "consec"), "⚠️ 連敗警告",
                         f"{journal['consec_losses']}連敗中です。一度休憩して相場環境を見直してください。")
