"""参加メンバーを13試合へ自動で振り分ける（オーダー自動編成）。

やっていること
--------------
* 各試合の必要人数（S=1 / D=2 / T=3 / G=4）をぴったり埋める。
* 出場数が偏らないように、1人あたりの出場試合数に上限・下限を付ける。
* 「くじ」の試合はランダムに選ぶ（実際にくじで決めるため）。
* 固定(ロック)した選手はそのまま動かさない。
* そのうえで、目的（合計ポイントの期待値など）が最大になる組み合わせを
  焼きなまし法(simulated annealing)で探す。

「勝てる試合か」を加味するのはこの目的関数のところ。
節の勝敗は13試合の勝ち星で決まるので、目的を「合計ポイント期待値」
（= 勝ち星の期待値 + 2P × 節に勝つ確率）にすると、
  ・格上相手 → 勝てる試合に上手い人を集め、勝てない試合は捨てる
  ・格下相手 → どの試合も5割を切らないように散らす
という配分が自然に出てくる。
"""
from __future__ import annotations

import math
import random

from .rating import (BONUS_POINT, expected_points, team_strength, win_prob)

OBJECTIVES = {
    "points": "合計ポイントの期待値（おすすめ）",
    "wins": "勝ち星の期待値",
    "matchwin": "節に勝つ確率",
}
CONSEC_PENALTY = 0.04  # 連投1回あたりの減点（ポイント換算）


def expected_opponent_strength(skills: list[float], size: int) -> float:
    """相手のオーダーが分からないときの、想定チーム力。

    相手も同じメンバーから size 人を出すと考えて、平均とエース補正の
    期待値から求める（誰が出るか分からない＝ランダム抽出とみなす）。
    """
    from .rating import ACE_WEIGHT, DEFAULT_RATING
    if not skills:
        return DEFAULT_RATING
    n = len(skills)
    k = max(1, min(size, n))
    s = sorted(skills)
    avg = sum(s) / n
    total = math.comb(n, k)
    e_max = sum(s[i] * math.comb(i, k - 1) for i in range(k - 1, n)) / total
    return avg + ACE_WEIGHT * (e_max - avg)


