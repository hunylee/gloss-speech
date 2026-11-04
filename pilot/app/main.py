"""SyncSL 시범 서비스 서버 (현장 설치: 노트북 / Mac mini).

실행:  uvicorn app.main:app --host 0.0.0.0 --port 8100
  운영 콘솔  http://localhost:8100/console      (마이크·상황 선택·상위 문장 10개·자유 옵션·QR)
  태블릿     http://<서버 IP>:8100/viewer?room=main   (콘솔 QR로 접속)
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.corpus import Corpus
from app.hub import Hub, lan_ip
from app.pipeline import Pipeline

STATIC = Path(__file__).parent / "static"


class SessionIn(BaseModel):
    domain: str | None = None
    terms: dict[str, str] | None = None     # 자유 옵션: {"요한복음": "", "김은혜 목사": "FS:김은혜 목사"}


class TextIn(BaseModel):
    text: str
    final: bool = True


def create_app(corpus: Corpus | None = None, agent=None, clock=time.monotonic,
               media_root: Path | None = None) -> FastAPI:
    corpus = corpus or Corpus.load()
    media_root = media_root or Path(os.environ.get("MEDIA_ROOT", Path(__file__).parent.parent / "media"))
    media_root.mkdir(parents=True, exist_ok=True)
    hub = Hub()
    pipe = Pipeline(corpus, hub, agent, media_root, clock)
    app = FastAPI(title="SyncSL pilot")
    app.state.pipe, app.state.hub = pipe, hub
    app.mount("/media", StaticFiles(directory=media_root), name="media")

    @app.get("/console")
    def console():
        return FileResponse(STATIC / "console.html")

    @app.get("/")
    @app.get("/viewer")
    def viewer():
        return FileResponse(STATIC / "viewer.html")

    @app.get("/api/domains")
    def domains():
        return corpus.domains

    @app.get("/api/rooms/{room}/session")
    def get_session(room: str):
        s = pipe.session(room)
        return {"domain": s.domain, "terms": s.terms, "order": s.order,
                "viewers": len(hub.room(room).viewers)}

    @app.post("/api/rooms/{room}/session")
    def set_session(room: str, body: SessionIn):
        s = pipe.session(room)
        if body.domain:
            s.domain, s.order = body.domain, 0
        if body.terms is not None:
            s.terms = {k.strip(): v.strip() for k, v in body.terms.items() if k.strip()}
        return get_session(room)

    @app.get("/api/rooms/{room}/suggest")
    def suggest(room: str, limit: int = 10):
        """노트: 상위 문장 10개 — 지금 상황에서 다음에 나올 문장 순서대로."""
        s = pipe.session(room)
        return [{"order": p.order, "text": p.text, "gloss": " ".join(p.gloss)}
                for p in corpus.top_phrases(s.domain, limit, s.order)]

    @app.post("/api/rooms/{room}/text")
    async def text_in(room: str, body: TextIn):
        if not body.final:
            await pipe.partial(room, body.text)
            return {"ok": True}
        return await pipe.final(room, body.text, time.time())

    @app.post("/api/rooms/{room}/phrase/{order}")
    async def phrase(room: str, order: int):
        return await pipe.phrase(room, pipe.session(room).domain, order)

    @app.post("/api/translate")
    def translate(body: TextIn, domain: str = "protestant"):
        from app.gloss import Session
        return pipe.translator.translate(body.text, Session(domain=domain)).as_dict()

    @app.get("/api/viewer-url")
    def viewer_url(request: Request, room: str = "main"):
        return {"url": f"http://{lan_ip()}:{request.url.port or 8100}/viewer?room={room}"}

    @app.get("/qr.svg")
    def qr(request: Request, room: str = "main"):
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(viewer_url(request, room)["url"], image_factory=qrcode.image.svg.SvgPathImage,
                          box_size=10)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @app.get("/health")
    def health():
        t = sorted(pipe.timings_ms)
        p95 = t[int(0.95 * (len(t) - 1))] if t else None
        return {"ok": True, "rooms": {k: len(r.viewers) for k, r in hub.rooms.items()},
                "translate_p95_ms": p95}

    @app.websocket("/ws/viewer")
    async def ws_viewer(ws: WebSocket, room: str = "main", since: int = 0):
        await ws.accept()
        await hub.join(room, ws, since)
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "ping":            # 태블릿 시계 맞추기·연결 확인
                    await ws.send_json({"type": "pong", "t": msg.get("t"), "server": time.time()})
        except WebSocketDisconnect:
            pass
        finally:
            hub.leave(room, ws)

    @app.websocket("/ws/operator")
    async def ws_operator(ws: WebSocket, room: str = "main"):
        """콘솔 → 서버: Web Speech partial/final, 직접 입력."""
        await ws.accept()
        try:
            while True:
                m = await ws.receive_json()
                if m.get("type") == "partial":
                    await pipe.partial(room, m["text"])
                elif m.get("type") == "final":
                    sent = await pipe.final(room, m["text"], m.get("t_speech_end") or time.time())
                    await ws.send_json({"type": "ack", "packets": sent})
        except WebSocketDisconnect:
            pass

    if os.environ.get("STT") == "whisper":
        from app.stt import EnergyVADWhisper

        @app.websocket("/ws/audio")
        async def ws_audio(ws: WebSocket, room: str = "main"):
            """16kHz mono PCM16 바이너리 조각을 받는다 (현장 오디오 입력 → 서버)."""
            await ws.accept()

            async def on_final(text, t_end):
                await pipe.final(room, text, t_end)
            stt = EnergyVADWhisper(on_final, os.environ.get("WHISPER_MODEL", "small"))
            try:
                while True:
                    await stt.feed(await ws.receive_bytes())
            except WebSocketDisconnect:
                pass

    return app


app = create_app()
