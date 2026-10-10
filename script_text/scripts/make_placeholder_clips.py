"""샘플 gloss마다 글자가 나오는 1초짜리 임시 영상을 만든다 (실제 수어 영상이 오기 전 player 확인용).
사용법: python -m scripts.make_placeholder_clips [--font /path/to/korean.ttf]
"""
import argparse
import subprocess

from app import db
from app.main import MEDIA_ROOT

FONTS = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--font")
    args = p.parse_args()
    font = args.font or next((f for f in FONTS if __import__("os").path.exists(f)), None)
    if not font:
        raise SystemExit("한글 폰트를 찾지 못했어요. --font로 지정하세요.")
    with db.connect() as conn:
        rows = conn.execute(
            "select g.label, c.file_path from clips c join glosses g on g.id = c.gloss_id where c.source = 'sample'"
        ).fetchall()
    for r in rows:
        out = MEDIA_ROOT / r["file_path"]
        if out.exists():
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        text = r["label"].replace("'", "")
        subprocess.run([
            "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x223344:s=640x480:d=1",
            "-vf", f"drawtext=fontfile={font}:text='{text}':fontcolor=white:fontsize=96:x=(w-tw)/2:y=(h-th)/2",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", str(out),
        ], check=True)
    print(f"{len(rows)} clips ready in {MEDIA_ROOT}")


if __name__ == "__main__":
    main()
