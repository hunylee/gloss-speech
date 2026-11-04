"""한국어 문장 → 수어 gloss.

순서 (노트의 Text to Gloss 블록):
  1) 상위 문장 10개 검색 → Top-1이 충분히 비슷하면 검수된 gloss 템플릿 사용 (mode=template)
  2) 아니면 규칙 번역 (mode=rules)
     - 자유 옵션 입력(세션 용어: 설교 제목, 인명, 본문 등) → 먼저 치환, 등록 gloss 없으면 지문자(FS:)
     - 여러 어절 표현 → 어절 사전(체언+조사, 용언 어간+어미) → 못 찾으면 지문자(FS:)
     - 같은 표기의 뜻이 상황마다 다르면: 현재 상황 > Top-10 문맥 gloss > 기본값
  3) 신뢰도가 낮으면 AI Agent(선택)가 Top-10을 예시로 다시 쓰고, 어휘 밖 결과는 버린다 (mode=agent)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.corpus import Corpus, LexEntry, normalize
from app.retrieve import Hit, Retriever, fill_numbers

TEMPLATE_MIN = 0.86      # 이 이상이면 검수 문장 템플릿을 그대로 쓴다
TEMPLATE_SOFT = 0.72     # STT 오류로 점수가 떨어져도, 2등과 차이가 크면 템플릿 사용 (harness dev로 보정)
TEMPLATE_MARGIN = 0.10
AGENT_MIN = 0.67         # 규칙 번역 신뢰도가 이보다 낮으면 Agent에게 넘긴다

JOSA = {
    "은", "는", "이", "가", "을", "를", "에", "에서", "에게", "께", "께서", "한테", "의", "도", "만",
    "로", "으로", "와", "과", "랑", "이랑", "하고", "부터", "까지", "보다", "처럼", "요", "이다",
    "입니다", "이에요", "예요", "에는", "에서는", "으로는", "로는", "에도", "께서는", "으로써", "이며",
    "들", "들은", "들을", "들이", "들의", "님", "님의", "님께", "님께서", "님은", "님이", "이나", "나",
    "인데", "이고", "이며", "이지만", "이었고", "이었다", "였다", "였고", "이에", "에서도", "에게서", "으로서", "로서",
}
ENDING_HEADS = set("세시셔셨아어았었여였겠고는니면자지기러려며게도요습ㅂ으은을ㄴ나냐네")
HADA_HEADS = ("하", "해", "했", "합", "할", "한", "함", "드", "되", "됩", "됐", "돼")
NOUN_TAIL_HEADS = set("이입으에을를은는과와의도로")   # 체언 뒤 조사·서술격의 첫 글자 (오인식된 꼬리 허용)
IMPERATIVE = ("십시오", "세요", "소서")
QUESTION_END = re.compile(r"(\?|까요?|나요|가요|니까|습니까|ㄹ까)\s*$")
NUM_SPLIT = re.compile(r"(\d+)")


_KIWI = None


def kiwi():
    """한국어 형태소 분석기(kiwipiepy). 설치돼 있지 않으면 None → 기존 규칙만 사용."""
    global _KIWI
    if _KIWI is None:
        try:
            from kiwipiepy import Kiwi
            _KIWI = Kiwi()
        except Exception:
            _KIWI = False
    return _KIWI or None


SKIP_TAGS = ("J", "E", "S", "XSV", "XSA", "XSN", "XPN", "VCP", "IC")
SKIP_NNB = {"것", "수", "번", "등", "거", "데", "줄", "뿐", "중", "게", "바", "분"}
NEG_VX = {"않": ["아니다"], "못하": ["못하다"], "말": ["아니다"]}
LIGHT_VV = {"하", "되", "드리"}           # 뜻이 앞 명사에 있는 가벼운 동사는 버린다

ENDINGS = re.compile(r"^(습니다|습니까|ㅂ니다|니다|어요|아요|다|요|고|며|면|겠습니다|겠습니까)$")


def _droppable_tail(frag: str) -> bool:
    return frag in JOSA or bool(ENDINGS.match(frag)) or frag.startswith(HADA_HEADS)


def _jamo(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch) - 0xAC00
        if 0 <= c < 11172:
            out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)] + ([chr(0x11A7 + c % 28)] if c % 28 else [])
        else:
            out.append(ch)
    return "".join(out)


def _edit(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _template_supported(template: list[str], rules: list[str]) -> bool:
    """템플릿이 '말하지 않은 뜻'을 넣지 않는지 확인한다.
    - 입력에서 알아들은 gloss가 템플릿에 없으면 다른 문장이다 (예: 둘째 독서 ≠ 첫째 독서).
    - 템플릿에만 있는 gloss는 STT가 망가뜨린 어절(FS:) 수만큼만 허용한다 (말한 것의 복원만 허용)."""
    soft = {"부탁", "바라다"}                       # 명령·기원 어미에서 나온 표지는 서로 바꿔 써도 같은 뜻
    known = [g for g in rules if not g.startswith("FS:") and not (g in soft and soft & set(template))]
    garbled = len(rules) - len(known)
    if any(g not in template for g in known):
        return False
    extra = [g for g in template if g not in known]
    # 템플릿 속 지문자(성경 책 이름 등)는 이번 주 입력에도 똑같이 있어야 한다 (요한복음 ≠ 마태복음)
    if any(g.startswith("FS:") and g not in rules for g in extra):
        return False
    return len(extra) <= garbled


@dataclass
class GlossResult:
    text: str
    glosses: list[str]
    mode: str                         # verified | template | rules | agent
    confidence: float
    question: bool = False
    unknown: list[str] = field(default_factory=list)
    context: list[dict] = field(default_factory=list)   # Top-10 (문장, 점수)

    def as_dict(self) -> dict:
        return {"text": self.text, "glosses": self.glosses, "mode": self.mode,
                "confidence": round(self.confidence, 3), "question": self.question,
                "unknown": self.unknown, "context": self.context}


@dataclass
class Session:
    """현장 세션 설정. terms = 자유 옵션 입력 {표기: gloss 또는 ''(→ 지문자)}"""
    domain: str = "protestant"
    terms: dict[str, str] = field(default_factory=dict)
    order: int = 0                     # 예배 순서상 마지막으로 나간 문장 번호 (다음 문장 추천용)


class Translator:
    def __init__(self, corpus: Corpus, agent=None):
        self.corpus = corpus
        self.retriever = Retriever(corpus)
        self.agent = agent

    # ---------- 공개 API ----------
    def translate(self, text: str, session: Session) -> GlossResult:
        key = normalize(text)
        question = bool(QUESTION_END.search(text.strip()))
        hits = self.retriever.top_k(key, session.domain, 10)
        context = [{"text": h.phrase.text, "gloss": " ".join(h.phrase.gloss),
                    "domain": h.phrase.domain, "score": round(h.score, 3)} for h in hits]

        rules_g, unknown, conf = self._rules(key.replace("?", " ").strip(), session, hits)
        confident = hits and (hits[0].score >= TEMPLATE_MIN or (
            hits[0].score >= TEMPLATE_SOFT and hits[0].phrase.domain in (session.domain, "common")
            and hits[0].score - (hits[1].score if len(hits) > 1 else 0) >= TEMPLATE_MARGIN))
        if confident and not self._has_session_term(key, session):
            filled = fill_numbers(hits[0].phrase.text, hits[0].phrase.gloss, key)
            if filled is not None and _template_supported(filled, rules_g):
                g = filled + (["?"] if question and "?" not in filled else [])
                return GlossResult(text, g, "template", hits[0].score, question, [], context)

        glosses = list(rules_g)
        if question:
            glosses.append("?")
        result = GlossResult(text, glosses, "rules", conf, question, unknown, context)

        if self.agent is not None and conf < AGENT_MIN:
            refined = self.agent.refine(text, session.domain, glosses, hits, self.allowed_vocab(session))
            if refined:
                result = GlossResult(text, refined, "agent", max(conf, 0.7), question, unknown, context)
        return result

    def allowed_vocab(self, session: Session) -> set[str]:
        extra = {g for v in session.terms.values() for g in v.split()} | {f"FS:{k}" for k in session.terms}
        return self.corpus.vocab | extra | {"?"}

    # ---------- 규칙 번역 ----------
    @staticmethod
    def _has_session_term(key: str, session: Session) -> bool:
        return any(t in key for t in session.terms)

    def _rules(self, key: str, session: Session, hits: list[Hit]):
        ctx = {g for h in hits for g in h.phrase.gloss}
        chunks: list = [key]                                   # str 또는 (gloss list,)

        def replace(surface: str, gloss: list[str]):
            """표현을 gloss로 치환. 바로 뒤에 붙은 조각이 조사·어미면 함께 지우고,
            다른 말이 붙어 있으면('다음 주' + '일') 치환하지 않는다."""
            out = []
            for c in chunks:
                if not isinstance(c, str):
                    out.append(c)
                    continue
                rest, buf = c, ""
                while surface in rest:
                    i = rest.index(surface)
                    after = rest[i + len(surface):]
                    frag = after.split(" ", 1)[0]
                    if frag and not _droppable_tail(frag):
                        if self._match_word(frag, session.domain, ctx) is not None:
                            # '다음 주예배는'처럼 띄어쓰기만 붙은 경우: 표현을 치환하고 뒤 어절은 따로 둔다
                            if buf + rest[:i]:
                                out.append(buf + rest[:i])
                            out.append((gloss,))
                            buf, rest = "", " " + after
                            continue
                        buf += rest[:i + len(surface)]
                        rest = after
                        continue
                    if buf + rest[:i]:
                        out.append(buf + rest[:i])
                    out.append((gloss,))
                    buf, rest = "", after[len(frag):]
                if buf + rest:
                    out.append(buf + rest)
            chunks[:] = out

        for term, g in sorted(session.terms.items(), key=lambda kv: -len(kv[0])):
            replace(term, g.split() if g.strip() else [f"FS:{term}"])
        for e in self._mwe_for(session.domain):
            replace(e.surface, e.gloss)
            if " " in e.surface:                      # STT가 띄어쓰기를 붙여 버린 경우
                replace(e.surface.replace(" ", ""), e.gloss)

        glosses, unknown, known, total = [], [], 0, 0
        for c in chunks:
            if isinstance(c, tuple):
                glosses += c[0]
                known += 1 if c[0] else 0
                total += 1 if c[0] else 0
                continue
            for word in NUM_SPLIT.sub(r" \1 ", c).split():
                if word.isdigit():
                    glosses.append(word); known += 1; total += 1
                    continue
                g = self._match_word(word, session.domain, ctx)
                if g is None:
                    g = self._segment(word, session.domain, ctx, allow_fs=False)  # 붙어 버린 어절 나누기
                if g is None:
                    g = self._fuzzy(word, session.domain, ctx)     # STT 오인식 보정 (자모 1~2개 차이)
                    if g is not None:
                        known += 0.5; total += 1; glosses += g
                        continue
                if g is None:
                    k = self._kiwi(word, session.domain, ctx)      # 형태소 분석: 활용형 → 원형
                    if k is not None:
                        kg, k_known, k_unk = k
                        glosses += kg
                        known += k_known; total += k_known + len(k_unk)
                        unknown += k_unk
                        if word.endswith(IMPERATIVE) and "부탁" not in kg:
                            glosses.append("부탁")
                        continue
                if g is None:
                    g = self._segment(word, session.domain, ctx)   # 모르는 뒷부분은 지문자로
                    stem = self._strip_josa(word)
                    glosses.append(f"FS:{stem}")
                    unknown.append(word); total += 1
                    continue
                if g:
                    known += 1; total += 1
                glosses += g
                if word.endswith(IMPERATIVE) and "부탁" not in g:
                    glosses.append("부탁")
        glosses = [g for i, g in enumerate(glosses) if i == 0 or g != glosses[i - 1]]
        conf = known / total if total else 0.0
        return glosses, unknown, conf

    def _mwe_for(self, domain: str) -> list[LexEntry]:
        return [e for e in self.corpus.mwe if e.domain in ("*", domain)]

    def _pick(self, cands: list[LexEntry], domain: str, ctx: set[str]) -> list[str]:
        for e in cands:
            if e.domain == domain:
                return e.gloss
        generic = [e for e in cands if e.domain == "*"]
        for e in generic + cands:
            if e.gloss and all(g in ctx for g in e.gloss):
                return e.gloss
        return (generic or cands)[0].gloss

    def _match_word(self, word: str, domain: str, ctx: set[str]) -> list[str] | None:
        lex = self.corpus.by_surface
        if word in lex:
            cands = [e for e in lex[word] if e.domain in ("*", domain)] or lex[word]
            return self._pick(cands, domain, ctx)
        for n in range(len(word) - 1, 0, -1):
            prefix, rest = word[:n], word[n:]
            if prefix not in lex:
                continue
            ok = []
            for e in lex[prefix]:
                if e.domain not in ("*", domain):
                    continue
                if e.kind == "n" and (rest in JOSA or (rest.startswith(HADA_HEADS) and rest not in lex)):
                    ok.append(e)
                elif e.kind == "v" and (len(prefix) >= 2 or rest[0] in ENDING_HEADS):
                    ok.append(e)
            if ok:
                return self._pick(ok, domain, ctx)
        return None

    def _segment(self, word: str, domain: str, ctx: set[str], depth: int = 0,
                 allow_fs: bool = True) -> list[str] | None:
        """'지금부터법회를' → '지금부터' + '법회를'. 왼쪽을 길게 잡는 순서로 최대 3조각."""
        if depth > 1 or len(word) < 3:
            return None
        for k in range(len(word) - 1, 0, -1):
            left = self._match_word(word[:k], domain, ctx)
            if left is None:
                continue
            right = self._match_word(word[k:], domain, ctx)
            if right is None:
                right = self._segment(word[k:], domain, ctx, depth + 1, allow_fs)
            if right is not None and (left or right):
                return left + right
        if depth == 0 and allow_fs:
            # 오른쪽이 사전에 없는 말이면(성경 책 이름·인명 등) 버리지 말고 지문자로 남긴다
            for k in range(len(word) - 2, 1, -1):
                left = self._match_word(word[:k], domain, ctx)
                if left:
                    return left + [f"FS:{self._strip_josa(word[k:])}"]
        return None

    def _kiwi(self, word: str, domain: str, ctx: set[str]):
        """어절을 형태소로 나눠 체언·용언 원형을 사전과 맞춘다.
        반환: (gloss 목록, 사전에서 찾은 개수, 못 찾은 원형 목록) / 분석기 없으면 None"""
        kw = kiwi()
        if kw is None:
            return None
        if not getattr(self, "_kiwi_words", False):            # 성경 책 이름·고유명사가 쪼개지지 않게
            for e in self.corpus.lexicon:
                if e.kind == "n" and len(e.surface) >= 2 and e.gloss and e.gloss[0].startswith("FS:"):
                    kw.add_user_word(e.surface, "NNP")
            self._kiwi_words = True
        toks = [(t.form, t.tag) for t in kw.tokenize(word)]
        out, known, unk = [], 0, []
        i = 0
        while i < len(toks):
            form, tag = toks[i]
            if tag == "NP" and i + 1 < len(toks) and toks[i + 1] == ("들", "XSN"):
                form, i = form + "들", i + 1                          # 그+들 → 그들
            i += 1
            if tag.startswith(SKIP_TAGS) or (tag == "NNB" and form in SKIP_NNB):
                continue
            if tag == "VCN":                                          # 아니다
                out.append("아니다"); known += 1; continue
            if tag == "SN":
                out.append(form); known += 1; continue
            if tag == "VV" and form in LIGHT_VV:
                continue
            if tag == "MAG" and form == "못":
                out.append("못하다"); known += 1; continue
            if tag == "VX":                                           # 보조용언: 부정만 남긴다
                if form in NEG_VX:
                    out += NEG_VX[form]; known += 1
                continue
            g = self._match_word(form, domain, ctx)
            if g is None and tag in ("VV", "VA"):
                g = self._match_word(form + "다", domain, ctx)
                if g is None and form + "다" in self.corpus.vocab:
                    g = [form + "다"]
            if g is None and tag.startswith("N") and form in self.corpus.vocab:
                g = [form]
            if g is not None:
                out += g; known += 1 if g else 0
                continue
            if tag in ("MM", "MAJ"):                                  # 모르는 관형사·접속부사는 버린다
                continue
            lemma = form + "다" if tag in ("VV", "VA") else form
            out.append(f"FS:{lemma}"); unk.append(lemma)
        return out, known, unk

    def _fuzzy(self, word: str, domain: str, ctx: set[str]) -> list[str] | None:
        """사전에 없는 어절을 자모 편집거리로 가장 가까운 표기에 맞춘다.
        2음절 표기는 자모 1개, 3음절 이상은 2개까지 허용. 1음절 표기는 오매칭이 많아 제외.
        후보는 Top-10 문맥 문장에 나온 gloss로만 제한한다 ('자리'→'자비' 같은 엉뚱한 보정 방지)."""
        stem = self._strip_josa(word)
        cands = [stem]
        if stem == word:                                   # 조사 대신 어미가 붙은 경우: 앞부분만 비교
            cands += [word[:n] for n in range(len(word) - 1, 1, -1)]
        best = None
        for c in cands:
            if len(c) < 2:
                continue
            jc = _jamo(c)
            for surface, entries in self.corpus.by_surface.items():
                if len(surface) < 2 or len(surface) != len(c) or (not entries[0].gloss and len(c) < 4):
                    continue
                d = _edit(jc, _jamo(surface), 2)
                limit = 1 if (len(surface) == 2 or not entries[0].gloss) else 2   # 버리는 말로는 1개 차이만
                if d <= limit and (best is None or d < best[0]):
                    ok = [e for e in entries if e.domain in ("*", domain) and all(g in ctx for g in e.gloss)]
                    rest = word[len(c):]
                    if ok and (c == stem or ok[0].kind == "v" or rest[:1] in NOUN_TAIL_HEADS):
                        best = (d, self._pick(ok, domain, ctx))
            if best:
                return best[1]
        return None

    @staticmethod
    def _strip_josa(word: str) -> str:
        for n in range(1, len(word)):
            if word[n:] in JOSA:
                return word[:n]
        return word
