---
description: 교회 시범 서비스 전체 점검 (클립 목록 → 테스트 → 하네스) 후 게이트 변화 보고
---
pilot/ 폴더에서 다음을 순서대로 실행하고 결과를 한국어로 짧게 보고해라.

1. `python tools/make_clip_manifest.py`
2. `python -m pytest -q` — 실패하면 여기서 멈추고 원인부터 설명한다.
3. `python -m harness.run_harness $ARGUMENTS` (인자가 없으면 전체, `--quick`이면 realistic만)
4. `harness/out/report.json`의 게이트를 표로 보여 주고, 직전 커밋 대비 바뀐 게이트와 그 이유를 적는다.
5. 미달 게이트는 "어느 문장이 왜 틀렸는지"를 runs.json에서 3건 이내로 예시한다.

임계값을 낮춰 통과시키지 말 것. holdout 문장을 보고 사전을 고치지 말 것 (pilot/CLAUDE.md 규칙 2).
