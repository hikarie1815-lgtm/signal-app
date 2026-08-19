from backend import rating as R


def test_rt_and_stats_round_trip():
    # Rt表の境目はそのままRtの整数になる
    assert R.rt_from_ppd(23.25) == 10.0
    assert R.rt_from_mpr(3.00) == 12.0
    assert abs(R.ppd_from_rt(10.0) - 23.25) < 0.01
    assert abs(R.mpr_from_rt(12.0) - 3.00) < 0.01


def test_rating_is_clamped():
    assert R.rt_from_ppd(0) == 1.0
    assert R.rt_from_ppd(200) == 20.0
    assert R.rt_from_mpr(1.10) > 1.0


def test_skills_filled_from_rating_only():
    s = R.player_skills(rating=10)
    assert s["01"] == 10 and s["cricket"] == 10
    assert abs(s["ppd"] - 23.25) < 0.05


def test_skills_from_stats_only():
    # 01は得意・クリケットは苦手、という差がそのまま出る
    s = R.player_skills(ppd=30.5, mpr=2.0)
    assert s["01"] == 15.0
    assert s["cricket"] == 7.0
    assert s["rating"] == 11.0  # 総合は平均


def test_team_strength_between_avg_and_max():
    st = R.team_strength([8.0, 12.0])
    assert 10.0 < st < 12.0
    assert R.team_strength([9.0]) == 9.0


def test_win_prob_direction_and_bounds():
    assert R.win_prob(12, 8, "01", "D", 15) > 0.8
    assert R.win_prob(8, 12, "01", "D", 15) < 0.2
    assert R.win_prob(10, 10, "01", "D", 15) == 0.5
    assert 0.03 <= R.win_prob(1, 20, "01", "S", 15) <= 0.97


def test_freeze_is_more_luck_than_normal_01():
    # 同じ実力差でも FREEZE は差が付きにくい
    assert R.win_prob(12, 10, "01f", "D", 15) < R.win_prob(12, 10, "01", "D", 15)


def test_20_rounds_favors_the_stronger_team():
    assert R.win_prob(12, 10, "01", "T", 20) > R.win_prob(12, 10, "01", "T", 15)


def test_win_distribution_sums_to_one():
    dist = R.win_distribution([0.5, 0.3, 0.9])
    assert abs(sum(dist) - 1.0) < 1e-9
    assert len(dist) == 4


def test_match_win_prob_needs_majority():
    assert R.match_win_prob([1.0] * 7 + [0.0] * 6) == 1.0
    assert R.match_win_prob([1.0] * 6 + [0.0] * 7) == 0.0
    assert abs(R.match_win_prob([0.5] * 13) - 0.5) < 1e-9


def test_expected_points_includes_bonus():
    ep = R.expected_points([1.0] * 13)
    assert ep["expected_points"] == 13 + R.BONUS_POINT
