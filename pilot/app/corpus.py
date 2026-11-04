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
class FixedText:
    """매주 똑같이 낭독하는 본문(사도신경·주기도문). 본문 전체는 저장하지 않고 시작 문구·특징 단어로 알아본다."""
    id: str
    title: str
    triggers: list[str]
    keywords: list[str]
    clip: str
    dur_ms: int
    lock_s: float

    def is_start(self, key: str) -> bool:
        return any(t in key for t in self.triggers)

    def hits(self, key: str) -> int:
        return sum(1 for k in self.keywords if k in key)


@dataclass
class Corpus:
    domains: dict[str, str]
    phrases: list[Phrase]
    lexicon: list[LexEntry]
    clips: dict[str, dict]
    by_surface: dict[str, list[LexEntry]] = field(default_factory=dict)
    mwe: list[LexEntry] = field(default_factory=list)
    vocab: set[str] = field(default_factory=set)
    fixed: list[FixedText] = field(default_factory=list)

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
        # active=0인 상황(지금은 천주교·불교)은 데이터는 남겨 두고 콘솔·검색·번역에서 뺀다
        with open(root / "domains.csv", encoding="utf-8") as f:
            domains = {r["code"]: r["name_ko"] for r in csv.DictReader(f)
                       if r.get("active", "1").strip() != "0"}
        with open(root / "phrasebank.csv", encoding="utf-8") as f:
            phrases = [Phrase(r["domain"], int(r["order"]), r["text"], r["gloss"].split())
                       for r in csv.DictReader(f) if r["domain"] in domains]
        with open(root / "lexicon.csv", encoding="utf-8") as f:
            rows = [l for l in f if l.strip() and not l.startswith("#")]
        lexicon = [LexEntry(r["surface"], r["gloss"].split(), r["domain"], r["kind"])
                   for r in csv.DictReader(rows) if r["domain"] in ("*", *domains)]
        clips_path = root / "clips.json"
        clips = json.loads(clips_path.read_text(encoding="utf-8")) if clips_path.exists() else {}
        fixed = []
        if (root / "fixed_texts.csv").exists():
            with open(root / "fixed_texts.csv", encoding="utf-8") as f:
                fixed = [FixedText(r["id"], r["title"], r["trigger"].split("|"), r["keywords"].split("|"),
                                   r["clip"], int(r["dur_ms"]), float(r["lock_s"])) for r in csv.DictReader(f)]
        return cls(domains, phrases, lexicon, clips, fixed=fixed)

    def top_phrases(self, domain: str, limit: int = 10, after_order: int = 0) -> list[Phrase]:
        """콘솔에 띄울 '이 상황에서 다음에 나올 가능성이 큰 문장' 목록 (예배 순서 기준)."""
        rows = [p for p in self.phrases if p.domain == domain]
        nxt = [p for p in rows if p.order > after_order] + [p for p in rows if p.order <= after_order]
        return nxt[:limit]
