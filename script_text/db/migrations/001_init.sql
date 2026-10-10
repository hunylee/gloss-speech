-- 001_init.sql
-- 문장 · gloss · 수어 클립 기본 스키마.
-- 표준 PostgreSQL 문법만 사용하므로 Supabase(SQL Editor 또는 supabase migration)로 그대로 옮길 수 있다.

-- 사용 상황 (병원, 교회, 관공서 ...). 상황별 자주 쓰는 문장을 뽑을 때 쓴다.
create table if not exists domains (
    id          serial primary key,
    code        text not null unique,          -- 'hospital', 'church' ...
    name_ko     text not null
);

-- 원문 문장. 모두의 말뭉치, AI Hub, 직접 입력한 문장이 모두 여기에 들어간다.
create table if not exists sentences (
    id              bigserial primary key,
    text            text not null,
    normalized_text text not null,             -- 공백·문장부호를 정리한 매칭용 키 (app/textnorm.py)
    source          text not null,             -- 'modu' | 'aihub' | 'manual' | 'sample'
    source_ref      text,                      -- 원본 파일명/문장 ID
    domain_id       int references domains(id),
    frequency       int not null default 1,    -- 같은 문장이 여러 번 나오면 누적
    created_at      timestamptz not null default now(),
    unique (normalized_text, source)
);
create index if not exists sentences_normalized_idx on sentences (normalized_text);
create index if not exists sentences_domain_freq_idx on sentences (domain_id, frequency desc);

-- 수어 gloss 어휘. label은 AI Hub 형태소 라벨과 같은 표기를 쓴다.
create table if not exists glosses (
    id          bigserial primary key,
    label       text not null unique,
    description text
);

-- 문장 → gloss 순서열.
create table if not exists sentence_glosses (
    sentence_id bigint not null references sentences(id) on delete cascade,
    position    int not null,
    gloss_id    bigint not null references glosses(id),
    primary key (sentence_id, position)
);

-- gloss별 수어 영상 클립. 파일 자체는 로컬(MEDIA_ROOT)에 두고 경로만 저장한다.
-- 원본 영상의 일부 구간이면 start_ms/end_ms로 자른다.
create table if not exists clips (
    id          bigserial primary key,
    gloss_id    bigint not null references glosses(id) on delete cascade,
    file_path   text not null,
    start_ms    int,
    end_ms      int,
    signer      text,
    source      text not null,
    created_at  timestamptz not null default now(),
    unique nulls not distinct (gloss_id, file_path, start_ms)   -- PG15+ (Supabase 포함)
);
create index if not exists clips_gloss_idx on clips (gloss_id);

-- 조회 편의 뷰: 문장별 gloss 배열.
create or replace view sentence_gloss_view as
select s.id as sentence_id,
       s.text,
       s.normalized_text,
       s.domain_id,
       s.frequency,
       array_agg(g.label order by sg.position) as glosses
from sentences s
join sentence_glosses sg on sg.sentence_id = s.id
join glosses g on g.id = sg.gloss_id
group by s.id;
