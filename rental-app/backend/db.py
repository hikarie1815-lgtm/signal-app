"""SQLite データベース層。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get("RENTAL_DB", os.path.join(os.path.dirname(__file__), "..", "data.db"))
JST = timezone(timedelta(hours=9))


def now_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, role TEXT NOT NULL CHECK(role IN('admin','employee')),
  name TEXT NOT NULL, display_name TEXT NOT NULL, login_id TEXT UNIQUE NOT NULL,
  email TEXT, password_hash TEXT NOT NULL, must_change_password INTEGER DEFAULT 0,
  active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT, expires_at TEXT);
CREATE TABLE IF NOT EXISTS company(
  id INTEGER PRIMARY KEY CHECK(id=1), company_name TEXT, admin_name TEXT,
  closing_day INTEGER DEFAULT 31, created_at TEXT);
CREATE TABLE IF NOT EXISTS sites(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, contractor TEXT DEFAULT '',
  status TEXT DEFAULT 'active', address TEXT DEFAULT '',
  created_by INTEGER, deleted INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS vendors(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN('rental','hauler','disposal')),
  name TEXT NOT NULL, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS price_master(
  id INTEGER PRIMARY KEY, code TEXT DEFAULT '', name TEXT NOT NULL, spec TEXT DEFAULT '',
  daily_rate INTEGER, monthly_rate INTEGER, basic_fee INTEGER,
  support_per_day INTEGER, damage_per_day INTEGER,
  needs_review INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  source_image TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS price_import_batches(
  id INTEGER PRIMARY KEY, filename TEXT, image_path TEXT, status TEXT DEFAULT 'open',
  created_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS price_import_rows(
  id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL, code TEXT DEFAULT '',
  name TEXT DEFAULT '', spec TEXT DEFAULT '',
  daily_rate INTEGER, monthly_rate INTEGER, basic_fee INTEGER,
  support_per_day INTEGER, damage_per_day INTEGER,
  needs_review INTEGER DEFAULT 0, note TEXT DEFAULT '',
  status TEXT DEFAULT 'pending');
CREATE TABLE IF NOT EXISTS rentals(
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, vendor_id INTEGER,
  item_id INTEGER, item_name TEXT NOT NULL, spec TEXT DEFAULT '', code TEXT DEFAULT '',
  qty INTEGER NOT NULL, start_date TEXT NOT NULL, due_date TEXT NOT NULL,
  returned_date TEXT,
  daily_rate INTEGER DEFAULT 0, monthly_rate INTEGER DEFAULT 0, basic_fee INTEGER DEFAULT 0,
  support_per_day INTEGER DEFAULT 0, damage_per_day INTEGER DEFAULT 0,
  status TEXT DEFAULT 'active',
  condition_flags TEXT DEFAULT '{}', condition_comment TEXT DEFAULT '',
  wf_status TEXT DEFAULT 'unconfirmed', wf_reason TEXT DEFAULT '',
  amount_total INTEGER, amount_locked INTEGER DEFAULT 0,
  created_by INTEGER, deleted INTEGER DEFAULT 0,
  client_key TEXT UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS rental_extensions(
  id INTEGER PRIMARY KEY, rental_id INTEGER NOT NULL, old_due TEXT, new_due TEXT,
  reason TEXT, comment TEXT DEFAULT '', created_by INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS waste_records(
  id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL, out_date TEXT NOT NULL,
  waste_type TEXT NOT NULL, qty REAL NOT NULL, unit TEXT NOT NULL,
  hauler_id INTEGER, disposal_id INTEGER, disposal_done INTEGER DEFAULT 0,
  slip_no TEXT DEFAULT '', amount INTEGER,
  wf_status TEXT DEFAULT 'unconfirmed', wf_reason TEXT DEFAULT '',
  created_by INTEGER, deleted INTEGER DEFAULT 0,
  client_key TEXT UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS photos(
  id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, target_id INTEGER,
  category TEXT DEFAULT 'その他', file_path TEXT NOT NULL,
  taken_by INTEGER, created_at TEXT, sort_order INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
  payload TEXT NOT NULL, updated_at TEXT);
CREATE TABLE IF NOT EXISTS delete_requests(
  id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, target_id INTEGER NOT NULL,
  reason TEXT DEFAULT '', requested_by INTEGER, status TEXT DEFAULT 'pending',
  decided_by INTEGER, decided_at TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY, user_id INTEGER, user_name TEXT, action TEXT,
  target_type TEXT, target_id INTEGER, before_json TEXT, after_json TEXT,
  device TEXT DEFAULT '', created_at TEXT, synced_at TEXT);
CREATE TABLE IF NOT EXISTS user_prefs(
  user_id INTEGER NOT NULL, key TEXT NOT NULL, value TEXT,
  PRIMARY KEY(user_id, key));
"""

WASTE_TYPES = ["木くず", "枝葉", "根株", "竹", "刈草", "草", "伐採材",
               "コンクリートがら", "アスファルトがら", "残土", "混合廃棄物", "その他"]
WASTE_TYPES_TOP = ["枝葉", "根株", "竹", "刈草", "草", "伐採材"]
WASTE_UNITS = ["kg", "t", "㎥", "台", "袋", "式"]
EXTENSION_REASONS = ["工程変更", "作業遅延", "追加工事", "天候", "元請都合", "その他"]
PHOTO_CATEGORIES = ["レンタル開始", "レンタル返却", "機械全体", "管理番号", "故障・破損",
                    "廃棄物積込前", "積込中", "積込後", "処分場", "計量票",
                    "マニフェスト", "請求書", "その他"]
WF_STATUSES = ["unconfirmed", "confirmed", "fix_requested", "fixed_amount", "billed", "paid"]
WF_LABELS = {"unconfirmed": "未確認", "confirmed": "確認済み", "fix_requested": "修正依頼",
             "fixed_amount": "金額確定", "billed": "請求済み", "paid": "支払済み"}


def init_db() -> None:
    conn = get_db()
    conn.executescript(SCHEMA)
    # 既存DBへの追加カラム（初期リリース後の変更分）
    try:
        conn.execute("ALTER TABLE sites ADD COLUMN created_by INTEGER")
    except Exception:
        pass  # 追加済み
    conn.commit()
    conn.close()


def audit(conn: sqlite3.Connection, user, action: str, target_type: str,
          target_id, before=None, after=None, device: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log(user_id,user_name,action,target_type,target_id,"
        "before_json,after_json,device,created_at,synced_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user["id"] if user else None, user["name"] if user else "system", action,
         target_type, target_id,
         json.dumps(before, ensure_ascii=False) if before is not None else None,
         json.dumps(after, ensure_ascii=False) if after is not None else None,
         device, now_str(), now_str()))


def get_pref(conn, user_id: int, key: str, default=None):
    row = conn.execute("SELECT value FROM user_prefs WHERE user_id=? AND key=?",
                       (user_id, key)).fetchone()
    return json.loads(row["value"]) if row else default


def set_pref(conn, user_id: int, key: str, value) -> None:
    conn.execute("INSERT INTO user_prefs(user_id,key,value) VALUES(?,?,?) "
                 "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
                 (user_id, key, json.dumps(value, ensure_ascii=False)))
