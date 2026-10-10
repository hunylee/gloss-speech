"""말뭉치/수어 데이터를 로컬 DB에 적재한다.

사용법 (script_text 폴더에서):
  python -m scripts.ingest migrate
  python -m scripts.ingest sample
  python -m scripts.ingest demo
  python -m scripts.ingest modu   data/raw/modu    [--domain church]
  python -m scripts.ingest aihub  data/raw/aihub   [--texts data/raw/aihub/texts.csv] [--media-prefix aihub]
"""
import argparse
import csv
import json
import re
from pathlib import Path

from app import db

SAMPLE = db.ROOT / "db" / "sample"


def cmd_migrate(conn, args):
    db.migrate(conn)
    print("migrated")


def cmd_demo(conn, args):
    """데모에서 실제로 말할 문장 (db/sample/demo_sentences.csv). gloss는 AI Hub 사전에 있는 단어로 맞췄다.
    문장을 미리 넣어 두면 정확히 같은 문장이 들어올 때 빠짐없이 변환된다."""
    domains = _load_domains(conn)
    n = 0
    with open(SAMPLE / "demo_sentences.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sid = db.upsert_sentence(conn, row["text"], "demo", domain_id=domains[row["domain"]], count=False)
            db.set_sentence_glosses(conn, sid, row["glosses"].split())
            n += 1
    print(f"demo: {n} sentences")


def _load_domains(conn) -> dict[str, int]:
    with open(SAMPLE / "domains.csv", encoding="utf-8") as f:
        return {row["code"]: db.upsert_domain(conn, row["code"], row["name_ko"]) for row in csv.DictReader(f)}


def cmd_sample(conn, args):
    """샘플 문장·gloss. 실제 데이터 없이 뼈대와 데모 흐름을 확인하는 용도."""
    domains = {}
    with open(SAMPLE / "domains.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domains[row["code"]] = db.upsert_domain(conn, row["code"], row["name_ko"])
    n = 0
    with open(SAMPLE / "sentences.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sid = db.upsert_sentence(conn, row["text"], "sample", domain_id=domains[row["domain"]], count=False)
            labels = row["glosses"].split()
            db.set_sentence_glosses(conn, sid, labels)
            for label in labels:
                db.add_clip(conn, label, f"sample/{label}.mp4", "sample")
            n += 1
    with open(SAMPLE / "aliases.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db.add_alias(conn, row["alias"], row["gloss"])
    print(f"sample: {n} sentences")


# ---------- 모두의 말뭉치 ----------
# 말뭉치마다 JSON 구조가 조금씩 다르다 (document[].utterance[].form, document[].sentence[].form,
# document[].paragraph[].form ...). 이 목록 아래에 있는 "form" 문자열을 문장으로 본다.
_MODU_LIST_KEYS = {"utterance", "sentence", "paragraph"}


def iter_modu_forms(node, under_list=False):
    if isinstance(node, dict):
        if under_list and isinstance(node.get("form"), str):
            yield node["form"], node.get("id")
        for key, value in node.items():
            yield from iter_modu_forms(value, key in _MODU_LIST_KEYS)
    elif isinstance(node, list):
        for item in node:
            yield from iter_modu_forms(item, under_list)


def cmd_modu(conn, args):
    domain_id = _domain_id(conn, args.domain)
    n = 0
    for path in sorted(Path(args.path).rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for form, ref in iter_modu_forms(data):
            if form.strip():
                db.upsert_sentence(conn, form, "modu", source_ref=ref or path.name, domain_id=domain_id)
                n += 1
        conn.commit()
    print(f"modu: {n} sentences")


# ---------- AI Hub 수어 영상 ----------
# 형태소(morpheme) 라벨 JSON: metaData.name = 영상 파일명, data[] = {start, end, attributes:[{name: gloss}]}
# 문장 영상(SEN)은 한국어 문장이 별도 CSV(파일명, 한국어)로 제공되므로 --texts로 연결한다.

def parse_aihub_morpheme(data: dict) -> tuple[str, list[dict]]:
    video = data["metaData"]["name"]
    segments = []
    for item in sorted(data.get("data", []), key=lambda d: d["start"]):
        for attr in item.get("attributes", []):
            segments.append({
                "label": attr["name"],
                "start_ms": round(float(item["start"]) * 1000),
                "end_ms": round(float(item["end"]) * 1000),
            })
    return video, segments


def load_texts(path: str | None) -> dict[str, str]:
    """파일명(확장자 제외) → 한국어 문장. 첫 열 파일명, 마지막 열 한국어로 가정."""
    if not path:
        return {}
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                out[Path(row[0]).stem] = row[-1]
    return out


def cmd_aihub(conn, args):
    texts = load_texts(args.texts)
    domain_id = _domain_id(conn, args.domain)
    n_clips = n_sent = 0
    # 파일명 끝의 촬영 방향(D/F/L/R/U) 중 --angle만 쓴다. 기본은 정면(F).
    pattern = f"*_{args.angle}_morpheme.json" if args.angle else "*.json"
    for path in sorted(Path(args.path).rglob(pattern)):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "metaData" not in data:
            continue
        video, segments = parse_aihub_morpheme(data)
        file_path = f"{args.media_prefix}/{video}"
        signer = m.group(1) if (m := re.search(r"_(REAL\d+)_", video)) else None
        for seg in segments:
            db.add_clip(conn, seg["label"], file_path, "aihub",
                        start_ms=seg["start_ms"], end_ms=seg["end_ms"], signer=signer)
            n_clips += 1
        text = texts.get(Path(video).stem) or data["metaData"].get("korean_text")
        if text and segments:
            sid = db.upsert_sentence(conn, text, "aihub", source_ref=video, domain_id=domain_id)
            db.set_sentence_glosses(conn, sid, [s["label"] for s in segments])
            n_sent += 1
        conn.commit()
    print(f"aihub: {n_clips} clips, {n_sent} sentences")


def _domain_id(conn, code):
    if not code:
        return None
    row = conn.execute("select id from domains where code = %s", (code,)).fetchone()
    if not row:
        raise SystemExit(f"unknown domain: {code} (sample 명령으로 domains를 먼저 넣으세요)")
    return row["id"]


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("sample")
    sub.add_parser("demo")
    m = sub.add_parser("modu")
    m.add_argument("path")
    m.add_argument("--domain")
    a = sub.add_parser("aihub")
    a.add_argument("path")
    a.add_argument("--texts")
    a.add_argument("--domain")
    a.add_argument("--media-prefix", default="aihub")
    a.add_argument("--angle", default="F", help="촬영 방향 D/F/L/R/U, 빈 문자열이면 전부")
    args = p.parse_args(argv)
    with db.connect() as conn:
        globals()[f"cmd_{args.cmd}"](conn, args)
        conn.commit()


if __name__ == "__main__":
    main()
