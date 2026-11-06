---
description: 미등록어를 lexicon에 추가하고 회귀 확인 (예: /add-vocab 주보 모임 순서)
---
추가할 표현: $ARGUMENTS

1. 각 표현이 `harness/build_scenarios.py`의 **holdout 문장에만** 나오는 말인지 먼저 확인한다. 그렇다면 추가하지 말고 사용자에게 알린다(규칙 2).
2. `pilot/data/lexicon.csv`에 맞는 kind로 넣는다: 여러 어절 표현 `m`, 정확 일치 `x`, 체언 `n`(조사 허용), 용언 어간 `v`(어미 허용). 상황 한정이면 domain에 `protestant`.
   gloss는 기존 표기 관례(용언은 `-다`, 고유명사는 `FS:이름`)를 따른다. 수어 전문가 검수 전 초안이라는 주석 블록 아래에 둔다.
3. `python tools/make_clip_manifest.py` → `python -m pytest -q` → `python -m harness.run_harness --quick`
4. 바뀐 게이트를 보고하고, 사용자가 원하면 커밋한다.
