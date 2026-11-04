"""gloss 품질·지연 지표."""
from __future__ import annotations


def _clean(g: list[str]) -> list[str]:
    return [x for x in g if x != "?"]


def lcs(a: list[str], b: list[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def gloss_scores(pred: list[str], gold: list[str]) -> dict:
    p, g = _clean(pred), _clean(gold)
    common = lcs(p, g)
    prec = common / len(p) if p else 0.0
    rec = common / len(g) if g else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"exact": float(p == g), "order_f1": f1, "recall": rec}


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def mean(values):
    return sum(values) / len(values) if values else None
