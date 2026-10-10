from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.textnorm import normalize
from scripts import ingest


def test_normalize():
    assert normalize("  어디가   아프세요? ") == "어디가 아프세요"


def test_sample_ingest_and_lookup(conn):
    ingest.cmd_sample(conn, None)
    conn.commit()
    assert db.glosses_for_text(conn, "어디가 아프세요") == ["어디", "아프다", "질문"]
    assert db.glosses_for_text(conn, "없는 문장") is None
    top = db.top_sentences(conn, "hospital", 10)
    assert len(top) == 3 and all(r["domain"] == "hospital" for r in top)


def test_repeated_sentence_increments_frequency(conn):
    a = db.upsert_sentence(conn, "감사합니다.", "modu")
    b = db.upsert_sentence(conn, "감사합니다", "modu")
    assert a == b
    assert conn.execute("select frequency from sentences where id=%s", (a,)).fetchone()["frequency"] == 2


def test_clips_keep_gloss_order_and_missing(conn):
    db.add_clip(conn, "B", "b.mp4", "t")
    db.add_clip(conn, "A", "a.mp4", "t")
    db.upsert_gloss(conn, "C")
    clips = db.clips_for_glosses(conn, ["A", "B", "C", "A"])
    assert [c["file_path"] for c in clips] == ["a.mp4", "b.mp4", None, "a.mp4"]


def test_modu_parser():
    data = {"document": [{"utterance": [{"id": "u1", "form": "안녕하세요"}],
                          "paragraph": [{"form": "문단입니다"}], "metadata": {"form": "무시"}}]}
    assert [f for f, _ in ingest.iter_modu_forms(data)] == ["안녕하세요", "문단입니다"]


def test_aihub_parser():
    data = {"metaData": {"name": "NIA_SL_SEN0001_REAL01_F.mp4"},
            "data": [{"start": 2.5, "end": 3.0, "attributes": [{"name": "아프다"}]},
                     {"start": 1.0, "end": 2.0, "attributes": [{"name": "어디"}]}]}
    video, segs = ingest.parse_aihub_morpheme(data)
    assert video == "NIA_SL_SEN0001_REAL01_F.mp4"
    assert [s["label"] for s in segs] == ["어디", "아프다"]
    assert segs[0]["start_ms"] == 1000


def test_api_gloss(conn):
    ingest.cmd_sample(conn, None)
    conn.commit()
    client = TestClient(app)
    r = client.post("/gloss", json={"text": "감사합니다"}).json()
    assert r["matched"] and r["glosses"] == ["감사"]
    assert r["clips"][0]["file_path"] == "sample/감사.mp4"
    assert client.post("/gloss", json={"text": "모르는 말"}).json()["matched"] is False
    assert len(client.get("/sentences/top", params={"limit": 5}).json()) == 5


def test_word_fallback(conn):
    from app.translate import translate
    ingest.cmd_sample(conn, None)
    conn.commit()
    r = translate(conn, "예배를 함께 기도해요")
    assert r["mode"] == "word"
    assert r["glosses"] == ["예배", "함께", "기도"]
    r = translate(conn, "신분증 보여 주세요 빨리")
    assert r["glosses"] == ["신분증", "보다", "부탁"] and r["unknown"] == ["빨리"]
    assert translate(conn, "어디가 아프세요?")["mode"] == "sentence"
    assert translate(conn, "가나다라")["mode"] == "none"


def test_api_gloss_word_mode_has_urls(conn):
    import app.main as main
    ingest.cmd_sample(conn, None)
    conn.commit()
    main._lexicon = None
    client = TestClient(app)
    r = client.post("/gloss", json={"text": "감사합니다 여러분"}).json()
    assert r["mode"] == "word" and r["glosses"] == ["감사"]
    # 영상 파일이 없으면 url은 None (Viewer가 글자 카드로 바로 넘어감)
    media = main.MEDIA_ROOT / "sample" / "감사.mp4"
    expected = "/media/sample/감사.mp4" if media.is_file() else None
    assert r["clips"][0]["url"] == expected
    assert client.get("/").status_code == 200


def test_broadcast_reaches_viewer(conn):
    client = TestClient(app)
    with client.websocket_connect("/ws/viewer") as ws:
        r = client.post("/broadcast", json={"text": "안녕하세요"}).json()
        assert r["sent"] == 1
        assert ws.receive_json() == {"type": "text", "text": "안녕하세요"}
    assert client.post("/broadcast", json={"text": "  "}).json()["sent"] == 0
    assert client.get("/qr.svg").headers["content-type"].startswith("image/svg")
    assert client.get("/console").status_code == 200
    assert client.get("/viewer").status_code == 200


def test_word_match_rejects_partial_nouns():
    from app.translate import Lexicon
    lx = Lexicon({"손", "날", "예배", "시작", "아프다", "가다", "보다", "날다"}, {})
    assert lx.match_word("손님") is None          # 손 + 님 은 조사가 아님
    assert lx.match_word("손을") == "손"
    assert lx.match_word("날씨가") is None
    assert lx.match_word("시작하겠습니다") == "시작"
    assert lx.match_word("아프세요") == "아프다"
    assert lx.match_word("가고") == "가다"
    assert lx.match_word("보여") == "보다"


def test_sample_ingest_is_idempotent(conn):
    ingest.cmd_sample(conn, None)
    ingest.cmd_sample(conn, None)
    conn.commit()
    freqs = {r["frequency"] for r in conn.execute("select frequency from sentences where source='sample'")}
    assert freqs == {1}
    assert conn.execute("select count(*) as n from clips where source='sample'").fetchone()["n"] == 34


def test_clip_url_only_when_file_exists(conn, tmp_path, monkeypatch):
    import app.main as main
    ingest.cmd_sample(conn, None)
    conn.commit()
    main._lexicon = None
    monkeypatch.setattr(main, "MEDIA_ROOT", tmp_path)
    client = TestClient(app)
    assert client.post("/gloss", json={"text": "감사합니다"}).json()["clips"][0]["url"] is None
    (tmp_path / "sample").mkdir()
    (tmp_path / "sample" / "감사.mp4").write_bytes(b"x")
    assert client.post("/gloss", json={"text": "감사합니다"}).json()["clips"][0]["url"] == "/media/sample/감사.mp4"


def test_demo_sentences_match_exactly(conn):
    from app.translate import translate
    ingest.cmd_demo(conn, None)
    conn.commit()
    r = translate(conn, "천천히 말해 주세요")
    assert r["mode"] == "sentence" and r["glosses"] == ["천천히", "말하다", "부탁"]
    # 음성인식이 띄어쓰기를 다르게 해도 문장 일치로 잡는다
    r = translate(conn, "화장실이 어디에있어요")
    assert r["mode"] == "sentence" and r["glosses"] == ["화장실", "어디", "있다", "질문"]
    n = conn.execute("select count(*) as n from sentences where source='demo'").fetchone()["n"]
    assert n == 30
