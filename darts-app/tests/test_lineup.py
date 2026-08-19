import random

from backend import games as G
from backend import rating as R
from backend.lineup import Assigner, expected_opponent_strength, tag_of


def specs(opp=10.0, **over):
    out = []
    for g in G.template():
        out.append({"game_no": g["game_no"], "kind": g["kind"], "mode": g["mode"],
                    "size": G.size_of(g["mode"]), "rounds": g["rounds"],
                    "lottery": g.get("lottery", 0), "opp_strength": opp, **over})
    return out


def players(ratings):
    return [{"id": i + 1, "name": f"P{i + 1}",
             "skills": {"01": r, "01f": r, "cricket": r}} for i, r in enumerate(ratings)]


def solve(ratings, opp=10.0, seed=1, **kw):
    a = Assigner(specs(opp), players(ratings), seed=seed, **kw)
    return a, a.solve(iterations=3000, restarts=2)


def test_every_game_is_filled_exactly():
    _, res = solve([10] * 10)
    assert len(res["games"]) == 13
    for row in res["games"]:
        assert len(row["player_ids"]) == row["size"]
        assert len(set(row["player_ids"])) == row["size"]  # 同じ人が2枠に入らない


def test_appearances_are_balanced():
    _, res = solve([10] * 10)
    counts = list(res["counts"].values())
    assert sum(counts) == G.TOTAL_SLOTS
    assert min(counts) >= res["min_games"]
    assert max(counts) <= res["max_games"]
    assert max(counts) - min(counts) <= 1  # 32枠を10人 → 3〜4試合ずつ


def test_min_size_team_still_works():
    # 4人ぴったり（⑦⑧が4人制）でも組める
    _, res = solve([9, 10, 11, 12])
    for row in res["games"]:
        assert len(row["player_ids"]) == row["size"]


def test_locked_player_stays_in_that_game():
    sp = specs()
    sp[2]["locked"] = [5]  # ③901トリオスに選手5を固定
    a = Assigner(sp, players([10] * 8), seed=3)
    res = a.solve(iterations=800, restarts=1)
    assert 5 in res["games"][2]["player_ids"]


def test_fixed_game_is_not_touched():
    sp = specs()
    sp[0]["fixed"] = True
    sp[0]["locked"] = [1, 2]
    a = Assigner(sp, players([6, 7, 12, 13, 14, 15]), seed=5)
    res = a.solve(iterations=800, restarts=1)
    assert sorted(res["games"][0]["player_ids"]) == [1, 2]


def test_specialists_are_used_where_they_are_strong():
    # 選手1はクリケット専門、選手2はゼロワン専門。得意な種目に多く出るはず。
    ps = players([10] * 6)
    ps[0]["skills"] = {"01": 6.0, "01f": 6.0, "cricket": 16.0}
    ps[1]["skills"] = {"01": 16.0, "01f": 16.0, "cricket": 6.0}
    a = Assigner(specs(opp=10.0), ps, seed=7)
    res = a.solve(iterations=4000, restarts=2)
    kind = {g["game_no"]: g["kind"] for g in G.template()}
    cr1 = sum(1 for r in res["games"] if 1 in r["player_ids"] and kind[r["game_no"]] == "cricket")
    o1 = sum(1 for r in res["games"] if 1 in r["player_ids"] and kind[r["game_no"]] != "cricket")
    cr2 = sum(1 for r in res["games"] if 2 in r["player_ids"] and kind[r["game_no"]] == "cricket")
    o2 = sum(1 for r in res["games"] if 2 in r["player_ids"] and kind[r["game_no"]] != "cricket")
    assert cr1 > o1
    assert o2 > cr2


def beats_random(ratings, opp, objective, seed=11):
    """最適化した並びが、適当に組んだ並びより良いことを確かめる。"""
    a, res = solve(ratings, opp=opp, seed=seed, objective=objective)
    rng = random.Random(seed)
    baseline = []
    for _ in range(30):
        plan = a._initial()
        rng.shuffle(a.ids)
        baseline.append(a.score(plan))
    return res, a, baseline


def test_optimizer_beats_random_order_when_outmatched():
    # 格上相手（Rt13）に Rt8〜11 のチームで挑む
    res, a, baseline = beats_random([8, 9, 9, 10, 10, 11], 13.0, "points")
    assert res["expected_points"] > max(baseline)


def test_optimizer_beats_random_order_when_favored():
    res, a, baseline = beats_random([11, 12, 12, 13, 13, 14], 9.0, "points")
    assert res["expected_points"] > max(baseline)


def test_underdog_concentrates_and_favorite_spreads():
    # 格上相手には「勝てる試合」に上手い人を集め、残りは捨てる（勝率の差が大きい）。
    # 格下相手にはどの試合も五分を切らないように散らす。
    _, under = solve([8, 9, 9, 10, 10, 11], opp=13.5, seed=21)
    _, over = solve([11, 12, 12, 13, 13, 14], opp=9.0, seed=21)
    u = [r["win_prob"] for r in under["games"]]
    o = [r["win_prob"] for r in over["games"]]
    assert max(u) / min(u) > 2.0  # 狙う試合と捨てる試合がはっきり分かれる
    assert max(o) / min(o) < 1.5  # 格下相手は均す
    assert min(o) > 0.5


def test_objective_matchwin_maximizes_match_win_prob():
    # 目的を「節に勝つ確率」にすると、その確率が実際に高くなる
    def avg(objective):
        vals = []
        for seed in range(8):
            _, res = solve([8, 9, 9, 10, 10, 11], opp=10.5, seed=seed,
                           objective=objective)
            vals.append(res["match_win_prob"])
        return sum(vals) / len(vals)

    assert avg("matchwin") > avg("wins")


def test_consecutive_games_are_avoided():
    on = Assigner(specs(), players([10] * 10), seed=41, avoid_consecutive=True)
    off = Assigner(specs(), players([10] * 10), seed=41, avoid_consecutive=False)
    r_on = on.solve(iterations=3000, restarts=1)
    r_off = off.solve(iterations=3000, restarts=1)
    plan_on = {g["game_no"]: g["player_ids"] for g in r_on["games"]}
    plan_off = {g["game_no"]: g["player_ids"] for g in r_off["games"]}
    assert on._consecutive(plan_on) <= off._consecutive(plan_off)


def test_expected_opponent_strength_between_mean_and_max():
    skills = [6, 8, 10, 12, 14]
    est = expected_opponent_strength(skills, 2)
    assert 10.0 < est < 14.0
    assert expected_opponent_strength([9.0], 4) == 9.0


def test_infeasible_limits_are_relaxed_with_warning():
    a = Assigner(specs(), players([10] * 6), max_games=2)  # 6人×2=12枠 < 32枠
    res = a.solve(iterations=300, restarts=1)
    assert res["warnings"]
    assert res["max_games"] > 2
    for row in res["games"]:
        assert len(row["player_ids"]) == row["size"]


def test_no_players_is_rejected():
    try:
        Assigner(specs(), [])
        assert False, "例外になるはず"
    except ValueError:
        pass


def test_tag_labels():
    assert tag_of(0.9) == "勝ち計算"
    assert tag_of(0.5) == "五分"
    assert tag_of(0.1) == "捨て試合"


def test_lottery_games_are_random_not_optimized():
    # くじの試合(⑤⑩)は実力ではなく運で決まるので、上手い人が固定されない
    picks = set()
    for seed in range(12):
        _, res = solve([6, 7, 8, 13, 14, 15], opp=10.0, seed=seed)
        picks.add(res["games"][4]["player_ids"][0])
    assert len(picks) >= 3
