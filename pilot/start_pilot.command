#!/bin/bash
# SyncSL 시범 서비스 실행 (Mac에서 더블클릭). 처음 한 번은 설치 때문에 1~2분 걸립니다.
cd "$(dirname "$0")" || exit 1
# 이미 8100번에서 돌고 있는 시범 서버가 있으면 끄고 새로 켠다 (다시 시작)
OLD=$(lsof -ti tcp:8100 -sTCP:LISTEN 2>/dev/null)
if [ -n "$OLD" ]; then echo "기존 서버 종료: $OLD"; kill $OLD 2>/dev/null; sleep 1; fi
PY=""
for c in python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then echo "Python 3.10 이상이 필요합니다: brew install python@3.12"; read -r; exit 1; fi
echo "Python: $($PY --version)"
if [ ! -x .venv/bin/python ]; then
  echo "가상환경 만드는 중…"; "$PY" -m venv .venv || { read -r; exit 1; }
fi
.venv/bin/pip install -q -r requirements.txt || { echo "설치 실패"; read -r; exit 1; }
[ -f data/clips.json ] || .venv/bin/python tools/make_clip_manifest.py
IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<Mac IP>")
echo ""
echo "=============================================="
echo " 운영 콘솔 : http://localhost:8100/console"
echo " 태블릿    : http://$IP:8100/viewer?room=main (콘솔 QR)"
echo " 영상 시험 : http://localhost:8100/replay"
echo " 끄기      : 이 창에서 Ctrl+C"
echo "=============================================="
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
