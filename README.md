# gloss-speech — the speech → KSL gloss half of SyncSL

**SyncSL** is an open, real-time Korean Sign Language (KSL) interpretation project for Deaf people in Korea.
It has two directions:

| Direction | What it does | Where |
|---|---|---|
| **Speech / text → KSL gloss** (hearing → Deaf) | Korean speech is transcribed, rewritten into KSL gloss order, and shown as Deaf-readable gloss subtitles or sign clips | **this repository** |
| Sign → text (Deaf → hearing) | MediaPipe hand/face landmarks → sign recognition → Korean text | SyncSL engine (not yet public) |

This repository is the speech-to-gloss side. It runs next to the SyncSL gateway (which uses port 8000, so this service uses 8100).

## Why gloss, not plain captions
Korean captions are written in Korean grammar. Many Deaf people whose first language is KSL read
**gloss** — sign words in sign order, with particles and endings removed and questions/negation marked —
more easily than Korean sentences. Example:

```
영등포로 가려면 어떻게 가나요?   →   영등포  가다  방법  ?
```

## What's here

```
demo/          Minimal local web demo (no database)
  gloss_subtitle.py   Korean sentence → gloss: nearest-neighbour retrieval over the GKSL sentence
                      pairs + word-lexicon fallback, question/WH detection, leave-one-out --eval
  claude_refine.py    Optional LLM refinement of low-confidence sentences into gloss
  server.py, index.html   Browser mic (Web Speech, ko-KR) → gloss subtitle, http://localhost:8765
script_text/   Service version (FastAPI + PostgreSQL)
  app/          sentence/gloss/clip DB, text normalisation, translation, live WebSocket viewer
  db/           SQL migrations (Supabase-compatible) and small sample data
  scripts/      loaders for 모두의 말뭉치 and AI Hub KSL label files
  tests/        pytest
```

## Quick start

Demo (needs the GKSL pairs under `data/aihub/external/GKSL-dataset`, see *Data*):
```bash
python3 demo/gloss_subtitle.py "영등포로 가려면 어떻게 가나요?"
python3 demo/server.py        # → http://localhost:8765
```

Service:
```bash
cd script_text
pip install -r requirements.txt
docker compose up -d                       # local PostgreSQL
python -m scripts.ingest migrate
python -m scripts.ingest sample            # small bundled sample data
uvicorn app.main:app --host 0.0.0.0 --port 8100   # /console  /viewer  /docs
pytest -q
```

## Data
Training/reference data is **not** in this repository and must be obtained from its owners under their terms:
- AI Hub Korean Sign Language datasets (login and usage application required)
- 모두의 말뭉치 (National Institute of Korean Language)
- GKSL sentence pairs (external dataset)

Only small hand-written samples (`script_text/db/sample/`) are included. Request logs stay local and are git-ignored,
because they can contain what people said.

## Status
Early stage, maintained by one person. Current scope: one-way settings such as churches, events and lectures.
Next: two-way use in public offices and hospitals, and an avatar/sign-clip player.

Feedback from Deaf users and KSL interpreters is especially welcome — please open an issue.

---

## 한국어 요약
**SyncSL**은 농인을 위한 실시간 한국수어 통역 오픈 프로젝트이고, 이 저장소(gloss-speech)는 그중
**음성·문장 → 수어 gloss 자막** 방향을 맡습니다. 한국어 문장을 수어 어순의 gloss(조사·어미 제거, 의문·부정 표시)로 바꿔
농인이 읽기 쉬운 자막과 수어 클립으로 보여 줍니다. 원본 데이터(AI Hub, 모두의 말뭉치)는 포함하지 않으며 각 기관의 이용 조건에 따라 직접 받아야 합니다.

## License
Code: [Apache License 2.0](LICENSE) © 2026 Taeheon Lee (NextRun).
Datasets referenced above keep their own licenses and are not covered by this license.
