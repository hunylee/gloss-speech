"""노트의 'AI Agent ↔ 서버': 규칙 번역 신뢰도가 낮은 문장만 LLM에 다시 맡긴다.

안전장치(가드레일)가 핵심이다.
  - Top-10 검수 문장을 예시로 주고, 허용 어휘 목록 밖의 gloss는 쓰지 못하게 한다.
  - 응답이 늦으면(timeout) 규칙 결과를 그대로 쓴다. 자막은 Agent를 기다리지 않는다(pipeline 참고).
  - 어휘 밖 토큰이 20%를 넘거나 길이가 비정상이면 결과 전체를 버린다.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field


def validate(glosses: list[str], allowed: set[str], draft: list[str]) -> list[str] | None:
    if not glosses or len(glosses) > max(4, 2 * len(draft)):
        return None
    bad = [g for g in glosses if g not in allowed and not g.startswith("FS:") and not g.isdigit()]
    if len(bad) / len(glosses) > 0.2:
        return None
    return [g if (g in allowed or g.startswith("FS:") or g.isdigit()) else f"FS:{g}" for g in glosses]


@dataclass
class AgentStats:
    calls: int = 0
    accepted: int = 0
    rejected: int = 0
    timeouts: int = 0
    latencies_ms: list[float] = field(default_factory=list)


class OllamaAgent:
    """로컬 Ollama(Gemma 등) 사용. 현장 Mac mini에서 인터넷 없이 동작 가능."""

    def __init__(self, model: str = "gemma3:4b", url: str = "http://localhost:11434/api/generate",
                 timeout_s: float = 1.5):
        self.model, self.url, self.timeout_s = model, url, timeout_s
        self.stats = AgentStats()

    def _prompt(self, text, domain, draft, hits, allowed):
        examples = "\n".join(f"- {h.phrase.text} => {' '.join(h.phrase.gloss)}" for h in hits[:10])
        vocab = " ".join(sorted(allowed)[:600])
        return (f"한국어 문장을 한국수어 gloss(수어 어순, 조사·어미 제거)로 바꾸세요. 상황: {domain}\n"
                f"예시(같은 상황의 검수 문장):\n{examples}\n허용 gloss: {vocab}\n"
                f"허용 목록에 없는 단어는 FS:단어 로 쓰세요(지문자).\n초안: {' '.join(draft)}\n"
                f"문장: {text}\n출력은 gloss만 공백으로 구분해 한 줄로.")

    def refine(self, text, domain, draft, hits, allowed):
        self.stats.calls += 1
        t0 = time.perf_counter()
        body = json.dumps({"model": self.model, "prompt": self._prompt(text, domain, draft, hits, allowed),
                           "stream": False, "options": {"temperature": 0}}).encode()
        try:
            req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                out = json.loads(r.read())["response"].strip().splitlines()[0].split()
        except Exception:
            self.stats.timeouts += 1
            return None
        finally:
            self.stats.latencies_ms.append((time.perf_counter() - t0) * 1000)
        ok = validate(out, allowed, draft)
        if ok is None:
            self.stats.rejected += 1
        else:
            self.stats.accepted += 1
        return ok
