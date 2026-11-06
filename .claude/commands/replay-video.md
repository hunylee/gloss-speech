---
description: YouTube 예배 영상 자동자막으로 구간별 번역 품질 측정 (예: /replay-video YRq2WCScl_U)
---
영상 ID: $ARGUMENTS

1. 서버의 `media/transcripts/<ID>.json`이 있으면 그것을 쓴다. 없으면 사용자에게 `/replay?v=<ID>` 화면을 브라우저로 한 번 열어 자막을 불러오게 하거나, YouTube "스크립트 표시" 내용을 텍스트 파일로 받는다.
2. `[노래]` 표시 조각과 찬양 구간은 빼고, 말한 부분만 `tools/replay_transcript.py` 또는 `/api/rooms/<room>/text`로 흘린다.
3. 구간별(여는 말·사도신경 / 기도·대표기도 / 설교 / 마침 기도·축도 / 광고) 평균 신뢰도, 지문자 비율, 수어 길이÷말한 시간, 미등록어 상위 40개를 표로 보고한다.
4. 찬양 가사와 광고 속 교인 이름은 보고에 옮겨 적지 않는다.
