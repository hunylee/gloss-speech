# SyncSL 종교시설 시범 서비스 (pilot)

음성 → **한국어 실시간 자막 + gloss 자막 + 수어 클립**을 태블릿에 동시에 띄우는 1-way 시범 서비스입니다.
대상: 기독교 예배 · 천주교 미사 · 불교 법회. 노트(4/5)의 구조를 그대로 따릅니다.

```
Audio ─▶ 서버(Notebook/Mac mini, 현장 설치) ◀─▶ AI Agent(선택, 로컬 LLM)
           │  STT → 문장 분리 → Text→Gloss(상위 문장 10개 + 상황 + 자유 옵션) → Gloss→클립 순서 → 재생 계획
           └─ web/QR ─▶ Tablet 수어 Viewer (수어 클립 · gloss 자막 · 한국어 자막)
```

## 실행
```bash
pip install -r requirements.txt
python tools/make_clip_manifest.py          # data/clips.json (클립 목록) 생성
uvicorn app.main:app --host 0.0.0.0 --port 8100
```
- 운영 콘솔: http://localhost:8100/console — 상황 선택, 자유 옵션(설교 제목·인명·본문), 🎙 음성 인식, 상위 문장 10개 원탭, QR
- 태블릿: 콘솔 QR을 찍으면 `http://<서버IP>:8100/viewer?room=main`
- 실사 수어 클립: `media/clips/<gloss>.mp4` 로 넣으면 바로 재생. 없으면 글자 카드·지문자 카드로 대신 표시
- 현장 오디오를 서버로 직접(인터넷 없이): `pip install faster-whisper numpy` 후 `STT=whisper uvicorn ...`, `/ws/audio`로 16kHz PCM 전송
- AI Agent(로컬 Ollama): `app/agent.py`의 `OllamaAgent`를 `create_app(agent=...)`에 넘김

## 검증 (harness)
```bash
pytest -q                          # 단위·통합 테스트 10개
python -m harness.run_harness      # 시나리오 검증 → harness/out/report.html
```
실제 서버를 띄우고 가상 콘솔(STT 오류·지연 주입) + 가상 태블릿 3~30대로 기독교·천주교·불교 시나리오를 흘려
gloss 품질, 종단 지연, 방송 순서·누락, 재접속 복구, Agent 장애, 재생 밀림, 클립 커버리지를 게이트로 판정합니다.
gold gloss는 개발자 초안이라 농인 수어 전문가 검수가 필요합니다.

## 폴더
| 경로 | 역할 |
|---|---|
| `app/corpus.py` | 상황·문장 은행·어휘 사전·클립 목록 (CSV/JSON, DB 서버 없음) |
| `app/retrieve.py` | 상위 문장 Top-10 검색 (상황 가중치) |
| `app/gloss.py` | Text→Gloss: 검수 템플릿 / 규칙(띄어쓰기 복원·오인식 보정·상황별 뜻) / Agent |
| `app/agent.py` | AI Agent(Ollama) + 가드레일 |
| `app/planner.py` | Gloss→클립 재생목록, 밀림 시 1.25배속·건너뛰기 |
| `app/hub.py`, `app/pipeline.py`, `app/main.py` | 방송·파이프라인·API/WebSocket |
| `app/static/` | 운영 콘솔, 태블릿 Viewer |
| `data/` | domains, phrasebank(종교별 순서 문장), lexicon, clips |
| `harness/` | 시나리오, STT 시뮬레이터, 지표, 게이트, 리포트 |
