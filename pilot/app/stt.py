"""노트의 'Audio → 서버(in)': 현장 음향 콘솔/마이크 라인 입력을 서버에서 직접 받는 STT 어댑터.

시범 서비스에는 두 가지 입력 경로가 있다.
  A) 운영 콘솔 브라우저의 Web Speech API(ko-KR)  — 추가 설치 없음, partial 자막 지원 (Chrome 권장)
  B) 서버 오디오 입력 + faster-whisper (이 파일) — 인터넷 없는 현장용, partial 없음(문장 단위)

B는 `pip install faster-whisper numpy` 후 STT=whisper 로 켠다. 이 저장소의 harness는 STT를
대본+오류주입으로 대체해 측정하므로, B의 실제 인식률·지연은 현장 녹음으로 따로 재야 한다.
"""
from __future__ import annotations

import asyncio
import time


class EnergyVADWhisper:
    """16kHz mono PCM16 조각을 받아, 무음 600ms 또는 최대 8초마다 한 문장으로 인식한다."""

    def __init__(self, on_final, model_size: str = "small", sample_rate: int = 16000,
                 silence_ms: int = 600, max_s: float = 8.0, threshold: float = 0.012):
        import numpy as np                      # noqa: F401  (설치 확인용)
        from faster_whisper import WhisperModel
        self.np = np
        self.model = WhisperModel(model_size, device="auto", compute_type="int8")
        self.on_final, self.sr = on_final, sample_rate
        self.silence_ms, self.max_s, self.threshold = silence_ms, max_s, threshold
        self.buf, self.silent_ms, self.speaking = [], 0, False

    async def feed(self, pcm16: bytes):
        a = self.np.frombuffer(pcm16, dtype=self.np.int16).astype(self.np.float32) / 32768
        loud = float(self.np.sqrt(self.np.mean(a * a))) > self.threshold if len(a) else False
        dur_ms = 1000 * len(a) / self.sr
        if loud:
            self.speaking, self.silent_ms = True, 0
        elif self.speaking:
            self.silent_ms += dur_ms
        if self.speaking:
            self.buf.append(a)
        total_s = sum(len(b) for b in self.buf) / self.sr
        if self.speaking and (self.silent_ms >= self.silence_ms or total_s >= self.max_s):
            audio = self.np.concatenate(self.buf)
            self.buf, self.silent_ms, self.speaking = [], 0, False
            t_end = time.time()
            text = await asyncio.to_thread(self._transcribe, audio)
            if text:
                await self.on_final(text, t_end)

    def _transcribe(self, audio) -> str:
        segs, _ = self.model.transcribe(audio, language="ko", beam_size=1, vad_filter=False)
        return " ".join(s.text.strip() for s in segs).strip()
