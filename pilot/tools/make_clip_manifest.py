"""data/clips.json 생성: 어휘 사전의 gloss마다 실사 클립 항목을 만든다.

실제 촬영 전이라 파일(media/clips/*.mp4)은 없다. 촬영하면 같은 이름으로 넣기만 하면 Viewer가 재생한다.
NOT_YET: 1차 촬영 범위에서 뺀 전문 용어 (하네스에서 '클립 없음 → 지문자/카드' 경로를 검증하려고 일부러 둔다).
dur_ms는 촬영 전 추정치(650ms + 글자당 40ms). 촬영 후 build 단계에서 실제 길이로 덮어쓴다.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.corpus import Corpus, DATA

NOT_YET = {"화답송", "환호송", "사홍서원", "삼귀의", "발원문", "반야심경", "보편지향", "강복",
           "초하루", "죽비", "입정", "공양간", "종무소", "축도", "묵도", "사도신경", "고해성사"}
c = Corpus.load()
clips = {g: {"file": f"clips/{g}.mp4", "dur_ms": 650 + 40 * len(g), "signer": "TBD"}
         for g in sorted(c.vocab) if g not in NOT_YET and g != "?" and not g.isdigit() and not g.startswith("FS:")}
(DATA / "clips.json").write_text(json.dumps(clips, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(clips), "clips registered;", len(NOT_YET), "not yet shot")
