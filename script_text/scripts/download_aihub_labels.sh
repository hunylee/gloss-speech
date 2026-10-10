#!/usr/bin/env bash
# AI Hub 수어 데이터셋에서 라벨만 내려받는다 (영상 원본 제외).
# AI Hub는 해외 IP에서 다운로드를 막으므로 국내 PC에서 실행한다.
#   AIHUB_APIKEY=<API key> bash scripts/download_aihub_labels.sh [출력 폴더]
set -euo pipefail

: "${AIHUB_APIKEY:?AIHUB_APIKEY 환경변수에 AI Hub API key를 넣어 주세요}"
OUT="${1:-data/raw/aihub}"
mkdir -p "$OUT"

# datasetkey:filekey:이름
FILES=(
  "103:39581:sign_train_crowd_morpheme"     # 수어 영상 Training CROWD 형태소 (8MB)
  "103:39584:sign_train_real_sen_morpheme"  # Training REAL 문장 형태소 (81MB)
  "103:39601:sign_train_real_word_morpheme" # Training REAL 단어 형태소 (110MB)
  "103:39475:sign_val_crowd_morpheme"       # Validation CROWD 형태소 (1MB)
  "103:39478:sign_val_real_word_morpheme"   # Validation REAL 단어 형태소 (14MB)
  "103:494853:sign_val_real_sen_morpheme"   # Validation REAL 문장 형태소 (10MB)
  "636:61896:disaster_script_train"         # 재난 안전 수어 스크립트 Training (372MB)
)

for entry in "${FILES[@]}"; do
  IFS=: read -r dataset filekey name <<<"$entry"
  dest="$OUT/$name"
  if [ -d "$dest" ]; then echo "skip $name"; continue; fi
  echo "download $name"
  tarfile="$OUT/$name.tar"
  code=$(curl -sS -L -C - -o "$tarfile" -H "apikey:$AIHUB_APIKEY" -w '%{http_code}' \
    "https://api.aihub.or.kr/down/0.6/$dataset.do?fileSn=$filekey")
  if [ "$code" != 200 ]; then
    echo "실패 ($code): $(head -c 300 "$tarfile")" >&2
    rm -f "$tarfile"
    exit 1
  fi
  mkdir -p "$dest"
  tar -xf "$tarfile" -C "$dest"
  # 큰 파일은 .partN 조각으로 나뉘어 온다: 이어 붙인다
  find "$dest" -name '*.part*' | sed 's/\.part[0-9]*$//' | sort -u | while read -r base; do
    ls "$base".part* | sort -V | tr "\n" "\0" | xargs -0 cat >"$base"
    rm "$base".part*
  done
  find "$dest" -name '*.zip' | while read -r z; do unzip -q -o "$z" -d "${z%.zip}" && rm "$z"; done
  rm "$tarfile"
done
echo "done: $OUT"
