# script_text

실시간 음성을 수어 gloss 기반 자막·영상으로 변환하는 프로젝트. 데모(시나리오 ①: 교회·행사·강연 단방향)를 먼저 만들고 정식 버전으로 넘어간다.

## 진행 계획
1. **뼈대와 데이터 기반** (완료): 로컬 PostgreSQL, 문장·gloss·클립 스키마, 모두의 말뭉치/AI Hub 적재, 조회 API
2. **Text→Gloss→영상** (완료, 실데이터 대기): 상황별 상위 문장 매칭 + 단어 단위 gloss 대체, (옵션) AI Agent 변환, 클립 이어 재생 player
3. **데모 통합** (진행 중, 영상 없이 글자 카드로): 노트북/Mac mini 서버, 마이크 → 로컬 STT → WebSocket → 태블릿 수어 Viewer(웹, QR 접속)
4. **테스트와 코드 리뷰**, 정식 버전 로드맵(클라우드, ② 관공서·병원 양방향, ③ YouTube 플러그인·3D 아바타)

## 구조
```
app/          DB 접근(db.py), 문장 정규화(textnorm.py), 조회 API(main.py)
db/migrations SQL 스키마 (Supabase에 그대로 적용 가능)
db/sample     샘플 상황·문장·gloss (실데이터 전 뼈대 확인용)
scripts/      적재 스크립트 (ingest.py)
data/raw      내려받은 원본 데이터 (git 제외)
data/media    수어 영상 파일 (git 제외)
tests/        pytest
```

## 실행
```bash
pip install -r requirements.txt
docker compose up -d                 # 로컬 PostgreSQL (이미 설치돼 있으면 생략, .env.example 참고)
python -m scripts.ingest migrate
python -m scripts.ingest sample      # 샘플 데이터
python -m scripts.make_placeholder_clips  # gloss 글자가 나오는 임시 영상 (ffmpeg 필요)
uvicorn app.main:app --host 0.0.0.0 --port 8000   # 콘솔: /console  태블릿: /viewer  API 문서: /docs
pytest -q                            # script_text_test DB를 만들고 지운다
```

## 실데이터 적재
데이터는 직접 내려받아 `data/raw` 아래에 둔다 (AI Hub·모두의 말뭉치는 로그인과 이용 신청 필요).
```bash
python -m scripts.ingest modu  data/raw/modu  --domain church
python -m scripts.ingest aihub data/raw/aihub/morpheme --texts data/raw/aihub/texts.csv
```
- 모두의 말뭉치: `utterance` / `sentence` / `paragraph` 목록 아래의 `form`을 문장으로 읽는다.
- AI Hub 수어 영상: 형태소 라벨 JSON(`metaData.name`, `data[].start/end/attributes[].name`)에서 gloss 구간을 클립으로, `--texts` CSV(파일명, 한국어 문장)로 문장과 연결한다. 실제 파일을 받으면 형식을 확인하고 파서를 맞춘다.
- 영상 파일은 `data/media/aihub/<파일명>`에 두면 `clips.file_path`와 맞는다.

## API
| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /domains | 상황 목록 |
| GET | /sentences/top?domain=hospital&limit=100 | 상황별 자주 쓰는 문장 |
| POST | /gloss `{"text": "..."}` | 문장 → gloss 순서열 + 클립. `mode`: sentence(문장 일치) / word(어절 단위) / none |
| POST | /admin/reload-lexicon | 데이터 적재 후 어절 매칭 사전 다시 읽기 |
| GET | / | 수어 player (태블릿 Viewer의 바탕) |

## Text→Gloss 규칙 (app/translate.py)
1. DB에 같은 문장이 있으면 그 gloss 순서열을 쓴다.
2. 없으면 어절마다: `gloss_aliases` 정확 일치 → gloss + 조사/하다 활용(`예배를`, `시작하겠습니다`) → `-다` 용언은 어간 + 어미(`아프세요`→아프다).
3. 못 찾은 어절은 `unknown`으로 돌려준다 (이후 지문자 또는 AI Agent로 처리 예정).

남는 부분이 조사·어미가 아니면 버리므로 `손님`이 `손`으로 잘못 바뀌지 않는다. 대신 사전에 없는 단어(`손님`, `날씨`)는 unknown으로 남는다.

## Player
gloss 순서대로 클립을 재생하고, `start_ms/end_ms`가 있으면 그 구간만 재생한다. 영상 파일이 없거나 재생이 안 되면 gloss 글자 카드를 대신 보여준다.
영상은 H.264 mp4 기준이다 (iPad Safari, Chrome에서 재생됨). 오픈소스 Chromium은 H.264를 못 틀어서 자동 테스트에서는 webm으로 확인했다.

![player](docs/player.png)


## 데모 실행 (현장)
1. 노트북/Mac mini에서 서버 실행: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. 같은 와이파이에 연결된 태블릿으로 콘솔(`http://localhost:8000/console`)의 QR을 찍으면 `/viewer`가 열린다.
3. 콘솔에서 문장을 보내는 방법 세 가지
   - **마이크 시작**: 브라우저 음성인식(ko-KR). Chrome/Edge/Safari에서 동작하고 인터넷 연결이 필요하다 (음성이 브라우저 제조사 서버로 전송됨). 로컬 Whisper는 정식 버전에서 붙인다.
   - **자주 쓰는 문장** 목록을 누르기 (말뭉치 문장으로 시연)
   - **직접 입력**
4. 확정된 문장은 연결된 모든 Viewer에 전달되고, Viewer는 받은 순서대로 gloss 영상(없으면 글자 카드)을 재생한다.

![console](docs/console.png)
![viewer](docs/viewer.png)
