import pytest
from fastapi.testclient import TestClient

from backend import db as D
from backend.main import app


@pytest.fixture()
def client():
    conn = D.get_db()  # テストごとにまっさらにする
    for t in ("game_players", "games", "entries", "matches", "players", "teams"):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.close()
    return TestClient(app)


def make_team(client, name, ratings):
    tid = client.post("/api/teams", json={"name": name}).json()["team"]["id"]
    ids = []
    for i, r in enumerate(ratings, start=1):
        res = client.post("/api/players",
                          json={"team_id": tid, "name": f"{name}{i}", "rating": r})
        ids.append(res.json()["player"]["id"])
    return tid, ids


def make_match(client, players=8):
    home, hids = make_team(client, "ホーム", [8, 9, 10, 11, 12, 13, 9, 10][:players])
    away, aids = make_team(client, "アウェイ", [10] * players)
    mid = client.post("/api/matches", json={
        "home_team_id": home, "away_team_id": away,
        "section": "1", "match_date": "2026-08-19"}).json()["match"]["id"]
    client.put(f"/api/matches/{mid}/entries", json={"side": "home", "player_ids": hids})
    client.put(f"/api/matches/{mid}/entries", json={"side": "away", "player_ids": aids})
    return mid, hids, aids


def test_meta_has_the_13_game_template(client):
    meta = client.get("/api/meta").json()
    assert len(meta["template"]) == 13
    assert meta["mode_size"] == {"S": 1, "D": 2, "T": 3, "G": 4}
    assert meta["template"][5]["name"] == "FREEZE"
    assert meta["total_slots"] == 32


def test_player_rating_is_derived_from_stats(client):
    tid, _ = make_team(client, "A", [])
    p = client.post("/api/players",
                    json={"team_id": tid, "name": "選手", "ppd": 30.5, "mpr": 2.0})
    body = p.json()["player"]
    assert body["skill_01"] == 15.0
    assert body["skill_cricket"] == 7.0
    assert body["rating"] == 11.0


def test_player_name_is_required(client):
    tid, _ = make_team(client, "A", [])
    assert client.post("/api/players", json={"team_id": tid, "name": " "}).status_code == 422


def test_creating_a_match_makes_13_games(client):
    mid, _, _ = make_match(client)
    data = client.get(f"/api/matches/{mid}").json()
    assert len(data["games"]) == 13
    assert data["games"][6]["mode"] == "G" and data["games"][6]["alt_mode"] == "T"
    assert data["totals"]["home_points"] == 0


def test_entries_reject_players_from_another_team(client):
    mid, hids, aids = make_match(client)
    res = client.put(f"/api/matches/{mid}/entries",
                     json={"side": "home", "player_ids": aids[:2]})
    assert res.status_code == 422


def test_auto_assign_fills_every_game(client):
    mid, hids, _ = make_match(client)
    res = client.post(f"/api/matches/{mid}/auto",
                      json={"side": "home", "apply": True, "seed": 1}).json()
    assert res["applied"]
    sizes = {"S": 1, "D": 2, "T": 3, "G": 4}
    for g in res["match"]["games"]:
        assert len(g["home"]) == sizes[g["mode"]]
    total = sum(c["games"] for c in res["result"]["counts"])
    assert total == 32
    assert 0 < res["result"]["match_win_prob"] < 1


def test_auto_assign_preview_does_not_save(client):
    mid, _, _ = make_match(client)
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "seed": 2})
    data = client.get(f"/api/matches/{mid}").json()
    assert all(not g["home"] for g in data["games"])


def test_auto_assign_needs_members(client):
    home, hids = make_team(client, "ホーム", [10, 10, 10, 10])
    mid = client.post("/api/matches", json={
        "home_team_id": home, "away_name": "よそ", "away_rating": 10}).json()["match"]["id"]
    res = client.post(f"/api/matches/{mid}/auto", json={"side": "home"})
    assert res.status_code == 422


def test_locked_player_survives_reassignment(client):
    mid, hids, _ = make_match(client)
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 3})
    client.put(f"/api/matches/{mid}/games/1",
               json={"home_players": [hids[0], hids[1]], "home_locked": [hids[0]]})
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 4})
    data = client.get(f"/api/matches/{mid}").json()
    assert hids[0] in [x["player_id"] for x in data["games"][0]["home"]]


def test_played_game_is_kept_when_reassigning(client):
    mid, hids, _ = make_match(client)
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 5})
    before = client.get(f"/api/matches/{mid}").json()["games"][2]
    ids = [x["player_id"] for x in before["home"]]
    client.put(f"/api/matches/{mid}/games/3", json={"winner": "home"})
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 6})
    after = client.get(f"/api/matches/{mid}").json()["games"][2]
    assert sorted(x["player_id"] for x in after["home"]) == sorted(ids)


def test_game_rejects_too_many_players(client):
    mid, hids, _ = make_match(client)
    res = client.put(f"/api/matches/{mid}/games/1", json={"home_players": hids[:3]})
    assert res.status_code == 422  # ①はダブルス(2人)


def test_mode_change_to_trios_on_game7(client):
    mid, hids, _ = make_match(client)
    res = client.put(f"/api/matches/{mid}/games/7",
                     json={"mode": "T", "home_players": hids[:3]})
    assert res.json()["games"][6]["mode"] == "T"
    assert res.json()["games"][6]["size"] == 3


