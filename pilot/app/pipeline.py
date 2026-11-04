"""STT 결과 → (자막 즉시) → gloss → 재생목록 → 방송.

자막(caption)은 번역을 기다리지 않는다:
  partial  → caption.partial  (말하는 중 글자가 바로 보임)
  final    → caption.final    (확정 문장) → 번역·재생계획 → sign 패킷
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from app.corpus import Corpus
from app.gloss import Session, Translator, GlossResult
from app.hub import Hub
from app.planner import RoomClock, plan, total_ms

SENT_SPLIT = re.compile(r"(?<=[.?!])\s+|(?<=니다)\s+|(?<=세요)\s+|(?<=시오)\s+|(?<=소서)\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text.strip()) if s and s.strip()]


class Pipeline:
    def __init__(self, corpus: Corpus, hub: Hub, agent=None, media_root: Path | None = None,
                 clock=time.monotonic):
        self.corpus, self.hub, self.media_root, self.clock = corpus, hub, media_root, clock
        self.translator = Translator(corpus, agent)
        self.sessions: dict[str, Session] = {}
        self.clocks: dict[str, RoomClock] = {}
        self.timings_ms: list[float] = []          # 번역+계획 처리 시간
        self._last_partial: dict[str, float] = {}

    def session(self, room: str) -> Session:
        return self.sessions.setdefault(room, Session())

    def room_clock(self, room: str) -> RoomClock:
        return self.clocks.setdefault(room, RoomClock())

    async def partial(self, room: str, text: str, t_speech: float | None = None):
        now = time.monotonic()
        if now - self._last_partial.get(room, 0) < 0.12:          # 초당 8회 이내로 제한
            return None
        self._last_partial[room] = now
        return await self.hub.broadcast(room, {"type": "caption.partial", "text": text, "t_speech": t_speech})

    async def final(self, room: str, text: str, t_speech_end: float | None = None) -> list[dict]:
        out = []
        for sent in split_sentences(text):
            await self.hub.broadcast(room, {"type": "caption.final", "text": sent, "t_speech": t_speech_end})
            t0 = time.perf_counter()
            # Agent(LLM) 호출이 블로킹이어도 이벤트 루프(다른 방송)를 막지 않도록 스레드에서 실행
            result = await asyncio.to_thread(self.translator.translate, sent, self.session(room))
            out.append(await self._emit(room, result, t0, t_speech_end))
        return out

    async def phrase(self, room: str, domain: str, order: int) -> dict | None:
        """콘솔의 '상위 문장 10개' 버튼: 검수된 gloss를 그대로 보낸다 (mode=verified)."""
        p = next((p for p in self.corpus.phrases if p.domain == domain and p.order == order), None)
        if p is None:
            return None
        s = self.session(room)
        s.order = order
        await self.hub.broadcast(room, {"type": "caption.final", "text": p.text, "t_speech": None})
        t0 = time.perf_counter()
        result = GlossResult(p.text, list(p.gloss), "verified", 1.0)
        return await self._emit(room, result, t0, None)

    async def _emit(self, room: str, result: GlossResult, t0: float, t_speech_end):
        items = plan(result.glosses, self.corpus.clips, self.media_root)
        sched = self.room_clock(room).schedule(total_ms(items), self.clock())
        self.timings_ms.append((time.perf_counter() - t0) * 1000)
        return await self.hub.broadcast(room, {
            "type": "sign", **result.as_dict(),
            "low_confidence": result.confidence < 0.67 and result.mode in ("rules", "agent"),
            "playlist": [i.as_dict() for i in items], "total_ms": total_ms(items),
            **sched, "t_speech": t_speech_end,
        })
