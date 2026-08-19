"""SQLite データベース層。"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

# 保存場所。本番で永続ディスクを使うときは DARTS_DATA_DIR=/var/data を指定する。
DATA_DIR = os.environ.get(
    "DARTS_DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.environ.get("DARTS_DB", os.path.join(DATA_DIR, "darts.db"))
JST = timezone(timedelta(hours=9))


def now_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT DEFAULT '',
  deleted INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS players(
  id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, name TEXT NOT NULL,
  rating REAL, ppd REAL, mpr REAL, note TEXT DEFAULT '',
  active INTEGER DEFAULT 1, deleted INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS matches(
  id INTEGER PRIMARY KEY, section TEXT DEFAULT '', match_date TEXT,
  home_team_id INTEGER, away_team_id INTEGER, away_name TEXT DEFAULT '',
  away_rating REAL, home_sign TEXT DEFAULT '', away_sign TEXT DEFAULT '',
  note TEXT DEFAULT '', deleted INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, side TEXT NOT NULL,
  slot INTEGER NOT NULL, player_id INTEGER NOT NULL,
  UNIQUE(match_id, side, slot), UNIQUE(match_id, side, player_id));
CREATE TABLE IF NOT EXISTS games(
  id INTEGER PRIMARY KEY, match_id INTEGER NOT NULL, game_no INTEGER NOT NULL,
  name TEXT, kind TEXT, mode TEXT, rounds INTEGER, coins INTEGER,
  lottery INTEGER DEFAULT 0, fixed INTEGER DEFAULT 0,
  winner TEXT DEFAULT '', note TEXT DEFAULT '',
  UNIQUE(match_id, game_no));
CREATE TABLE IF NOT EXISTS game_players(
  id INTEGER PRIMARY KEY, game_id INTEGER NOT NULL, side TEXT NOT NULL,
  player_id INTEGER NOT NULL, locked INTEGER DEFAULT 0,
  UNIQUE(game_id, side, player_id));
CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
CREATE INDEX IF NOT EXISTS idx_entries_match ON entries(match_id);
CREATE INDEX IF NOT EXISTS idx_games_match ON games(match_id);
CREATE INDEX IF NOT EXISTS idx_gp_game ON game_players(game_id);
"""


def init_db() -> None:
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def rows(conn, sql, args=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(conn, sql, args=()) -> dict | None:
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None