def test_points_totals_follow_the_sheet(client):
    mid, hids, _ = make_match(client)
    for no in range(1, 8):
        client.put(f"/api/matches/{mid}/games/{no}", json={"winner": "home"})
    for no in range(8, 14):
        client.put(f"/api/matches/{mid}/games/{no}", json={"winner": "away"})
    t = client.get(f"/api/matches/{mid}").json()["totals"]
    assert t["home_wins"] == 7 and t["away_wins"] == 6
    assert t["home_bonus"] == 2 and t["away_bonus"] == 0
    assert t["home_points"] == 9 and t["away_points"] == 6


def test_forecast_uses_results_once_played(client):
    mid, hids, _ = make_match(client)
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 7})
    for no in range(1, 8):
        client.put(f"/api/matches/{mid}/games/{no}", json={"winner": "home"})
    fc = client.get(f"/api/matches/{mid}/forecast").json()
    assert fc["match_win_prob"] == 1.0  # 7勝で節の勝ちが確定
    assert fc["games"][0]["settled"] is True


def test_standings_counts_points_and_player_records(client):
    mid, hids, _ = make_match(client)
    client.post(f"/api/matches/{mid}/auto", json={"side": "home", "apply": True, "seed": 8})
    client.post(f"/api/matches/{mid}/auto", json={"side": "away", "apply": True, "seed": 9})
    for no in range(1, 10):
        client.put(f"/api/matches/{mid}/games/{no}", json={"winner": "home"})
    st = client.get("/api/standings").json()
    top = st["teams"][0]
    assert top["name"] == "ホーム" and top["points"] == 11  # 9勝 + 勝利2P
    played = [p for p in st["players"] if p["games"]]
    assert played and all(p["wins"] + p["losses"] == p["games"] for p in played)


def test_csv_export(client):
    mid, _, _ = make_match(client)
    res = client.get(f"/api/matches/{mid}/csv")
    assert res.status_code == 200
    text = res.content.decode("utf-8-sig")
    assert "合計ポイント" in text and "FREEZE" in text


def test_unknown_opponent_uses_estimated_rating(client):
    home, hids = make_team(client, "ホーム", [12] * 6)
    mid = client.post("/api/matches", json={
        "home_team_id": home, "away_name": "初対戦チーム", "away_rating": 8}).json()["match"]["id"]
    client.put(f"/api/matches/{mid}/entries", json={"side": "home", "player_ids": hids})
    res = client.post(f"/api/matches/{mid}/auto", json={"side": "home", "seed": 10}).json()
    assert res["result"]["match_win_prob"] > 0.8  # 格下相手なら勝ち濃厚
    assert all(g["opp_strength"] == 8.0 for g in res["result"]["games"])


def test_match_not_found(client):
    assert client.get("/api/matches/9999").status_code == 404


def test_entries_need_a_registered_opponent_team(client):
    home, hids = make_team(client, "ホーム", [10, 10])
    mid = client.post("/api/matches", json={
        "home_team_id": home, "away_name": "未登録"}).json()["match"]["id"]
    res = client.put(f"/api/matches/{mid}/entries",
                     json={"side": "away", "player_ids": hids})
    assert res.status_code == 422


def test_players_are_listed_by_rating(client):
    tid, _ = make_team(client, "A", [9, 14, 11])
    names = [p["name"] for p in client.get(f"/api/teams/{tid}/players").json()["players"]]
    assert names == ["A2", "A3", "A1"]  # Rt 14 → 11 → 9


def test_entries_are_numbered_by_rating(client):
    mid, hids, _ = make_match(client)
    client.put(f"/api/matches/{mid}/entries",
               json={"side": "home", "player_ids": list(reversed(hids))})
    roster = client.get(f"/api/matches/{mid}").json()["home_roster"]
    assert [p["slot"] for p in roster] == list(range(1, len(roster) + 1))
    assert [p["rating"] for p in roster] == sorted((p["rating"] for p in roster), reverse=True)
    assert roster[0]["name"] == "ホーム6"  # Rt13 がいちばん上


def test_game_players_are_in_throwing_order(client):
    mid, hids, _ = make_match(client)
    res = client.post(f"/api/matches/{mid}/auto",
                      json={"side": "home", "apply": True, "seed": 11}).json()
    for g in res["match"]["games"]:
        for side in ("home", "away"):
            assert [x["order"] for x in g[side]] == list(range(1, len(g[side]) + 1))
            rts = [x["rating"] for x in g[side]]
            assert rts == sorted(rts, reverse=True)
    for row in res["result"]["games"]:  # プレビューの並びも同じ
        assert [p["order"] for p in row["players"]] == list(range(1, len(row["players"]) + 1))


def test_order_follows_a_rating_change(client):
    mid, hids, _ = make_match(client)
    before = client.get(f"/api/matches/{mid}").json()["home_roster"]
    last = before[-1]
    client.put(f"/api/players/{last['player_id'] if 'player_id' in last else last['id']}",
               json={"rating": 20})
    after = client.get(f"/api/matches/{mid}").json()["home_roster"]
    assert after[0]["name"] == last["name"]
    assert after[0]["slot"] == 1
