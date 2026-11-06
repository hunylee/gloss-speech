# SyncSL 교회 시범 서비스 (pilot/) — Claude Code 작업 지침

예배 음성을 받아 **한국어 실시간 자막 + gloss 자막 + 수어 클립**을 태블릿에 동시에 띄우는 1-way 시범 서비스다.
지금 활성 상황은 **기독교 예배(protestant) + 공통 안내(common)** 뿐이다. 천주교·불교는 데이터만 있고 꺼져 있다.

## 명령
| 목적 | 명령 (pilot/ 에서) |
|---|---|
| 설치 | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |
| 클립 목록 갱신 | `python tools/make_clip_manifest.py` (lexicon 바꾼 뒤 항상) |
| 서버 실행 | `uvicorn app.main:app --host 0.0.0.0 --port 8100` 또는 Mac에서 `start_pilot.command` 더블클릭(기존 서버를 끄고 다시 켬) |
| 단위·통합 테스트 | `python -m pytest -q` |
| 검증 하네스 | `python -m harness.run_harness` (전체, 1~2분) / `--quick` (realistic만) → `harness/out/report.html` |
| 시나리오 다시 만들기 | `python harness/build_scenarios.py` (phrasebank 바꾼 뒤) |
| 자막 파일로 일괄 번역 | `python tools/replay_transcript.py <자막.txt|srt|vtt>` |

화면: 운영 콘솔 `/console`, 태블릿 `/viewer?room=main`, 예배 영상 연동 시험 `/replay?v=<YouTube ID>`.

## 구조 (노트 4/5의 구성 그대로)
```
Audio → (Web Speech 콘솔 | 서버 faster-whisper) → pipeline.final()
  → caption.final 즉시 방송 (번역을 기다리지 않음)
  → 고정 본문 감지 (사도신경·주기도문 → 전문 영상 1개, 낭독 줄은 fixed-hold)
  → Translator: Top-10 유사 문장 검색 → 검수 템플릿 / 규칙 번역 / (선택) AI Agent
  → planner: gloss → 클립·숫자·지문자·카드 재생목록, 방 단위 재생 시계(밀리면 1.25배속, 8초↑ 건너뜀)
  → hub: seq 붙여 방송, 최근 20개 보관(재접속 복구)
```
| 파일 | 역할 |
|---|---|
| `app/gloss.py` | 번역 핵심. 순서: 세션 용어 → 다어절 표현 → 어절 사전 → 붙은 어절 분리 → 오인식 보정(Top-10 어휘 한정) → **Kiwi 형태소 분석** → 지문자 |
| `app/retrieve.py` | 글자 2-gram 코사인 Top-K, 상황 가중치(현재 1.0 / 공통 0.95 / 그 외 0.8) |
| `app/pipeline.py` | 문장 분리, 자막 선송출, 고정 본문 잠금, 방송 패킷 |
| `app/planner.py` | 재생목록·밀림 정책 |
| `app/agent.py` | Ollama Agent + 가드레일(어휘 밖 20% 넘으면 버림, 시간초과 1.5초) |
| `app/main.py` | FastAPI 라우트, WebSocket(`/ws/viewer`, `/ws/operator`, 선택 `/ws/audio`) |
| `data/*.csv` | domains(active 열), phrasebank(예배 순서 문장+검수 gloss), lexicon, fixed_texts, bible_books |
| `harness/` | STT 시뮬레이터(오류·지연 주입), 가상 태블릿 3~30대, 게이트 15개, 리포트 |

## 지켜야 할 규칙
1. **말하지 않은 뜻을 수어로 내보내지 않는다.** 템플릿은 `_template_supported()`를 통과할 때만 쓴다(알아들은 gloss가 모두 템플릿에 있고, 템플릿에만 있는 단어는 망가진 어절 수 이하, 템플릿의 `FS:` 고유명사는 입력과 같을 때만). 이 검사를 느슨하게 만드는 변경은 하네스 G14(템플릿 오적용)로 반드시 확인한다.
2. **holdout을 보고 사전을 고치지 않는다.** `harness/build_scenarios.py`의 split이 `holdout`인 문장의 단어를 lexicon에 넣으면 점수가 부풀어 판정이 무의미해진다. holdout을 한번 보고 고쳤다면 그 문장들은 dev로 돌리고 **새 holdout을 사전 수정 전에** 작성한다.
3. **gold gloss와 lexicon은 개발자 초안이다.** 농인 수어 전문가 검수 전이라는 사실을 결과 보고에 항상 적는다.
4. **lexicon을 바꾸면** `tools/make_clip_manifest.py` → `pytest` → `harness --quick` 순서로 확인하고, 게이트가 떨어지면 원인을 먼저 본다(임계값을 낮춰서 통과시키지 않는다).
5. **커밋하지 않는 것:** `media/`(실사 클립·예배 자막 `media/transcripts/`), `harness/out/`, `.venv/`. 예배 자막에는 교인 이름(광고의 경조사 등)이 들어 있다.
6. 찬양 가사는 저작물이므로 저장소·리포트·로그에 옮겨 적지 않는다. 찬양 구간은 "♪ 찬양 중"으로만 표시한다.
7. 천주교·불교를 다시 켜려면 `data/domains.csv`의 `active`를 1로 바꾸고, 그 상황의 holdout도 새로 써서 하네스를 돌린다.
8. 커밋 메시지는 한국어로, 무엇을 왜 바꿨는지와 하네스 결과 변화를 적는다. PR 전에 `pytest`와 `harness --quick`를 통과시킨다.

## 현재 수치 (2026-11-04, 기독교, realistic STT 시뮬레이션)
- 게이트 15개 중 14개 통과: 정형 문장 0.89, 운영자 원탭 병행 1.00, 설교 holdout 0.90(작성자가 같아 부풀었을 수 있음), 지연 p95 1.37초, 30대 전달 p95 12ms
- 미달: **G2 변형 문장 0.61** — 광고 어휘(주보, 모임, 순서, 헌금함, "다 같이") 공백
- 실제 예배 영상(잠실중앙교회 11/1 4부, 자동자막 71분) 설교 구간: 평균 신뢰도 0.57, 지문자 47%, 수어 길이 = 말한 시간의 1.4배

## 다음 할 일 (우선순위)
1. 광고·주보 어휘 보강 + 새 holdout 작성 → G2 통과
2. 설교 요약 gloss: `app/agent.py`의 OllamaAgent로 허용 어휘 안에서 문장 압축(수어 1.4배 밀림 해소), 하네스 Agent 게이트로 검증
3. 찬양 모드: 곡별 사전 제작 수어/가사 자막
4. 실사 클립 촬영 우선순위: `harness/out/report.json`의 커버리지와 영상 분석 미등록어 빈도 순
5. 현장 STT 실측(음향 콘솔 라인 입력) → `harness/stt_sim.py` 프로필 교체
