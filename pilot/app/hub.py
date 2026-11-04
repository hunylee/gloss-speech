"""노트의 '서버 → web/QR → Tablet(수어 Viewer)': 방(room) 단위 방송.

- 서버가 gloss·재생목록을 한 번만 계산해서 보낸다. (3월 버전은 태블릿마다 /gloss를 다시 불렀다.)
- 메시지마다 seq 번호를 붙이고 최근 20개를 보관해, 중간에 접속하거나 재접속한 태블릿에 다시 보낸다.
"""
from __future__ import annotations

import asyncio
import socket
import time
from collections import deque


class Room:
    def __init__(self, name: str):
        self.name = name
        self.viewers: set = set()
        self.seq = 0
        self.history: deque = deque(maxlen=20)


class Hub:
    def __init__(self):
        self.rooms: dict[str, Room] = {}

    def room(self, name: str) -> Room:
        return self.rooms.setdefault(name, Room(name))

    async def join(self, room: str, ws, since: int = 0) -> None:
        r = self.room(room)
        r.viewers.add(ws)
        replay = [m for m in r.history if m["seq"] > since and m["type"] == "sign"][-3:]
        for m in replay:
            await ws.send_json({**m, "replay": True})

    def leave(self, room: str, ws) -> None:
        self.room(room).viewers.discard(ws)

    async def broadcast(self, room: str, message: dict) -> dict:
        r = self.room(room)
        r.seq += 1
        msg = {**message, "seq": r.seq, "t_emit": time.time()}
        if msg["type"] != "caption.partial":
            r.history.append(msg)
        targets = list(r.viewers)
        results = await asyncio.gather(*(ws.send_json(msg) for ws in targets), return_exceptions=True)
        for ws, res in zip(targets, results):
            if isinstance(res, Exception):
                r.viewers.discard(ws)
        return msg


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
