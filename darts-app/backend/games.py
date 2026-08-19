"""KI-LEAGUE スコアシートの雛形（13ゲーム）。

紙のスコアシートと同じ並び。S=1人 / D=2人 / T=3人 / G=4人。
⑦⑧は「状況に応じてトリオス(T)にする」ため alt_mode を持つ。
kind は勝率計算に使う種目区分:
  "01"      … 501 / 701 / 901（ゼロワン。PPDで強さを見る）
  "01f"     … FREEZE（ゼロワンだが運の要素が大きい）
  "cricket" … CR / CRくじ（クリケット。MPRで強さを見る）
lottery=1 は「くじ」で出る人を決める試合 → 自動振り分けでもランダムに選ぶ。
"""
from __future__ import annotations

MODE_SIZE = {"S": 1, "D": 2, "T": 3, "G": 4}
MODE_LABEL = {"S": "シングルス(1人)", "D": "ダブルス(2人)", "T": "トリオス(3人)", "G": "4人"}

TEMPLATE = [
    {"game_no": 1, "name": "501", "kind": "01", "mode": "D", "rounds": 15, "coins": 200},
    {"game_no": 2, "name": "CR", "kind": "cricket", "mode": "D", "rounds": 20, "coins": 200},
    {"game_no": 3, "name": "901", "kind": "01", "mode": "T", "rounds": 20, "coins": 200},
    {"game_no": 4, "name": "CR", "kind": "cricket", "mode": "T", "rounds": 20, "coins": 200},
    {"game_no": 5, "name": "501くじ", "kind": "01", "mode": "S", "rounds": 15, "coins": 200,
     "lottery": 1},
    {"game_no": 6, "name": "FREEZE", "kind": "01f", "mode": "D", "rounds": 15, "coins": 400},
    {"game_no": 7, "name": "901", "kind": "01", "mode": "G", "rounds": 20, "coins": 200,
     "alt_mode": "T"},
    {"game_no": 8, "name": "CR", "kind": "cricket", "mode": "G", "rounds": 20, "coins": 200,
     "alt_mode": "T"},
    {"game_no": 9, "name": "701", "kind": "01", "mode": "D", "rounds": 15, "coins": 200},
    {"game_no": 10, "name": "CRくじ", "kind": "cricket", "mode": "S", "rounds": 20, "coins": 200,
     "lottery": 1},
    {"game_no": 11, "name": "501", "kind": "01", "mode": "D", "rounds": 15, "coins": 200},
    {"game_no": 12, "name": "CR", "kind": "cricket", "mode": "T", "rounds": 20, "coins": 200},
    {"game_no": 13, "name": "901", "kind": "01", "mode": "T", "rounds": 20, "coins": 200},
]

# 雛形どおりに全試合を行ったときに必要な「のべ出場人数」
TOTAL_SLOTS = sum(MODE_SIZE[g["mode"]] for g in TEMPLATE)


def template() -> list[dict]:
    """雛形のコピーを返す（呼び出し側で書き換えても元は壊れない）。"""
    return [dict(g) for g in TEMPLATE]


def size_of(mode: str) -> int:
    return MODE_SIZE.get(mode, 1)


def alt_mode_of(game_no: int) -> str:
    """⑦⑧のように人数を変えられる試合の、もう一方のモード。無ければ ''。"""
    for g in TEMPLATE:
        if g["game_no"] == game_no:
            return g.get("alt_mode", "")
    return ""
