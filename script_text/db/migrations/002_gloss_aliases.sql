-- 002_gloss_aliases.sql
-- 단어(어절) → gloss 수동 매핑. 접두어 규칙으로 못 잡는 표현을 넣는다 (예: '감사합니다' → 감사).
create table if not exists gloss_aliases (
    alias       text primary key,              -- textnorm.normalize 결과
    gloss_id    bigint not null references glosses(id) on delete cascade
);
