"""料金計算モジュール（独立・純粋関数のみ）

ルール:
- 日数 = 返却日 - 開始日 + 1（開始日と返却日の両方を含む）
- 30日を1ブロックとして、ブロック内 1〜9日は日割単価×日数、10日以上は月極料金
- 基本料は契約初日の1回のみ（開始月に計上）
- サポート料/日・賠償対策費/日は全日数について毎日発生
- すべて整数の円で計算する
- 月をまたぐ場合は暦月ごとの内訳を作成（丸め差分は最終月に寄せ、合計を一致させる）
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

BLOCK_DAYS = 30          # 月極1ブロックの日数
DAILY_MAX_DAYS = 9       # この日数まで日割、超えたら月極
WARN_DAYS = 90           # 最大3か月程度 — 超過は警告


@dataclass
class MonthlyLine:
    year: int
    month: int
    days: int
    rental: int
    basic: int
    support: int
    damage: int

    @property
    def subtotal(self) -> int:
        return self.rental + self.basic + self.support + self.damage

    def to_dict(self) -> dict:
        return {
            "year": self.year, "month": self.month, "days": self.days,
            "rental": self.rental, "basic": self.basic,
            "support": self.support, "damage": self.damage,
            "subtotal": self.subtotal,
        }


@dataclass
class RentalCharge:
    days: int
    rental: int
    basic: int
    support: int
    damage: int
    warning: str | None = None
    monthly: list[MonthlyLine] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.rental + self.basic + self.support + self.damage

    def to_dict(self) -> dict:
        return {
            "days": self.days, "rental": self.rental, "basic": self.basic,
            "support": self.support, "damage": self.damage, "total": self.total,
            "warning": self.warning,
            "monthly": [m.to_dict() for m in self.monthly],
        }


def inclusive_days(start: date, end: date) -> int:
    if end < start:
        raise ValueError("返却日は開始日以降の日付にしてください")
    return (end - start).days + 1


def rental_portion(daily_rate: int, monthly_rate: int, days: int) -> int:
    """日割/月極ルールによるレンタル料（数量1あたり・整数円）。"""
    if days < 1:
        raise ValueError("日数は1以上が必要です")
    total = 0
    remaining = days
    while remaining > 0:
        block = min(BLOCK_DAYS, remaining)
        if block <= DAILY_MAX_DAYS:
            total += daily_rate * block
        else:
            total += monthly_rate
        remaining -= block
    return total


def _month_spans(start: date, end: date) -> list[tuple[int, int, int]]:
    """(year, month, その月に含まれる日数) のリスト。"""
    spans: list[tuple[int, int, int]] = []
    cur = start
    while cur <= end:
        last_day = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        seg_end = min(last_day, end)
        spans.append((cur.year, cur.month, (seg_end - cur).days + 1))
        cur = seg_end + timedelta(days=1)
    return spans


def chargeable_dates(start: date, end: date, *, skip_sundays: bool = False,
                     rest_days: set | frozenset | tuple | list = ()) -> list[date]:
    """料金対象日の一覧。日曜休止・個別休止日を除外する（両端含む）。"""
    if end < start:
        raise ValueError("返却日は開始日以降の日付にしてください")
    rest = {str(d) for d in rest_days}
    out = []
    cur = start
    while cur <= end:
        if not (skip_sundays and cur.weekday() == 6) and cur.isoformat() not in rest:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def calc_rental_charge(
    *,
    daily_rate: int,
    monthly_rate: int,
    basic_fee: int,
    support_per_day: int,
    damage_per_day: int,
    qty: int,
    start: date,
    end: date,
    skip_sundays: bool = False,
    rest_days: set | frozenset | tuple | list = (),
) -> RentalCharge:
    """レンタル1件の料金と月別内訳を計算する。すべて整数円。

    skip_sundays / rest_days で休止日を除外できる。休止日は日割・サポート料・
    賠償(環境)対策費の日数に数えず、日割⇔月極の判定（10日以上）も休止を除いた
    日数で行う。基本料は休止に関係なく契約初日の1回のみ。
    """
    if qty < 1:
        raise ValueError("数量は1以上で入力してください")
    span_days = inclusive_days(start, end)
    dates = chargeable_dates(start, end, skip_sundays=skip_sundays, rest_days=rest_days)
    days = len(dates)
    rental = (rental_portion(daily_rate, monthly_rate, days) if days else 0) * qty
    basic = basic_fee * qty  # 契約初日の1回のみ（休止に関係なく発生）
    support = support_per_day * days * qty
    damage = damage_per_day * days * qty
    warning = (f"レンタル期間が{span_days}日です。最大3か月程度を超えています。"
               if span_days > WARN_DAYS else None)

    # 月別内訳（対象日ベース。丸め差分は最終月へ）
    per_month: dict[tuple[int, int], int] = {}
    for d in dates:
        per_month[(d.year, d.month)] = per_month.get((d.year, d.month), 0) + 1
    if not per_month:
        per_month = {(start.year, start.month): 0}
    keys = sorted(per_month)
    start_key = (start.year, start.month)
    lines: list[MonthlyLine] = []
    allocated = 0
    for i, key in enumerate(keys):
        d = per_month[key]
        if i == len(keys) - 1:
            month_rental = rental - allocated
        else:
            month_rental = rental * d // days if days else 0
            allocated += month_rental
        lines.append(MonthlyLine(
            year=key[0], month=key[1], days=d,
            rental=month_rental,
            basic=basic if key == start_key or (start_key not in per_month and i == 0) else 0,
            support=support_per_day * d * qty,
            damage=damage_per_day * d * qty,
        ))
    if start_key not in per_month:  # 開始月が全休止でも基本料は開始月に計上
        lines.insert(0, MonthlyLine(year=start_key[0], month=start_key[1], days=0,
                                    rental=0, basic=basic, support=0, damage=0))
        for ln in lines[1:]:
            ln.basic = 0
    return RentalCharge(days=days, rental=rental, basic=basic,
                        support=support, damage=damage,
                        warning=warning, monthly=lines)
