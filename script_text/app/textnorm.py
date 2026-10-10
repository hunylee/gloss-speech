"""문장 매칭용 정규화. DB의 sentences.normalized_text와 조회 시 같은 함수를 쓴다."""
import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip()
