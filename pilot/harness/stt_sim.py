"""STT 시뮬레이터: 대본 문장에 '음성인식이 실제로 내는 종류의 오류'와 지연을 넣는다.

실제 STT 엔진 비교가 목적이 아니다. 'STT가 이 정도로 틀리고 늦을 때 뒤 단계(gloss·클립·방송)가
버티는가'를 재현 가능하게(seed 고정) 측정하려는 것이다. 현장 STT의 실제 오류율·지연은
시범 운영 때 녹음으로 따로 측정해서 아래 프로필 숫자를 바꿔 끼운다.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

PROFILES = {
    #            띄어쓰기 붙임, 띄어쓰기 쪼갬, 음절 오인식, 어절 누락, 확정 지연(평균, 표준편차, 초)
    "clean":     dict(merge=0.0, split=0.0, sub=0.0, drop=0.0, lat=(0.6, 0.10)),
    "realistic": dict(merge=0.08, split=0.03, sub=0.02, drop=0.03, lat=(0.9, 0.25)),
    "noisy":     dict(merge=0.15, split=0.05, sub=0.06, drop=0.07, lat=(1.4, 0.40)),
}
SYLLABLES_PER_S = 5.5          # 설교·안내 말하기 속도 근사


def _swap_vowel(ch: str, rng: random.Random) -> str:
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return ch
    cho, jung, jong = code // 588, (code % 588) // 28, code % 28
    jung = (jung + rng.choice([-1, 1, 4])) % 21
    return chr(0xAC00 + cho * 588 + jung * 28 + jong)


@dataclass
class STTOutput:
    partials: list[str]
    final: str
    speech_s: float          # 말한 시간
    final_latency_s: float   # 말이 끝난 뒤 확정 결과가 나오기까지


class SimulatedSTT:
    def __init__(self, profile: str = "realistic", seed: int = 7):
        self.p = PROFILES[profile]
        self.rng = random.Random(seed)

    def run(self, text: str) -> STTOutput:
        rng, p = self.rng, self.p
        t = re.sub(r"[.!,]", "", text)                    # Web Speech는 문장부호를 거의 안 준다
        words = [w for w in t.split() if not (len(t.split()) > 2 and rng.random() < p["drop"])]
        out = []
        for i, w in enumerate(words):
            w = "".join(_swap_vowel(c, rng) if rng.random() < p["sub"] else c for c in w)
            if len(w) > 3 and rng.random() < p["split"]:
                k = rng.randint(1, len(w) - 1)
                w = w[:k] + " " + w[k:]
            out.append(w)
            if i < len(words) - 1 and rng.random() >= p["merge"]:
                out.append(" ")
        final = "".join(out).strip()
        ws = final.split()
        partials = [" ".join(ws[:k]) for k in range(1, len(ws))]
        syl = len(re.sub(r"\s", "", text))
        mu, sd = p["lat"]
        return STTOutput(partials, final, syl / SYLLABLES_PER_S, max(0.2, rng.gauss(mu, sd)))


def cer(ref: str, hyp: str) -> float:
    """문자 오류율 (공백·문장부호 제외)."""
    a, b = re.sub(r"[\s.,!?]", "", ref), re.sub(r"[\s.,!?]", "", hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(a))
