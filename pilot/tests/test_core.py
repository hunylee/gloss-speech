import asyncio
import pytest
from fastapi.testclient import TestClient

from app.agent import validate
from app.corpus import Corpus
from app.gloss import Session, Translator
from app.main import create_app
from app.planner import RoomClock, plan

C = Corpus.load()
T = Translator(C)


def tr(text, domain="protestant", **kw):
    return T.translate(text, Session(domain=domain, **kw))


def test_fixed_sentence_uses_verified_template():
    r = tr("찬송가 364장을 함께 부르겠습니다.")
    assert r.mode == "template" and r.glosses == ["찬송가", "364", "장", "함께", "노래"]


def test_template_never_adds_unspoken_meaning():
    # '둘째'를 말했는데 '첫째' 템플릿이 쓰이면 안 된다
    # '지금부터'를 말하지 않았으면 '지금'이 들어가면 안 된다
    assert "지금" not in tr("예배를 시작하겠습니다.").glosses
    # 찬송가 장 번호는 말한 번호로
    assert "364" in tr("찬송가 364장을 함께 부르겠습니다.").glosses


def test_inactive_domains_are_hidden():
    assert set(C.domains) == {"protestant", "common"}
    assert all(p.domain in C.domains for p in C.phrases)


def test_bible_reference_keeps_spoken_book_and_numbers():
    r = tr("성경 봉독은 마태복음 5장 3절 말씀입니다.")
    assert "FS:마태복음" in r.glosses and "FS:요한복음" not in r.glosses
    assert ["5", "장", "3", "절"] == r.glosses[r.glosses.index("5"):r.glosses.index("절") + 1]
    r = tr("성경 봉독은 요한복음 1장 1절 말씀입니다.")
    assert r.mode == "template" and r.glosses[3:7] == ["1", "장", "1", "절"]


def test_free_option_terms_become_fingerspelling():
    r = tr("오늘 본문은 요한복음입니다.", terms={"요한복음": ""})
    assert "FS:요한복음" in r.glosses


def test_merged_words_from_stt_are_split():
    assert tr("지금부터예배를 시작하겠습니다").glosses == ["지금", "예배", "시작"]


def test_question_marker():
    assert tr("다음 주에 성경 공부가 있나요?").glosses[-1] == "?"


def test_agent_guardrail_rejects_out_of_vocab():
    assert validate(["로켓", "우주선", "XYZ"], C.vocab, ["예배"]) is None
    assert validate(["예배", "시작"], C.vocab, ["예배", "FS:시작"]) == ["예배", "시작"]


def test_planner_fallbacks():
    items = plan(["예배", "FS:요한", "삼귀의", "300", "?"], C.clips)
    assert [i.kind for i in items] == ["clip", "fingerspell", "card", "number", "marker"]


def test_backlog_policy():
    c = RoomClock()
    assert c.schedule(5000, 0)["rate"] == 1.0
    assert c.schedule(5000, 1)["rate"] == 1.25          # 4초 밀림 → 배속
    c.schedule(5000, 1.1)
    assert c.schedule(1000, 1.2)["flush"] is True       # 8초 넘게 밀림 → 밀린 수어 건너뜀


def test_end_to_end_websocket_broadcast():
    app = create_app(C)
    client = TestClient(app)
    with client.websocket_connect("/ws/viewer?room=t") as v:
        r = client.post("/api/rooms/t/text", json={"text": "헌금 시간입니다."})
        assert r.status_code == 200
        cap = v.receive_json(); sign = v.receive_json()
        assert cap["type"] == "caption.final" and sign["type"] == "sign"
        assert sign["glosses"] == ["헌금", "시간"] and sign["seq"] == cap["seq"] + 1
