"""認証・権限。"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request

from .db import JST, get_db, now_str

SESSION_DAYS = 30


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def create_session(conn, user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (datetime.now(JST) + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                 (token, user_id, now_str(), expires))
    return token


def current_user(request: Request) -> dict:
    token = request.cookies.get("session") or request.headers.get("x-session-token")
    if not token:
        raise HTTPException(401, "ログインしてください")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id "
            "WHERE s.token=? AND s.expires_at>=?", (token, now_str())).fetchone()
        if not row or not row["active"]:
            raise HTTPException(401, "ログインの有効期限が切れています。もう一度ログインしてください")
        return dict(row)
    finally:
        conn.close()


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "この操作は管理者だけができます")
    return user
