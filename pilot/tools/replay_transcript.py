"""예배 영상 자막(스크립트)을 파이프라인에 흘려 보고, 결과표와 '사전에 없는 말' 목록을 만든다.

입력: YouTube '스크립트 표시'를 복사한 텍스트, .srt/.vtt, 또는 한 줄에 한 문장인 .txt
  python tools/replay_transcript.py 예배_스크립트.txt [--domain protestant] [--terms 요한복음,김은혜]
출력: <입력>.gloss.csv (문장별 결과), 화면에 요약 + 자주 나온 미등록 어절 상위 40개
"""
import argparse, csv, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.corpus import Corpus               # noqa: E402
from app.gloss import Session, Translator   # noqa: E402
from app.pipeline import split_sentences    # noqa: E402

TIME = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}([.,]\d+)?(\s*-->.*)?\s*$")


def read_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or line.isdigit() or TIME.match(line) or line.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        line = re.sub(r"\[(음악|박수|웃음|Music|Applause)[^\]]*\]", "", line).strip()
        if line:
            out.append(line)
    # 유튜브 자동자막은 문장이 잘게 끊기므로 이어 붙인 뒤 문장 단위로 다시 자른다
    return split_sentences(" ".join(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--domain", default="protestant")
    ap.add_argument("--terms", default="", help="자유 옵션 용어, 쉼표로 구분")
    a = ap.parse_args()
    src = Path(a.path)
    t = Translator(Corpus.load())
    s = Session(domain=a.domain, terms={x.strip(): "" for x in a.terms.split(",") if x.strip()})
    rows, unk, modes = [], Counter(), Counter()
    for sent in read_lines(src):
        r = t.translate(sent, s)
        modes[r.mode] += 1
        unk.update(r.unknown)
        rows.append({"text": sent, "gloss": " ".join(r.glosses), "mode": r.mode,
                     "confidence": round(r.confidence, 2), "unknown": " ".join(r.unknown)})
    out = src.with_suffix(".gloss.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["text"])
        w.writeheader(); w.writerows(rows)
    n = len(rows) or 1
    low = sum(1 for r in rows if r["confidence"] < 0.67 and r["mode"] == "rules")
    print(f"문장 {len(rows)}개 | 검수 템플릿 {modes['template']} | 규칙 {modes['rules']} | 부분 번역(신뢰도<0.67) {low} ({low/n:.0%})")
    print("자주 나온 미등록 어절:", ", ".join(f"{w}({c})" for w, c in unk.most_common(40)))
    print("결과표:", out)


if __name__ == "__main__":
    main()
