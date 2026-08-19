"""KI-LEAGUE ダーツリーグ 対戦表・スコアシート API"""
from __future__ import annotations

import csv
import io
import os

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cloud_sync
from . import db as D
from . import games as G
from . import rating as R
from .db import get_db, now_str, one, rows
from .lineup import OBJECTIVES, Assigner, expected_opponent_strength, tag_of

app = FastAPI(title="KI-LEAGUE ダーツリーグ")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, "static")

if cloud_sync.init():
    cloud_sync.restore(D.DB_PATH)
D.init_db()

SIDES = ("home", "away")


@app.middleware("http")
async def _backup_after_writes(request: Request, call_next):
    resp = await call_next(request)
    if request.method in ("POST", "PUT", "DELETE") and resp.status_code < 400:
        cloud_sync.mark_dirty(D.DB_PATH)
    return resp


def err(message: str, status: int = 422):
    return JSONResponse({"error": message}, status_code=status)


def num(v):
    """空文字は None、数値は float にする（入力欄が空のときの扱い）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def check_side(side: str) -> str:
    if side not in SIDES:
        raise HTTPException(400, "side は home か away です")
    return side


# ---------------------------------------------------------------- メタ情報
@app.get("/api/meta")
def meta():
    return {
        "template": G.template(),
        "mode_size": G.MODE_SIZE,
        "mode_label": G.MODE_LABEL,
        "objectives": OBJECTIVES,
        "bonus_point": R.BONUS_POINT,
        "total_slots": G.TOTAL_SLOTS,
        "cloud": cloud_sync.enabled(),
    }


@app.get("/api/health")
def health():
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) c FROM matches WHERE deleted=0").fetchone()["c"]
    conn.close()
    return {"ok": True, "matches": n, "cloud": cloud_sync.enabled()}


# ---------------------------------------------------------------- チーム
def team_dict(conn, row) -> dict:
    ps = rows(conn, "SELECT * FROM players WHERE team_id=? AND deleted=0 ORDER BY id", (row["id"],))
    rt = [player_view(p)["rating"] for p in ps if p["active"]]
    return {**row, "player_count": len(ps),
            "avg_rating": round(sum(rt) / len(rt), 2) if rt else None}


@app.get("/api/teams")
def list_teams():
    conn = get_db()
    out = [team_dict(conn, t) for t in
           rows(conn, "SELECT * FROM teams WHERE deleted=0 ORDER BY id")]
    conn.close()
    return {"teams": out}


@app.post("/api/teams")
def create_team(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        return err("チーム名を入力してください")
    conn = get_db()
    cur = conn.execute("INSERT INTO teams(name, note, created_at) VALUES(?,?,?)",
                       (name, body.get("note", ""), now_str()))
    conn.commit()
    t = one(conn, "SELECT * FROM teams WHERE id=?", (cur.lastrowid,))
    out = team_dict(conn, t)
    conn.close()
    return {"team": out}


@app.put("/api/teams/{team_id}")
def update_team(team_id: int, body: dict = Body(...)):
    conn = get_db()
    if not one(conn, "SELECT id FROM teams WHERE id=? AND deleted=0", (team_id,)):
        conn.close()
        return err("チームが見つかりません", 404)
    conn.execute("UPDATE teams SET name=COALESCE(?,name), note=COALESCE(?,note) WHERE id=?",
                 ((body.get("name") or "").strip() or None, body.get("note"), team_id))
    conn.commit()
    out = team_dict(conn, one(conn, "SELECT * FROM teams WHERE id=?", (team_id,)))
    conn.close()
    return {"team": out}


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int):
    conn = get_db()
    conn.execute("UPDATE teams SET deleted=1 WHERE id=?", (team_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- 選手
def by_rating(players: list[dict]) -> list[dict]:
    """レーティングの高い順に並べる（同じなら名前順）。

    出場の順番（①②③…、投げる順）はすべてこの並びに合わせる。
    """
    return sorted(players, key=lambda p: (-p["rating"], p["name"]))


def player_view(p: dict) -> dict:
    """DBの選手行に、種目ごとの強さ(Rt換算)を足して返す。"""
    s = R.player_skills(p.get("rating"), p.get("ppd"), p.get("mpr"))
    return {**p, "rating": s["rating"], "input_rating": p.get("rating"),
            "skill_01": round(s["01"], 2), "skill_cricket": round(s["cricket"], 2),
            "est_ppd": s["ppd"], "est_mpr": s["mpr"]}


@app.get("/api/teams/{team_id}/players")
def list_players(team_id: int):
    conn = get_db()
    ps = rows(conn, "SELECT * FROM players WHERE team_id=? AND deleted=0 ORDER BY id", (team_id,))
    conn.close()
    return {"players": by_rating([player_view(p) for p in ps])}


@app.post("/api/players")
def create_player(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    team_id = body.get("team_id")
    if not name:
        return err("選手名を入力してください")
    conn = get_db()
    if not one(conn, "SELECT id FROM teams WHERE id=? AND deleted=0", (team_id,)):
        conn.close()
        return err("チームを選んでください")
    cur = conn.execute(
        "INSERT INTO players(team_id,name,rating,ppd,mpr,note,active,created_at)"
        " VALUES(?,?,?,?,?,?,1,?)",
        (team_id, name, num(body.get("rating")), num(body.get("ppd")), num(body.get("mpr")),
         body.get("note", ""), now_str()))
    conn.commit()
    p = one(conn, "SELECT * FROM players WHERE id=?", (cur.lastrowid,))
    conn.close()
    return {"player": player_view(p)}


@app.put("/api/players/{player_id}")
def update_player(player_id: int, body: dict = Body(...)):
    conn = get_db()
    p = one(conn, "SELECT * FROM players WHERE id=? AND deleted=0", (player_id,))
    if not p:
        conn.close()
        return err("選手が見つかりません", 404)
    name = (body.get("name") or "").strip() or p["name"]
    fields = {"rating": num(body.get("rating")), "ppd": num(body.get("ppd")),
              "mpr": num(body.get("mpr"))}
    for k, v in fields.items():
        if k not in body:  # 送られてこなかった項目は今の値を保つ
            fields[k] = p[k]
    active = int(bool(body.get("active", p["active"])))
    conn.execute(
        "UPDATE players SET name=?, rating=?, ppd=?, mpr=?, note=?, active=? WHERE id=?",
        (name, fields["rating"], fields["ppd"], fields["mpr"],
         body.get("note", p["note"]), active, player_id))
    conn.commit()
    out = player_view(one(conn, "SELECT * FROM players WHERE id=?", (player_id,)))
    conn.close()
    return {"player": out}


@app.delete("/api/players/{player_id}")
def delete_player(player_id: int):
    conn = get_db()
    conn.execute("UPDATE players SET deleted=1 WHERE id=?", (player_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------------------------------------------------------------- 節（対戦）
@app.get("/api/matches")
def list_matches():
    conn = get_db()
    out = []
    for m in rows(conn, "SELECT * FROM matches WHERE deleted=0 ORDER BY id DESC"):
        gs = rows(conn, "SELECT winner FROM games WHERE match_id=?", (m["id"],))
        out.append({**m,
                    "home_team_name": team_name(conn, m["home_team_id"]),
                    "away_team_name": away_label(conn, m),
                    "home_wins": sum(1 for g in gs if g["winner"] == "home"),
                    "away_wins": sum(1 for g in gs if g["winner"] == "away"),
                    "played": sum(1 for g in gs if g["winner"]), "games": len(gs)})
    conn.close()
    return {"matches": out}


def team_name(conn, team_id) -> str:
    t = one(conn, "SELECT name FROM teams WHERE id=?", (team_id,)) if team_id else None
    return t["name"] if t else ""


def away_label(conn, m: dict) -> str:
    return team_name(conn, m["away_team_id"]) or (m["away_name"] or "相手チーム")


@app.post("/api/matches")
def create_match(body: dict = Body(...)):
    conn = get_db()
    home_id = body.get("home_team_id")
    if not one(conn, "SELECT id FROM teams WHERE id=? AND deleted=0", (home_id,)):
        conn.close()
        return err("HOMEチームを選んでください")
    away_id = body.get("away_team_id") or None
    away_name = (body.get("away_name") or "").strip()
    if not away_id and not away_name:
        conn.close()
        return err("AWAYチーム名を入力するか、登録済みチームを選んでください")
    cur = conn.execute(
        "INSERT INTO matches(section,match_date,home_team_id,away_team_id,away_name,"
        "away_rating,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (str(body.get("section") or ""), body.get("match_date") or D.today_str(),
         home_id, away_id, away_name, num(body.get("away_rating")),
         body.get("note", ""), now_str()))
    mid = cur.lastrowid
    for g in G.template():
        conn.execute(
            "INSERT INTO games(match_id,game_no,name,kind,mode,rounds,coins,lottery)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (mid, g["game_no"], g["name"], g["kind"], g["mode"], g["rounds"], g["coins"],
             g.get("lottery", 0)))
    conn.commit()
    conn.close()
    return get_match(mid)


@app.put("/api/matches/{match_id}")
def update_match(match_id: int, body: dict = Body(...)):
    conn = get_db()
    m = one(conn, "SELECT * FROM matches WHERE id=? AND deleted=0", (match_id,))
    if not m:
        conn.close()
        return err("対戦が見つかりません", 404)
    keys = ("section", "match_date", "away_name", "note", "home_sign", "away_sign")
    vals = {k: (body[k] if k in body else m[k]) for k in keys}
    away_rating = num(body.get("away_rating")) if "away_rating" in body else m["away_rating"]
    away_team_id = body.get("away_team_id", m["away_team_id"]) or None
    conn.execute(
        "UPDATE matches SET section=?, match_date=?, away_name=?, note=?, home_sign=?,"
        " away_sign=?, away_rating=?, away_team_id=? WHERE id=?",
        (str(vals["section"] or ""), vals["match_date"], vals["away_name"], vals["note"],
         vals["home_sign"], vals["away_sign"], away_rating, away_team_id, match_id))
    conn.commit()
    conn.close()
    return get_match(match_id)


@app.delete("/api/matches/{match_id}")
def delete_match(match_id: int):
    conn = get_db()
    conn.execute("UPDATE matches SET deleted=1 WHERE id=?", (match_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def roster(conn, match_id: int, side: str) -> list[dict]:
    """その節に出る（＝スコアシートの①〜⑩に書いた）選手。

    ①がいちばんレーティングの高い人になるように並べ替えて返す。
    あとからレーティングを直しても、並びは自動で付け直される。
    """
    ps = rows(conn,
              "SELECT e.slot, p.* FROM entries e JOIN players p ON p.id=e.player_id"
              " WHERE e.match_id=? AND e.side=? ORDER BY e.slot", (match_id, side))
    ordered = by_rating([player_view(p) for p in ps])
    return [{**p, "slot": i + 1} for i, p in enumerate(ordered)]


def fallback_roster(conn, match_id: int, side: str, m: dict) -> list[dict]:
    """メンバー未入力のときは、そのチームの登録選手全員を想定に使う。"""
    got = roster(conn, match_id, side)
    if got:
        return got
    team_id = m["home_team_id"] if side == "home" else m["away_team_id"]
    if not team_id:
        return []
    ps = rows(conn, "SELECT * FROM players WHERE team_id=? AND deleted=0 AND active=1", (team_id,))
    return [player_view(p) for p in ps]


def game_rows(conn, match_id: int) -> list[dict]:
    gs = rows(conn, "SELECT * FROM games WHERE match_id=? ORDER BY game_no", (match_id,))
    gp = rows(conn,
              "SELECT gp.game_id, gp.side, gp.player_id, gp.locked, p.* FROM game_players gp"
              " JOIN players p ON p.id=gp.player_id"
              " JOIN games g ON g.id=gp.game_id WHERE g.match_id=?", (match_id,))
    for g in gs:
        g["size"] = G.size_of(g["mode"])
        g["alt_mode"] = G.alt_mode_of(g["game_no"])
        for side in SIDES:
            mine = [{**player_view(x), "player_id": x["player_id"], "locked": x["locked"]}
                    for x in gp if x["game_id"] == g["id"] and x["side"] == side]
            g[side] = [{"player_id": x["player_id"], "name": x["name"], "rating": x["rating"],
                        "locked": x["locked"], "order": i + 1}
                       for i, x in enumerate(by_rating(mine))]
    return gs


def skill_for(p: dict, kind: str) -> float:
    return p["skill_cricket"] if kind == "cricket" else p["skill_01"]


def opponent_strength(conn, m: dict, g: dict, side: str) -> float:
    """相手チームのそのゲームでの想定チーム力(Rt単位)。

    1) 相手のオーダーが決まっていればその人たちの実力
    2) 決まっていなければ、相手の参加メンバーから size 人が出ると想定した期待値
    3) 相手が未登録なら「相手の想定レーティング」（既定 Rt8）
    """
    other = "away" if side == "home" else "home"
    kind, size = g["kind"], G.size_of(g["mode"])
    named = [x["player_id"] for x in g[other]]
    if named:
        conn_players = rows(conn, "SELECT * FROM players WHERE id IN (%s)"
                            % ",".join("?" * len(named)), named)
        skills = [skill_for(player_view(p), kind) for p in conn_players]
        if skills:
            return R.team_strength(skills)
    pool = fallback_roster(conn, m["id"], other, m)
    if pool:
        return expected_opponent_strength([skill_for(p, kind) for p in pool], size)
    flat = m["away_rating"] if other == "away" else None
    return float(flat) if flat else R.DEFAULT_RATING


def forecast(conn, m: dict, gs: list[dict], side: str = "home") -> dict:
    """今のオーダーでの勝率予測。決着済みの試合は実際の結果を使う。"""
    probs, per_game = [], []
    for g in gs:
        ours = [x["player_id"] for x in g[side]]
        settled = g["winner"] in SIDES
        if settled:
            p = 1.0 if g["winner"] == side else 0.0
        elif ours:
            conn_players = rows(conn, "SELECT * FROM players WHERE id IN (%s)"
                                % ",".join("?" * len(ours)), ours)
            our_s = R.team_strength([skill_for(player_view(x), g["kind"]) for x in conn_players])
            p = R.win_prob(our_s, opponent_strength(conn, m, g, side),
                           g["kind"], g["mode"], g["rounds"])
        else:
            p = 0.5
        probs.append(p)
        per_game.append({"game_no": g["game_no"], "win_prob": round(p, 3),
                         "settled": settled, "assigned": bool(ours),
                         "tag": "結果" if settled else tag_of(p)})
    ep = R.expected_points(probs)
    return {"side": side, "games": per_game,
            "expected_wins": round(ep["expected_wins"], 2),
            "match_win_prob": round(ep["match_win_prob"], 3),
            "expected_points": round(ep["expected_points"], 2)}


def totals(gs: list[dict]) -> dict:
    home = sum(1 for g in gs if g["winner"] == "home")
    away = sum(1 for g in gs if g["winner"] == "away")
    hb = R.BONUS_POINT if home > away else 0
    ab = R.BONUS_POINT if away > home else 0
    return {"home_wins": home, "away_wins": away, "home_bonus": hb, "away_bonus": ab,
            "home_points": home + hb, "away_points": away + ab,
            "played": home + away, "games": len(gs)}


@app.get("/api/matches/{match_id}")
def get_match(match_id: int):
    conn = get_db()
    m = one(conn, "SELECT * FROM matches WHERE id=? AND deleted=0", (match_id,))
    if not m:
        conn.close()
        return err("対戦が見つかりません", 404)
    gs = game_rows(conn, match_id)
    out = {
        "match": {**m, "home_team_name": team_name(conn, m["home_team_id"]),
                  "away_team_name": away_label(conn, m)},
        "home_roster": roster(conn, match_id, "home"),
        "away_roster": roster(conn, match_id, "away"),
        "games": gs,
        "totals": totals(gs),
        "forecast": forecast(conn, m, gs, "home"),
    }
    conn.close()
    return out


@app.put("/api/matches/{match_id}/entries")
def set_entries(match_id: int, body: dict = Body(...)):
    """スコアシート①〜⑩の参加メンバーを登録する。"""
    side = check_side(body.get("side", ""))
    ids = [int(x) for x in (body.get("player_ids") or [])]
    if len(set(ids)) != len(ids):
        return err("同じ選手が2回入っています")
    if len(ids) > 10:
        return err("参加メンバーは10人までです")
    conn = get_db()
    m = one(conn, "SELECT * FROM matches WHERE id=? AND deleted=0", (match_id,))
    if not m:
        conn.close()
        return err("対戦が見つかりません", 404)
    team_id = m["home_team_id"] if side == "home" else m["away_team_id"]
    if not team_id and ids:
        conn.close()
        return err("相手チームが未登録です。チームを登録するか、想定レーティングで計算してください")
    if team_id:
        valid = {p["id"] for p in rows(
            conn, "SELECT id FROM players WHERE team_id=? AND deleted=0", (team_id,))}
        bad = [i for i in ids if i not in valid]
        if bad:
            conn.close()
            return err("そのチームに登録されていない選手が含まれています")
    if ids:  # ①から順にレーティングの高い人が入るようにする
        ps = rows(conn, "SELECT * FROM players WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
        ids = [p["id"] for p in by_rating([player_view(p) for p in ps])]
    conn.execute("DELETE FROM entries WHERE match_id=? AND side=?", (match_id, side))
    for slot, pid in enumerate(ids, start=1):
        conn.execute("INSERT INTO entries(match_id,side,slot,player_id) VALUES(?,?,?,?)",
                     (match_id, side, slot, pid))
    # 参加から外れた選手は、組んであるオーダーからも外す
    sql = ("DELETE FROM game_players WHERE side=? AND game_id IN"
           " (SELECT id FROM games WHERE match_id=?)")
    args = [side, match_id]
    if ids:
        sql += " AND player_id NOT IN (%s)" % ",".join("?" * len(ids))
        args += ids
    conn.execute(sql, args)
    conn.commit()
    conn.close()
    return get_match(match_id)


@app.put("/api/matches/{match_id}/games/{game_no}")
def update_game(match_id: int, game_no: int, body: dict = Body(...)):
    """1試合分の編集（人数モード・出場者・勝敗・固定）。"""
    conn = get_db()
    g = one(conn, "SELECT * FROM games WHERE match_id=? AND game_no=?", (match_id, game_no))
    if not g:
        conn.close()
        return err("試合が見つかりません", 404)
    mode = body.get("mode", g["mode"])
    if mode not in G.MODE_SIZE:
        conn.close()
        return err("人数モードが正しくありません")
    winner = body.get("winner", g["winner"])
    if winner not in ("", "home", "away"):
        conn.close()
        return err("勝敗は 未入力 / home / away です")
    fixed = int(bool(body.get("fixed", g["fixed"])))
    conn.execute("UPDATE games SET mode=?, winner=?, fixed=?, note=? WHERE id=?",
                 (mode, winner, fixed, body.get("note", g["note"]), g["id"]))
    size = G.size_of(mode)
    for side in SIDES:
        key = f"{side}_players"
        if key not in body:
            continue
        ids = [int(x) for x in (body[key] or [])]
        if len(set(ids)) != len(ids):
            conn.close()
            return err("同じ選手を2回選べません")
        if len(ids) > size:
            conn.close()
            return err(f"この試合は{size}人までです")
        entered = {e["player_id"] for e in rows(
            conn, "SELECT player_id FROM entries WHERE match_id=? AND side=?", (match_id, side))}
        if entered and [i for i in ids if i not in entered]:
            conn.close()
            return err("参加メンバーに入っていない選手は出せません")
        locked = set(int(x) for x in (body.get(f"{side}_locked") or []))
        conn.execute("DELETE FROM game_players WHERE game_id=? AND side=?", (g["id"], side))
        for pid in ids:
            conn.execute(
                "INSERT INTO game_players(game_id,side,player_id,locked) VALUES(?,?,?,?)",
                (g["id"], side, pid, 1 if pid in locked else 0))
    conn.commit()
    conn.close()
    return get_match(match_id)


# ---------------------------------------------------------------- 自動振り分け
@app.post("/api/matches/{match_id}/auto")
def auto_assign(match_id: int, body: dict = Body(default={})):
    """参加メンバーを13試合へ自動で振り分ける。

    apply=false なら結果を返すだけ（プレビュー）。true で実際に保存する。
    """
    side = check_side(body.get("side", "home"))
    conn = get_db()
    m = one(conn, "SELECT * FROM matches WHERE id=? AND deleted=0", (match_id,))
    if not m:
        conn.close()
        return err("対戦が見つかりません", 404)
    members = roster(conn, match_id, side)
    if not members:
        conn.close()
        return err("先に参加メンバーを選んでください")
    gs = game_rows(conn, match_id)
    players = [{"id": p["id"], "name": p["name"],
                "skills": {"01": p["skill_01"], "01f": p["skill_01"],
                           "cricket": p["skill_cricket"]}} for p in members]
    member_ids = {p["id"] for p in members}

    specs = []
    for g in gs:
        current = [x for x in g[side] if x["player_id"] in member_ids]
        settled = bool(g["winner"]) or bool(g["fixed"])
        locked = [x["player_id"] for x in current if x["locked"] or settled]
        specs.append({
            "game_no": g["game_no"], "kind": g["kind"], "mode": g["mode"],
            "size": G.size_of(g["mode"]), "rounds": g["rounds"],
            "lottery": g["lottery"], "fixed": settled and len(current) == G.size_of(g["mode"]),
            "locked": locked[:G.size_of(g["mode"])],
            "opp_strength": opponent_strength(conn, m, g, side),
        })
    try:
        solver = Assigner(
            specs, players,
            min_games=body.get("min_games"), max_games=body.get("max_games"),
            objective=body.get("objective", "points"),
            avoid_consecutive=bool(body.get("avoid_consecutive", True)),
            seed=body.get("seed"))
        result = solver.solve(iterations=int(body.get("iterations", 6000)),
                              restarts=int(body.get("restarts", 3)))
    except ValueError as e:
        conn.close()
        return err(str(e))

    names = {p["id"]: p["name"] for p in members}
    rt = {p["id"]: p["rating"] for p in members}
    order_key = (lambda pid: (-rt.get(pid, 0), names.get(pid, "")))
    for row in result["games"]:  # 投げる順＝レーティングの高い順
        row["player_ids"] = sorted(row["player_ids"], key=order_key)
        row["players"] = [{"player_id": pid, "name": names.get(pid, ""),
                           "rating": rt.get(pid), "order": i + 1}
                          for i, pid in enumerate(row["player_ids"])]
    result["counts"] = [{"player_id": pid, "name": names.get(pid, ""), "games": c,
                         "rating": rt.get(pid)}
                        for pid, c in sorted(result["counts"].items(),
                                             key=lambda kv: (-kv[1], order_key(kv[0])))]

    if body.get("apply"):
        for row in result["games"]:
            g = next(x for x in gs if x["game_no"] == row["game_no"])
            keep = {x["player_id"] for x in g[side] if x["locked"]}
            conn.execute("DELETE FROM game_players WHERE game_id=? AND side=?", (g["id"], side))
            for pid in row["player_ids"]:
                conn.execute(
                    "INSERT INTO game_players(game_id,side,player_id,locked) VALUES(?,?,?,?)",
                    (g["id"], side, pid, 1 if pid in keep else 0))
        conn.commit()
    conn.close()
    out = {"result": result, "applied": bool(body.get("apply"))}
    if body.get("apply"):
        out["match"] = get_match(match_id)
    return out


@app.get("/api/matches/{match_id}/forecast")
def get_forecast(match_id: int, side: str = "home"):
    check_side(side)
    conn = get_db()
    m = one(conn, "SELECT * FROM matches WHERE id=? AND deleted=0", (match_id,))
    if not m:
        conn.close()
        return err("対戦が見つかりません", 404)
    out = forecast(conn, m, game_rows(conn, match_id), side)
    conn.close()
    return out


# ---------------------------------------------------------------- 成績
@app.get("/api/standings")
def standings():
    """チームの勝ち点と、選手ごとの出場・勝敗成績。"""
    conn = get_db()
    teams = {t["id"]: {"team_id": t["id"], "name": t["name"], "matches": 0, "won": 0,
                       "lost": 0, "game_wins": 0, "game_losses": 0, "points": 0}
             for t in rows(conn, "SELECT * FROM teams WHERE deleted=0")}
    players = {p["id"]: {"player_id": p["id"], "team_id": p["team_id"], "name": p["name"],
                         "rating": player_view(p)["rating"], "games": 0, "wins": 0, "losses": 0}
               for p in rows(conn, "SELECT * FROM players WHERE deleted=0")}
    for m in rows(conn, "SELECT * FROM matches WHERE deleted=0"):
        gs = game_rows(conn, m["id"])
        t = totals(gs)
        if not t["played"]:
            continue
        sides = {"home": m["home_team_id"], "away": m["away_team_id"]}
        for side, tid in sides.items():
            if tid in teams:
                row = teams[tid]
                row["matches"] += 1
                row["game_wins"] += t[f"{side}_wins"]
                row["game_losses"] += t["away_wins" if side == "home" else "home_wins"]
                row["points"] += t[f"{side}_points"]
                won = t["home_wins"] > t["away_wins"] if side == "home" \
                    else t["away_wins"] > t["home_wins"]
                row["won" if won else "lost"] += 1
        for g in gs:
            if g["winner"] not in SIDES:
                continue
            for side in SIDES:
                for x in g[side]:
                    p = players.get(x["player_id"])
                    if not p:
                        continue
                    p["games"] += 1
                    p["wins" if g["winner"] == side else "losses"] += 1
    conn.close()
    for p in players.values():
        p["win_rate"] = round(p["wins"] / p["games"], 3) if p["games"] else None
    return {
        "teams": sorted(teams.values(), key=lambda r: (-r["points"], -r["game_wins"], r["name"])),
        "players": sorted(players.values(),
                          key=lambda r: (-(r["win_rate"] or 0), -r["games"], r["name"])),
    }


@app.get("/api/matches/{match_id}/csv")
def match_csv(match_id: int):
    """スコアシートをCSVで書き出す（集計や提出用）。"""
    data = get_match(match_id)
    if isinstance(data, JSONResponse):
        return data
    m, gs = data["match"], data["games"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["節", m["section"], "日付", m["match_date"]])
    w.writerow(["HOME", m["home_team_name"], "AWAY", m["away_team_name"]])
    w.writerow([])
    w.writerow(["No", "GAME", "人数", "R", "コイン", "HOME出場(投げる順)",
                "AWAY出場(投げる順)", "勝敗"])
    for g in gs:
        w.writerow([g["game_no"], g["name"], g["mode"], f'{g["rounds"]}R', g["coins"],
                    "→".join(x["name"] for x in g["home"]),  # 投げる順
                    "→".join(x["name"] for x in g["away"]),
                    {"home": "HOME", "away": "AWAY"}.get(g["winner"], "")])
    t = data["totals"]
    w.writerow([])
    w.writerow(["獲得ポイント", t["home_wins"], t["away_wins"]])
    w.writerow([f'勝利ポイント({R.BONUS_POINT}P加算)', t["home_bonus"], t["away_bonus"]])
    w.writerow(["合計ポイント", t["home_points"], t["away_points"]])
    name = f"kileague_{m['match_date']}_{match_id}.csv"
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---------------------------------------------------------------- 画面
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