class Assigner:
    """1チーム分のオーダーを組み立てる。

    games: [{game_no, kind, mode, size, rounds, lottery, opp_strength, locked:[pid], fixed:bool}]
    players: [{id, skills:{"01":x,"01f":x,"cricket":x}}]
    """

    def __init__(self, games, players, *, min_games=None, max_games=None,
                 objective="points", avoid_consecutive=True, seed=None):
        self.games = games
        self.players = {p["id"]: p for p in players}
        self.ids = [p["id"] for p in players]
        self.objective = objective if objective in OBJECTIVES else "points"
        self.avoid_consecutive = avoid_consecutive
        self.rng = random.Random(seed)
        self.warnings: list[str] = []

        total = sum(g["size"] for g in games)
        n = len(self.ids)
        if n == 0:
            raise ValueError("参加メンバーがいません")
        big = max((g["size"] for g in games), default=1)
        if n < big:
            self.warnings.append(
                f"{big}人必要な試合があるのに参加が{n}人です。人数を増やすか⑦⑧をトリオスにしてください")
        self.min_games = total // n if min_games is None else int(min_games)
        self.max_games = -(-total // n) if max_games is None else int(max_games)
        # 実現できない上限・下限は自動でゆるめる
        if self.max_games * n < total:
            self.max_games = -(-total // n)
            self.warnings.append("出場上限では埋まらないため、上限を自動で広げました")
        if self.min_games * n > total:
            self.min_games = total // n
            self.warnings.append("出場下限が多すぎるため、下限を自動で下げました")
        self.min_games = max(0, min(self.min_games, self.max_games))
        self.max_games = min(self.max_games, len(games))

    # ---------- 目的関数 ----------
    def strength(self, game, pids) -> float:
        kind = game["kind"]
        return team_strength([self.players[p]["skills"][kind] for p in pids if p in self.players])

    def probs(self, plan) -> list[float]:
        out = []
        for g in self.games:
            ours = self.strength(g, plan[g["game_no"]])
            out.append(win_prob(ours, g["opp_strength"], g["kind"], g["mode"], g["rounds"]))
        return out

    def score(self, plan) -> float:
        probs = self.probs(plan)
        ep = expected_points(probs)
        if self.objective == "wins":
            value = ep["expected_wins"]
        elif self.objective == "matchwin":
            value = ep["match_win_prob"] * len(self.games)
        else:
            value = ep["expected_points"]
        if self.avoid_consecutive:
            value -= CONSEC_PENALTY * self._consecutive(plan)
        return value

    def _consecutive(self, plan) -> int:
        """連続する試合番号に続けて出る回数。"""
        order = [g["game_no"] for g in self.games]
        hits = 0
        for a, b in zip(order, order[1:]):
            hits += len(set(plan[a]) & set(plan[b]))
        return hits

    # ---------- 初期配置 ----------
    def _initial(self) -> dict:
        plan, counts = {}, {pid: 0 for pid in self.ids}
        for g in self.games:  # 固定・確定済みの試合を先に反映
            locked = [p for p in g.get("locked", []) if p in self.players]
            plan[g["game_no"]] = list(dict.fromkeys(locked))[:g["size"]]
            for p in plan[g["game_no"]]:
                counts[p] += 1
        order = sorted(self.games, key=lambda g: -g["size"])
        for g in order:
            gno = g["game_no"]
            while len(plan[gno]) < g["size"]:
                pool = [p for p in self.ids if p not in plan[gno]]
                if not pool:
                    break
                room = [p for p in pool if counts[p] < self.max_games]
                pool = room or pool
                least = min(counts[p] for p in pool)
                cand = [p for p in pool if counts[p] == least]
                pick = self.rng.choice(cand)
                plan[gno].append(pick)
                counts[pick] += 1
        return plan

    def _counts(self, plan) -> dict:
        counts = {pid: 0 for pid in self.ids}
        for pids in plan.values():
            for p in pids:
                counts[p] = counts.get(p, 0) + 1
        return counts

    def _movable(self, game) -> bool:
        """自動で入れ替えてよい試合か（くじ・固定済みは動かさない）。"""
        return not game.get("lottery") and not game.get("fixed")

    def _locked_in(self, game) -> set:
        return set(game.get("locked", []))

    # ---------- 探索 ----------
    def solve(self, iterations: int = 6000, restarts: int = 3) -> dict:
        best_plan, best_score = None, -1e9
        for _ in range(max(1, restarts)):
            plan = self._initial()
            plan, sc = self._anneal(plan, iterations)
            if sc > best_score:
                best_plan, best_score = plan, sc
        return self.result(best_plan)

    def _anneal(self, plan, iterations):
        counts = self._counts(plan)
        cur = self.score(plan)
        best, best_plan = cur, {k: list(v) for k, v in plan.items()}
        movable = [g for g in self.games if self._movable(g)]
        if not movable:
            return best_plan, best
        # 目的関数によって値の幅が違う（合計ポイントは十点台、節の勝率は0〜1）ので、
        # 入れ替え1回あたりの変化量から温度を決める。そうしないと、
        # 温度が大きすぎて「ただのランダム探索」になってしまう。
        step = self._calibrate(plan, counts, movable)
        t0, t1 = 2.0 * step, step / 20.0
        for i in range(iterations):
            temp = t0 * (t1 / t0) ** (i / max(1, iterations - 1))
            undo = self._propose(plan, counts, movable)
            if undo is None:
                continue
            new = self.score(plan)
            if new >= cur or self.rng.random() < math.exp((new - cur) / temp):
                cur = new
                if cur > best:
                    best, best_plan = cur, {k: list(v) for k, v in plan.items()}
            else:
                undo()
        return best_plan, best

    def _calibrate(self, plan, counts, movable, samples: int = 40) -> float:
        """入れ替え1回でスコアがどれくらい動くかを測る（温度の目安）。"""
        base = self.score(plan)
        deltas = []
        for _ in range(samples):
            undo = self._propose(plan, counts, movable)
            if undo is None:
                continue
            deltas.append(abs(self.score(plan) - base))
            undo()
        avg = sum(deltas) / len(deltas) if deltas else 0.0
        return max(avg, 1e-6)

    def _propose(self, plan, counts, movable):
        """入れ替えを1つ試す。戻す関数を返す（できなければ None）。"""
        if self.rng.random() < 0.5 or len(movable) < 2:
            return self._swap_bench(plan, counts, movable)
        return self._swap_games(plan, counts, movable)

    def _swap_bench(self, plan, counts, movable):
        """試合に出ている人 ↔ 出ていない人 を入れ替える。"""
        g = self.rng.choice(movable)
        gno = g["game_no"]
        inside = [p for p in plan[gno] if p not in self._locked_in(g)]
        outside = [p for p in self.ids if p not in plan[gno]]
        if not inside or not outside:
            return None
        old = self.rng.choice(inside)
        new = self.rng.choice(outside)
        if counts[old] - 1 < self.min_games or counts[new] + 1 > self.max_games:
            return None
        idx = plan[gno].index(old)
        plan[gno][idx] = new
        counts[old] -= 1
        counts[new] += 1

        def undo():
            plan[gno][idx] = old
            counts[old] += 1
            counts[new] -= 1
        return undo

    def _swap_games(self, plan, counts, movable):
        """別々の試合に出ている2人を交換する（出場数は変わらない）。"""
        g1, g2 = self.rng.sample(movable, 2)
        a, b = g1["game_no"], g2["game_no"]
        cand1 = [p for p in plan[a] if p not in self._locked_in(g1) and p not in plan[b]]
        cand2 = [p for p in plan[b] if p not in self._locked_in(g2) and p not in plan[a]]
        if not cand1 or not cand2:
            return None
        p1, p2 = self.rng.choice(cand1), self.rng.choice(cand2)
        i1, i2 = plan[a].index(p1), plan[b].index(p2)
        plan[a][i1], plan[b][i2] = p2, p1

        def undo():
            plan[a][i1], plan[b][i2] = p1, p2
        return undo

    # ---------- 結果 ----------
    def result(self, plan) -> dict:
        probs = self.probs(plan)
        ep = expected_points(probs)
        counts = self._counts(plan)
        rows = []
        for g, p in zip(self.games, probs):
            pids = plan[g["game_no"]]
            rows.append({
                "game_no": g["game_no"], "mode": g["mode"], "size": g["size"],
                "player_ids": pids,
                "our_strength": round(self.strength(g, pids), 2),
                "opp_strength": round(g["opp_strength"], 2),
                "win_prob": round(p, 3),
                "tag": tag_of(p),
                "lottery": bool(g.get("lottery")),
            })
        return {
            "games": rows,
            "counts": counts,
            "expected_wins": round(ep["expected_wins"], 2),
            "match_win_prob": round(ep["match_win_prob"], 3),
            "expected_points": round(ep["expected_points"], 2),
            "bonus_point": BONUS_POINT,
            "min_games": self.min_games, "max_games": self.max_games,
            "objective": self.objective,
            "warnings": self.warnings,
        }


def tag_of(p: float) -> str:
    if p >= 0.72:
        return "勝ち計算"
    if p >= 0.58:
        return "優位"
    if p >= 0.42:
        return "五分"
    if p >= 0.28:
        return "劣勢"
    return "捨て試合"
