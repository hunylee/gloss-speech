"""노트의 'Gloss → 영상 순서 (Clip … Clip) → player'.

gloss 순서열을 재생 목록(playlist)으로 바꾸고, 방(room) 단위 재생 시계로 시작 시각·속도를 정한다.
  - clip        : 촬영된(또는 촬영 예정으로 등록된) 실사 수어 클립
  - number      : 숫자 수어
  - fingerspell : 클립이 없는 단어 → 지문자 카드 (음절당 380ms)
  - card        : 클립이 없는 일반 gloss → 글자 카드
  - '?'         : 비수지 신호(의문) → 재생 시간 없이 표시만

밀림(backlog) 정책: 수어 재생은 말보다 느릴 수 있다. 밀림이 CATCHUP_S를 넘으면 1.25배속,
FLUSH_S를 넘으면 밀린 수어를 버리고 최신 문장부터 다시 시작한다(자막은 항상 실시간).
모든 태블릿이 같은 start_at을 받으므로 여러 대가 같은 화면을 보여준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

TRANSITION_MS = 120        # 클립 사이 전환(이음새) 시간
FS_MS_PER_SYLLABLE = 380
CARD_MS = 700
NUMBER_MS_PER_DIGIT = 350
CATCHUP_S = 3.0
FLUSH_S = 8.0


@dataclass
class Item:
    gloss: str
    kind: str
    dur_ms: int
    src: str | None = None

    def as_dict(self):
        return {"gloss": self.gloss, "kind": self.kind, "dur_ms": self.dur_ms, "src": self.src}


def plan(glosses: list[str], clips: dict[str, dict], media_root: Path | None = None) -> list[Item]:
    items = []
    for g in glosses:
        if g == "?":
            items.append(Item(g, "marker", 0))
        elif g.isdigit():
            items.append(Item(g, "number", NUMBER_MS_PER_DIGIT * len(g) + 200))
        elif g.startswith("FS:"):
            items.append(Item(g[3:], "fingerspell", FS_MS_PER_SYLLABLE * len(g[3:])))
        elif g in clips:
            c = clips[g]
            src = None
            if media_root is not None and c.get("file") and (media_root / c["file"]).is_file():
                src = f"/media/{c['file']}"
            items.append(Item(g, "clip", int(c["dur_ms"]), src))
        else:
            items.append(Item(g, "card", CARD_MS))
    return items


def total_ms(items: list[Item]) -> int:
    n = sum(1 for i in items if i.dur_ms)
    return sum(i.dur_ms for i in items) + TRANSITION_MS * max(0, n - 1)


@dataclass
class RoomClock:
    """방 하나의 수어 재생 예정 시각. now는 초 단위 (time.monotonic 또는 harness 가상 시계)."""
    end_at: float = 0.0
    flushes: int = 0
    catchups: int = 0
    lags: list[float] = field(default_factory=list)

    def schedule(self, dur_ms: int, now: float) -> dict:
        lag = max(0.0, self.end_at - now)
        rate, flush = 1.0, False
        if lag > FLUSH_S:
            flush, lag = True, 0.0
            self.flushes += 1
        elif lag > CATCHUP_S:
            rate = 1.25
            self.catchups += 1
        start = now + lag
        self.end_at = start + dur_ms / 1000 / rate
        self.lags.append(lag)
        return {"start_in_ms": int(lag * 1000), "rate": rate, "flush": flush}
