"""조회 API, 수어 Viewer, 운영자 콘솔.
실행: uvicorn app.main:app --host 0.0.0.0 --port 8000
  운영자 콘솔: http://localhost:8000/console   (노트북/Mac mini)
  태블릿 Viewer: http://<서버 IP>:8000/viewer  (콘솔의 QR로 접속)
"""
import os
from pathlib import Path

import io

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db
from app.live import Hub, lan_ip
from app.translate import Lexicon, translate

STATIC = Path(__file__).parent / "static"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", db.ROOT / "data" / "media"))

app = FastAPI(title="script_text")
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_ROOT), name="media")

_lexicon: Lexicon | None = None
hub = Hub()


def lexicon(conn) -> Lexicon:
    global _lexicon
    if _lexicon is None:
        _lexicon = Lexicon.load(conn)
    return _lexicon


class TextIn(BaseModel):
    text: str


@app.get("/")
def player():
    return FileResponse(STATIC / "player.html")


@app.get("/viewer")
def viewer():
    """태블릿용. player.html이 /viewer 경로면 입력창을 숨기고 WebSocket으로 문장을 받는다."""
    return FileResponse(STATIC / "player.html")


@app.get("/console")
def console():
    return FileResponse(STATIC / "console.html")


@app.get("/api/viewer-url")
def viewer_url(request: Request):
    port = request.url.port or 8000
    url = f"http://{lan_ip()}:{port}/viewer"
    return {"url": url, "viewers": len(hub.viewers)}


@app.get("/qr.svg")
def qr_svg(request: Request):
    url = viewer_url(request)["url"]
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml")


@app.websocket("/ws/viewer")
async def ws_viewer(ws: WebSocket):
    await hub.join(ws)
    try:
        while True:
            await ws.receive_text()   # Viewer는 받기만 한다. 연결 유지용.
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(ws)


@app.post("/broadcast")
async def broadcast(body: TextIn):
    """콘솔에서 확정된 문장(음성인식 결과, 목록 선택, 직접 입력)을 모든 Viewer에 보낸다."""
    text = body.text.strip()
    if not text:
        return {"sent": 0}
    return {"sent": await hub.broadcast({"type": "text", "text": text})}


@app.get("/health")
def health():
    with db.connect() as conn:
        conn.execute("select 1")
    return {"ok": True}


@app.get("/domains")
def domains():
    with db.connect() as conn:
        return db.list_domains(conn)


@app.get("/sentences/top")
def top_sentences(domain: str | None = None, limit: int = Query(100, ge=1, le=1000)):
    with db.connect() as conn:
        return db.top_sentences(conn, domain, limit)


@app.post("/gloss")
def gloss(body: TextIn):
    """문장 → gloss 순서열 → 클립 목록.
    mode: sentence(문장 일치) | word(어절 단위 대체) | none(못 찾음)"""
    with db.connect() as conn:
        result = translate(conn, body.text, lexicon(conn))
        clips = db.clips_for_glosses(conn, result["glosses"]) if result["glosses"] else []
    for clip in clips:
        # 영상 파일이 실제로 있을 때만 주소를 준다. 없으면 Viewer가 바로 글자 카드를 보여준다.
        has_file = clip["file_path"] and (MEDIA_ROOT / clip["file_path"]).is_file()
        clip["url"] = f"/media/{clip['file_path']}" if has_file else None
    return {"text": body.text, **result, "matched": result["mode"] == "sentence", "clips": clips}


@app.post("/admin/reload-lexicon")
def reload_lexicon():
    """데이터를 새로 적재한 뒤 호출하면 어절 매칭 사전을 다시 읽는다."""
    global _lexicon
    _lexicon = None
    return {"ok": True}
