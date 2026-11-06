---
description: 시범 서버를 켜고 콘솔·태블릿·영상 연동 주소를 안내
---
pilot/ 에서 시범 서버를 실행한다.

- Mac이면 사용자에게 `pilot/start_pilot.command` 더블클릭을 안내한다 (기존 8100 서버를 끄고 다시 켬, 처음엔 설치로 1~2분).
- 직접 실행할 수 있으면 `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100` 를 백그라운드로 띄우고 `/health`로 확인한다.

안내할 주소: 운영 콘솔 `http://localhost:8100/console`, 태블릿 `http://<서버 IP>:8100/viewer?room=main`(콘솔 QR),
예배 영상 연동 시험 `http://localhost:8100/replay?v=<YouTube 영상 ID>`(태블릿은 `room=replay`).
