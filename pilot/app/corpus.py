"""데이터 적재: 상황(domain), 상황별 문장 은행(phrasebank), 어휘 사전(lexicon), 수어 클립 목록(clips).

현장 설치(노트북·Mac mini)에서 DB 서버 없이 돌아가도록 CSV/JSON 파일만 쓴다.
(3월 버전은 PostgreSQL + docker가 필요해서 현장 세팅이 무거웠다.)
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def normalize(text: str) -> str:
    """매칭용 정규화: NFC, 문장부호 제거, 공백 하나로."""
    t = unicodedata.normalize("NFC", text)
    t = re.sub(r"[\"'“”‘’.,!·…~]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


@dataclass
class Phrase:
    domain: str
    order: int
    text: str
    gloss: list[str]
    key: str = ""

    def __post_init__(self):
        self.key = normalize(self.text).replace("?", "")


@dataclass
class LexEntry:
    surface: str
    gloss: list[str]          # 빈 리스트 = 버리는 말
    domain: str               # '*' 또는 domain code
    kind: str                 # m / x / n / v


@dataclass
class Corpus:
    domains: dict[str, str]
    phrases: list[Phrase]
    lexicon: list[LexEntry]
    clips: dict[str, dict]
    by_surface: dict[str, list[LexEntry]] = field(default_factory=dict)
    mwe: list[LexEntry] = field(default_factory=list)
    vocab: set[str] = field(default_factory=set)

    def __post_init__(self):
        for e in self.lexicon:
            if e.kind == "m":
                self.mwe.append(e)
            else:
                self.by_surface.setdefault(e.surface, []).append(e)
            self.vocab.update(e.gloss)
        for p in self.phrases:
            self.vocab.update(p.gloss)
        self.mwe.sort(key=lambda e: len(e.surface), reverse=True)   # 긴 표현부터 치환

    @classmethod
    def load(cls, root: Path = DATA) -> "Corpus":
        with open(root / "domains.csv", encoding="utf-8") as f:
            domains = {r["code"]: r["name_ko"] for r in csv.DictReader(f)}
        with open(root / "phrasebank.csv", encoding="utf-8") as f:
            phrases = [Phrase(r["domain"], int(r["order"]), r["text"], r["gloss"].split())
                       for r in csv.DictReader(f)]
        with open(root / "lexicon.csv", encoding="utf-8") as f:
            rows = [l for l in f if l.strip() and not l.startswith("#")]
        lexicon = [LexEntry(r["surface"], r["gloss"].split(), r["domain"], r["kind"])
                   for r in csv.DictReader(rows)]
        clips_path = root / "clips.json"
        clips = json.loads(clips_path.read_text(encoding="utf-8")) if clips_path.exists() else {}
        return cls(domains, phrases, lexicon, clips)

    def top_phrases(self, domain: str, limit: int = 10, after_order: int = 0) -> list[Phrase]:
        """콘솔에 띄울 '이 상황에서 다음에 나올 가능성이 큰 문장' 목록 (예배 순서 기준)."""
        rows = [p for p in self.phrases if p.domain == domain]
        nxt = [p for p in rows if p.order > after_order] + [p for p in rows if p.order <= after_order]
        return nxt[:limit]
