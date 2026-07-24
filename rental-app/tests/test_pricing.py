from datetime import date

import pytest

from backend.pricing import calc_rental_charge, inclusive_days, rental_portion


def charge(days_start, days_end, qty=1, daily=1000, monthly=8000,
           basic=500, support=100, damage=50):
    return calc_rental_charge(
        daily_rate=daily, monthly_rate=monthly, basic_fee=basic,
        support_per_day=support, damage_per_day=damage, qty=qty,
        start=days_start, end=days_end)


def test_inclusive_days_both_ends():
    # 開始日と返却日を両方含む
    assert inclusive_days(date(2026, 7, 1), date(2026, 7, 1)) == 1
    assert inclusive_days(date(2026, 7, 1), date(2026, 7, 10)) == 10


def test_end_before_start_rejected():
    with pytest.raises(ValueError):
        inclusive_days(date(2026, 7, 2), date(2026, 7, 1))


def test_one_day_daily_rate():
    c = charge(date(2026, 7, 1), date(2026, 7, 1))
    assert c.rental == 1000
    assert c.basic == 500
    assert c.support == 100
    assert c.damage == 50
    assert c.total == 1650


def test_nine_days_daily_rate():
    c = charge(date(2026, 7, 1), date(2026, 7, 9))
    assert c.days == 9
    assert c.rental == 9000  # 9日×1000


def test_ten_days_switches_to_monthly():
    c = charge(date(2026, 7, 1), date(2026, 7, 10))
    assert c.days == 10
    assert c.rental == 8000  # 月極


def test_thirty_days_one_month():
    c = charge(date(2026, 7, 1), date(2026, 7, 30))
    assert c.rental == 8000


def test_thirty_one_days_month_plus_one_daily():
    c = charge(date(2026, 7, 1), date(2026, 7, 31))
    assert c.days == 31
    assert c.rental == 8000 + 1000  # 月極 + 日割1日


def test_forty_five_days_month_plus_monthly_block():
    # 45日 = 30日ブロック(月極) + 15日ブロック(10日以上→月極)
    c = charge(date(2026, 7, 1), date(2026, 8, 14))
    assert c.days == 45
    assert c.rental == 8000 + 8000


def test_ninety_days_three_months_no_warning():
    c = charge(date(2026, 7, 1), date(2026, 9, 28))
    assert c.days == 90
    assert c.rental == 8000 * 3
    assert c.warning is None


def test_over_ninety_days_warns():
    c = charge(date(2026, 7, 1), date(2026, 9, 29))
    assert c.warning is not None


def test_basic_fee_only_once_in_start_month():
    c = charge(date(2026, 7, 20), date(2026, 9, 5))
    assert c.monthly[0].basic == 500
    assert all(m.basic == 0 for m in c.monthly[1:])
    assert sum(m.basic for m in c.monthly) == 500


def test_support_and_damage_every_day():
    c = charge(date(2026, 7, 25), date(2026, 8, 5))  # 12日
    assert c.support == 100 * 12
    assert c.damage == 50 * 12
    # 月別: 7月は7日分、8月は5日分
    assert c.monthly[0].support == 100 * 7
    assert c.monthly[1].support == 100 * 5


def test_monthly_breakdown_sums_match_total():
    c = charge(date(2026, 6, 15), date(2026, 9, 10), qty=3, daily=1234,
               monthly=9999, basic=777, support=123, damage=45)
    assert sum(m.rental for m in c.monthly) == c.rental
    assert sum(m.subtotal for m in c.monthly) == c.total
    # すべて整数円
    for m in c.monthly:
        for v in (m.rental, m.basic, m.support, m.damage):
            assert isinstance(v, int)


def test_quantity_multiplies():
    c1 = charge(date(2026, 7, 1), date(2026, 7, 5), qty=1)
    c3 = charge(date(2026, 7, 1), date(2026, 7, 5), qty=3)
    assert c3.rental == c1.rental * 3
    assert c3.basic == c1.basic * 3
    assert c3.total == c1.total * 3


def test_qty_zero_rejected():
    with pytest.raises(ValueError):
        charge(date(2026, 7, 1), date(2026, 7, 5), qty=0)


def test_skip_sundays_excludes_charge():
    # 2026-07-01(水)〜07-14(火) の14日間に日曜が2日(7/5,7/12)
    c = charge(date(2026, 7, 1), date(2026, 7, 14))
    assert c.days == 14
    cs = calc_rental_charge(
        daily_rate=1000, monthly_rate=8000, basic_fee=500, support_per_day=100,
        damage_per_day=50, qty=1, start=date(2026, 7, 1), end=date(2026, 7, 14),
        skip_sundays=True)
    assert cs.days == 12  # 日曜2日を除外
    # 12日は10日以上なので月極、サポート・賠償は12日分
    assert cs.rental == 8000
    assert cs.support == 100 * 12
    assert cs.damage == 50 * 12
    assert cs.basic == 500  # 基本料は休止に関係なく1回


def test_rest_days_excluded():
    # 5日間のうち特定の2日を休止
    cs = calc_rental_charge(
        daily_rate=1000, monthly_rate=8000, basic_fee=500, support_per_day=100,
        damage_per_day=50, qty=1, start=date(2026, 7, 1), end=date(2026, 7, 5),
        rest_days=["2026-07-02", "2026-07-03"])
    assert cs.days == 3
    assert cs.rental == 1000 * 3
    assert cs.support == 100 * 3


def test_skip_sundays_month_split_and_basic():
    # 月をまたぎ、日曜を除外しても基本料は開始月のみ・合計一致
    cs = calc_rental_charge(
        daily_rate=1000, monthly_rate=8000, basic_fee=500, support_per_day=100,
        damage_per_day=50, qty=2, start=date(2026, 7, 28), end=date(2026, 8, 9),
        skip_sundays=True)
    assert sum(m.rental for m in cs.monthly) == cs.rental
    assert sum(m.subtotal for m in cs.monthly) == cs.total
    assert sum(m.basic for m in cs.monthly) == cs.basic
    assert cs.monthly[0].basic == 500 * 2 and all(m.basic == 0 for m in cs.monthly[1:])


def test_rental_portion_block_rule():
    assert rental_portion(1000, 8000, 1) == 1000
    assert rental_portion(1000, 8000, 9) == 9000
    assert rental_portion(1000, 8000, 10) == 8000
    assert rental_portion(1000, 8000, 30) == 8000
    assert rental_portion(1000, 8000, 33) == 8000 + 3000
    assert rental_portion(1000, 8000, 60) == 16000
