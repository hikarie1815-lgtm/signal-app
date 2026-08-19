"""レーティングと勝率の計算。

考え方
------
1) 選手の実力は「レーティング(Rt)」「PPD(ゼロワンの1本あたり得点)」
   「MPR(クリケットの1ラウンドあたりマーク数)」のどれかで入れてもらう。
   足りない値は下の対応表から補完する（DARTSLIVE のRt表に合わせた目安）。
2) 種目ごとに強さを Rt 単位に直す。ゼロワンは PPD、クリケットは MPR を使う。
   → 「01は強いがクリケットは苦手」といった選手の得手不得手を反映できる。
3) チームの強さ = 平均 + エース補正（上手い人が1人いると多少引き上がる）。
4) 勝率 = ロジスティック関数。試合が長いほど（20R・トリオス以上）実力差が
   出やすく、FREEZE のような運の要素が大きい種目は差が出にくいとして
   「ばらつき(spread)」を種目ごとに変える。
"""
from __future__ import annotations

import math

# Rt1〜18 の下限値（Rt が1つ上がるのに必要な PPD / MPR）。
# 実際のリーグ運用では店の基準に合わせて調整してよい。
PPD_MIN = [0.0, 10.30, 12.20, 14.10, 16.00, 17.45, 18.90, 20.35, 21.80,
           23.25, 24.70, 26.15, 27.60, 29.05, 30.50, 31.95, 33.40, 34.85]
MPR_MIN = [0.0, 1.00, 1.20, 1.40, 1.60, 1.80, 2.00, 2.20, 2.40,
           2.60, 2.80, 3.00, 3.20, 3.40, 3.60, 3.80, 4.00, 4.20]

RT_MIN, RT_MAX = 1.0, 20.0
DEFAULT_RATING = 8.0  # 何も入力が無い選手の仮の実力


def _to_rt(value: float | None, table: list[float]) -> float | None:
    """PPD/MPR を連続値の Rt に直す（Rt表の間は直線で補間）。"""
    if value is None:
        return None
    v = float(value)
    if v <= table[1]:
        return _clamp(1.0 + v / table[1], RT_MIN, RT_MAX)
    for i in range(1, len(table) - 1):
        if v < table[i + 1]:
            width = table[i + 1] - table[i]
            return _clamp(i + 1 + (v - table[i]) / width, RT_MIN, RT_MAX)
    last = table[-1] - table[-2]  # Rt18以上は最後の刻み幅で延長
    return _clamp(len(table) + (v - table[-1]) / last, RT_MIN, RT_MAX)


def _from_rt(rt: float, table: list[float]) -> float:
    """Rt を PPD/MPR に戻す（_to_rt の逆）。Rt n の下限が table[n-1]。"""
    r = _clamp(float(rt), RT_MIN, RT_MAX)
    i = min(max(int(r) - 1, 0), len(table) - 2)  # Rt18以上は最後の刻み幅で延長
    return table[i] + (r - (i + 1)) * (table[i + 1] - table[i])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def rt_from_ppd(ppd: float | None) -> float | None:
    return _to_rt(ppd, PPD_MIN)


def rt_from_mpr(mpr: float | None) -> float | None:
    return _to_rt(mpr, MPR_MIN)


def ppd_from_rt(rt: float) -> float:
    return _from_rt(rt, PPD_MIN)


def mpr_from_rt(rt: float) -> float:
    return _from_rt(rt, MPR_MIN)


def player_skills(rating=None, ppd=None, mpr=None) -> dict:
    """選手1人の「種目ごとの強さ(Rt単位)」を作る。

    入力は Rt だけ / スタッツだけ / 両方 のどれでもよい。
    """
    rt01 = rt_from_ppd(ppd)
    rtcr = rt_from_mpr(mpr)
    base = rating if rating else None
    if base is None:
        known = [x for x in (rt01, rtcr) if x is not None]
        base = sum(known) / len(known) if known else DEFAULT_RATING
    base = _clamp(float(base), RT_MIN, RT_MAX)
    if rt01 is None:
        rt01 = base
    if rtcr is None:
        rtcr = base
    return {"rating": round(base, 2), "01": rt01, "01f": rt01, "cricket": rtcr,
            "ppd": round(ppd if ppd else ppd_from_rt(rt01), 2),
            "mpr": round(mpr if mpr else mpr_from_rt(rtcr), 2)}


ACE_WEIGHT = 0.25  # チーム戦で上手い人が引っ張る度合い


def team_strength(skills: list[float]) -> float:
    """複数人で投げるときのチームの強さ(Rt単位)。

    交互に投げるので基本は平均。ただし上がり(フィニッシュ)を任せられる人が
    いると多少強くなるので、最大値へ少しだけ寄せる。
    """
    if not skills:
        return DEFAULT_RATING
    avg = sum(skills) / len(skills)
    return avg + ACE_WEIGHT * (max(skills) - avg)


# 種目ごとの「ばらつき」。小さいほど実力差がそのまま勝敗になる。
SPREAD_BASE = {"01": 1.55, "01f": 2.10, "cricket": 1.55}
MODE_SPREAD = {"S": 1.05, "D": 1.00, "T": 0.97, "G": 0.95}


def spread(kind: str, mode: str, rounds: int = 15) -> float:
    s = SPREAD_BASE.get(kind, 1.55) * MODE_SPREAD.get(mode, 1.0)
    if rounds and rounds >= 20:
        s *= 0.92  # ラウンドが多いほど運で勝てなくなる
    return s


def win_prob(ours: float, theirs: float, kind: str, mode: str, rounds: int = 15) -> float:
    """自チームの勝率(0〜1)。3〜97%に収める（ダーツに絶対は無いため）。"""
    diff = (ours - theirs) / spread(kind, mode, rounds)
    p = 1.0 / (1.0 + math.exp(-diff))
    return _clamp(p, 0.03, 0.97)


def win_distribution(probs: list[float]) -> list[float]:
    """各試合の勝率から「何勝できるか」の確率分布を作る（ポアソン二項分布）。"""
    dist = [1.0]
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for wins, w in enumerate(dist):
            nxt[wins] += w * (1 - p)
            nxt[wins + 1] += w * p
        dist = nxt
    return dist


def match_win_prob(probs: list[float]) -> float:
    """節(13試合)全体で相手より多く勝てる確率。"""
    n = len(probs)
    if n == 0:
        return 0.0
    dist = win_distribution(probs)
    need = n // 2 + 1
    return sum(dist[need:])


BONUS_POINT = 2  # 勝利ポイント(2P加算)


def expected_points(probs: list[float]) -> dict:
    """獲得ポイント・勝利ポイント・合計ポイントの期待値。"""
    e_wins = sum(probs)
    p_match = match_win_prob(probs)
    return {"expected_wins": e_wins, "match_win_prob": p_match,
            "expected_points": e_wins + BONUS_POINT * p_match}
