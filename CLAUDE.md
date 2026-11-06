# gloss-speech (SyncSL) — Claude Code 작업 지침

한국어 음성 → 한국수어(KSL) gloss·수어 영상 표출 저장소. NextRun(Sign-Lab)의 SyncSL 제품.

## 폴더
| 경로 | 내용 | 상태 |
|---|---|---|
| `pilot/` | **교회 시범 서비스** — 실시간 한국어 자막 + gloss 자막 + 수어 클립, 검증 하네스 | 현재 작업 대상. 세부 지침은 `pilot/CLAUDE.md` |
| `script_text/` | 3월 서비스 버전 (FastAPI + PostgreSQL, 운영 콘솔 → 태블릿) | 참고용, 수정하지 않음 |
| `demo/` | 초기 gloss 자막 데모 스크립트 | 참고용 |

## 브랜치
- `main`: 3월 버전. 검수 전 기능을 합치지 않는다.
- `church-stt`: 교회 예배 STT·수어 시범 작업 브랜치 (기독교만 활성).
- `pilot/religion-1way`: church-stt의 이전 단계(종교 3종 설계·하네스 1차).

## 공통 규칙
- 응답·커밋 메시지·문서는 한국어.
- 농인 사용자 관점이 중심이다. "청인이 편한 자막"으로 기능을 설명하지 않는다.
- 수어 gloss·어휘는 농인 수어 전문가 검수 전 초안임을 결과에 항상 밝힌다.
- 개인정보(예배 광고 속 교인 이름, 녹음, 실사 촬영 영상)는 커밋하지 않는다.
- 웹와치 MOU 관련 내용은 어떤 문서에도 넣지 않는다.

## 빠른 시작
```bash
cd pilot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tools/make_clip_manifest.py
.venv/bin/python -m pytest -q
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100
```
자주 쓰는 작업은 슬래시 명령으로 있다: `/pilot-check`, `/pilot-run`, `/add-vocab`, `/replay-video`.
