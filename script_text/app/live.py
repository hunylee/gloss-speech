"""운영자 콘솔에서 확정된 문장을 연결된 태블릿 Viewer 전체에 보낸다."""
import socket

from fastapi import WebSocket


class Hub:
    def __init__(self):
        self.viewers: set[WebSocket] = set()

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.viewers.add(ws)

    def leave(self, ws: WebSocket) -> None:
        self.viewers.discard(ws)

    async def broadcast(self, message: dict) -> int:
        dead = []
        for ws in list(self.viewers):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(ws)
        return len(self.viewers)


def lan_ip() -> str:
    """태블릿이 접속할 이 서버의 사설 IP. 네트워크가 없으면 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # 실제로 패킷을 보내지 않고 경로만 고른다
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
