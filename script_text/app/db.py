"""DB 접근 계층. 적재 스크립트와 API가 함께 쓴다."""
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.textnorm import normalize

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
DEFAULT_URL = "postgresql://speech:speech@localhost:5432/script_text"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


@contextmanager
def connect(url: str | None = None):
    with psycopg.connect(url or database_url(), row_factory=dict_row) as conn:
        yield conn


def migrate(conn) -> None:
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        conn.execute(sql_file.read_text(encoding="utf-8"))


# ---------- 쓰기 ----------

def upsert_domain(conn, code: str, name_ko: str) -> int:
    row = conn.execute(
        "insert into domains (code, name_ko) values (%s, %s) "
        "on conflict (code) do update set name_ko = excluded.name_ko returning id",
        (code, name_ko),
    ).fetchone()
    return row["id"]


def upsert_sentence(conn, text: str, source: str, *, source_ref=None, domain_id=None, count=True) -> int:
    """같은 (정규화 문장, 출처)가 다시 나오면 frequency를 올린다.
    count=False면 올리지 않는다 (샘플처럼 다시 적재해도 빈도가 바뀌면 안 되는 데이터)."""
    row = conn.execute(
        """
        insert into sentences (text, normalized_text, source, source_ref, domain_id)
        values (%s, %s, %s, %s, %s)
        on conflict (normalized_text, source) do update
            set frequency = sentences.frequency + %s,
                domain_id = coalesce(sentences.domain_id, excluded.domain_id)
        returning id
        """,
        (text.strip(), normalize(text), source, source_ref, domain_id, 1 if count else 0),
    ).fetchone()
    return row["id"]


def upsert_gloss(conn, label: str) -> int:
    row = conn.execute(
        "insert into glosses (label) values (%s) "
        "on conflict (label) do update set label = excluded.label returning id",
        (label.strip(),),
    ).fetchone()
    return row["id"]


def set_sentence_glosses(conn, sentence_id: int, labels: list[str]) -> None:
    conn.execute("delete from sentence_glosses where sentence_id = %s", (sentence_id,))
    for pos, label in enumerate(labels):
        conn.execute(
            "insert into sentence_glosses (sentence_id, position, gloss_id) values (%s, %s, %s)",
            (sentence_id, pos, upsert_gloss(conn, label)),
        )


def add_clip(conn, label: str, file_path: str, source: str, *, start_ms=None, end_ms=None, signer=None) -> None:
    conn.execute(
        """
        insert into clips (gloss_id, file_path, start_ms, end_ms, signer, source)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (gloss_id, file_path, start_ms) do nothing
        """,
        (upsert_gloss(conn, label), file_path, start_ms, end_ms, signer, source),
    )


# ---------- 읽기 ----------

def list_domains(conn) -> list[dict]:
    return conn.execute("select id, code, name_ko from domains order by id").fetchall()


def top_sentences(conn, domain_code: str | None = None, limit: int = 100) -> list[dict]:
    """상황별 자주 쓰는 문장 상위 N개 (gloss가 있는 문장만)."""
    return conn.execute(
        """
        select v.sentence_id, v.text, v.frequency, v.glosses, d.code as domain
        from sentence_gloss_view v
        left join domains d on d.id = v.domain_id
        where %(code)s::text is null or d.code = %(code)s
        order by v.frequency desc, v.sentence_id
        limit %(limit)s
        """,
        {"code": domain_code, "limit": limit},
    ).fetchall()


def glosses_for_text(conn, text: str) -> list[str] | None:
    """정확히 일치하는 문장의 gloss 순서열. 없으면 None (단어 단위 대체는 2단계)."""
    # 띄어쓰기는 무시하고 비교한다: 음성인식이 '어디에있어요'처럼 붙여 쓰는 경우가 있다
    row = conn.execute(
        "select glosses from sentence_gloss_view where replace(normalized_text, ' ', '') = %s "
        "order by frequency desc limit 1",
        (normalize(text).replace(" ", ""),),
    ).fetchone()
    return row["glosses"] if row else None


def clips_for_glosses(conn, labels: list[str]) -> list[dict]:
    """gloss 순서대로 대표 클립 하나씩. 클립이 없는 gloss는 file_path가 None."""
    rows = conn.execute(
        """
        select distinct on (g.label) g.label, c.file_path, c.start_ms, c.end_ms
        from glosses g
        left join clips c on c.gloss_id = g.id
        where g.label = any(%s)
        -- 실데이터(aihub) 단어 영상 > 문장 영상 구간 > 샘플 순으로 대표 클립을 고른다
        order by g.label, (c.source = 'aihub') desc, (c.file_path like '%%WORD%%') desc, c.id
        """,
        (labels,),
    ).fetchall()
    by_label = {r["label"]: r for r in rows}
    return [
        by_label.get(label, {"label": label, "file_path": None, "start_ms": None, "end_ms": None})
        for label in labels
    ]


def add_alias(conn, alias: str, label: str) -> None:
    conn.execute(
        "insert into gloss_aliases (alias, gloss_id) values (%s, %s) "
        "on conflict (alias) do update set gloss_id = excluded.gloss_id",
        (normalize(alias), upsert_gloss(conn, label)),
    )
