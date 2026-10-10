"""한국어 문장 → gloss 순서열.

1) DB에 같은 문장이 있으면 그 gloss를 그대로 쓴다 (상황별 자주 쓰는 문장).
2) 없으면 어절마다 gloss를 찾는다.
   - gloss_aliases 정확 일치
   - gloss 표기 + 조사/하다 ('예배를', '시작하겠습니다' → 예배, 시작). 남는 부분이 조사가 아니면 버린다 ('손님' ≠ 손).
   - '다'로 끝나는 용언 gloss는 어간 + 어미로 비교 ('아프세요' → 아프다)
   못 찾은 어절은 unknown으로 남긴다 (나중에 지문자/AI Agent로 처리).
"""
from dataclasses import dataclass, field

from app import db
from app.textnorm import normalize

# 체언 뒤에 붙는 조사(+서술격). 긴 것부터 비교할 필요는 없다: 남는 부분 전체가 이 집합에 있어야 한다.
JOSA = {
    "은", "는", "이", "가", "을", "를", "에", "에서", "에게", "께", "께서", "한테", "의", "도", "만",
    "로", "으로", "와", "과", "랑", "이랑", "하고", "부터", "까지", "보다", "처럼", "요",
    "이다", "입니다", "이에요", "예요", "이야", "야", "이고", "에는", "에서는", "으로는", "로는", "에도",
}
# 어간 뒤에 오는 어미의 첫 글자. 어간이 한 글자일 때 '날씨'→날다 같은 오매칭을 막는다.
ENDING_HEADS = set("세시셔셨아어았었여였겠고는니면자지기러려며게도요습ㅂ으은을")
# '시작하겠습니다', '기도해요'처럼 명사 + 하다 활용
HADA_HEADS = set("하해했합할한함")


@dataclass
class Lexicon:
    labels: set[str]
    aliases: dict[str, str]
    stems: dict[str, str] = field(default_factory=dict)   # 어간 → gloss

    def __post_init__(self):
        for label in self.labels:
            if label.endswith("다") and len(label) >= 2:
                self.stems.setdefault(label[:-1], label)

    @classmethod
    def load(cls, conn) -> "Lexicon":
        labels = {r["label"] for r in conn.execute("select label from glosses")}
        aliases = {
            r["alias"]: r["label"]
            for r in conn.execute(
                "select a.alias, g.label from gloss_aliases a join glosses g on g.id = a.gloss_id"
            )
        }
        return cls(labels, aliases)

    def match_word(self, word: str) -> str | None:
        if word in self.aliases:
            return self.aliases[word]
        if word in self.labels:
            return word
        for n in range(len(word) - 1, 0, -1):
            prefix, rest = word[:n], word[n:]
            if prefix in self.labels and (rest in JOSA or rest[0] in HADA_HEADS):
                return prefix
            if prefix in self.stems and (len(prefix) >= 2 or rest[0] in ENDING_HEADS):
                return self.stems[prefix]
        return None


def translate(conn, text: str, lexicon: Lexicon | None = None) -> dict:
    labels = db.glosses_for_text(conn, text)
    if labels is not None:
        return {"mode": "sentence", "glosses": labels, "unknown": []}
    lexicon = lexicon or Lexicon.load(conn)
    glosses, unknown = [], []
    for word in normalize(text).split():
        label = lexicon.match_word(word)
        if label:
            glosses.append(label)
        else:
            unknown.append(word)
    return {"mode": "word" if glosses else "none", "glosses": glosses, "unknown": unknown}
