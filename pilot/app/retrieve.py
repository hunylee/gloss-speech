"""노트의 'Text to Gloss — 상위 문장 10개를 고려': 입력 문장과 비슷한 문장 Top-K를 찾는다.

- 현재 상황(domain) 문장은 가중치 1.0, 공통 안내는 0.95, 다른 상황은 0.8을 곱한다.
- Top-1이 충분히 비슷하면 그 문장의 검수된 gloss를 템플릿으로 쓰고(숫자만 바꿔 끼움),
  아니면 Top-10의 gloss를 '문맥 어휘'로 써서 어절 번역의 중의성을 푼다.
- 외부 라이브러리 없이 글자 2-gram 코사인 유사도. 수천 문장까지는 선형 탐색으로 1ms 안팎.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.corpus import Corpus, Phrase, normalize

NUM = re.compile(r"\d+")


def _grams(text: str) -> Counter:
    s = re.sub(r"\s+", "", NUM.sub("#", text))
    return Counter(s[i:i + 2] for i in range(len(s) - 1)) if len(s) > 1 else Counter([s])


def cosine(a: Counter, b: Counter) -> float:
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Hit:
    phrase: Phrase
    score: float


class Retriever:
    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self._grams = [(p, _grams(p.key)) for p in corpus.phrases]

    def top_k(self, text: str, domain: str, k: int = 10) -> list[Hit]:
        q = _grams(normalize(text))
        hits = []
        for p, g in self._grams:
            w = 1.0 if p.domain == domain else (0.95 if p.domain == "common" else 0.8)
            hits.append(Hit(p, cosine(q, g) * w))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]


def fill_numbers(template_text: str, template_gloss: list[str], text: str) -> list[str] | None:
    """템플릿 문장과 입력 문장의 숫자 개수가 같으면 gloss 속 숫자를 입력값으로 바꾼다."""
    src, dst = NUM.findall(template_text), NUM.findall(text)
    if len(src) != len(dst):
        return None
    mapping = dict(zip(src, dst))
    return [mapping.get(g, g) for g in template_gloss]
