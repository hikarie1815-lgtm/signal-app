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
) -> RentalCharge:
    """レンタル1件の料金と月別内訳を計算する。すべて整数円。"""
    if qty < 1:
        raise ValueError("数量は1以上で入力してください")
    days = inclusive_days(start, end)
    rental = rental_portion(daily_rate, monthly_rate, days) * qty
    basic = basic_fee * qty  # 契約初日の1回のみ
    support = support_per_day * days * qty
    damage = damage_per_day * days * qty
    warning = f"レンタル期間が{days}日です。最大3か月程度を超えています。" if days > WARN_DAYS else None

    spans = _month_spans(start, end)
    lines: list[MonthlyLine] = []
    allocated_rental = 0
    for i, (y, m, d) in enumerate(spans):
        if i == len(spans) - 1:
            month_rental = rental - allocated_rental  # 丸め差分は最終月へ
        else:
            month_rental = rental * d // days
            allocated_rental += month_rental
        lines.append(MonthlyLine(
            year=y, month=m, days=d,
            rental=month_rental,
            basic=basic if i == 0 else 0,  # 基本料は開始月のみ
            support=support_per_day * d * qty,
            damage=damage_per_day * d * qty,
        ))
    return RentalCharge(days=days, rental=rental, basic=basic,
                        support=support, damage=damage,
                        warning=warning, monthly=lines)
