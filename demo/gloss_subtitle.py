"""Demo: Korean sentence -> 농인 자막 (KSL gloss sequence + non-manual question marker).

Usage:
  python3 demo/gloss_subtitle.py "영등포로 가려면 어떻게 가나요?"
  python3 demo/gloss_subtitle.py            # interactive, one sentence per line
  python3 demo/gloss_subtitle.py --eval     # leave-one-out accuracy on the GKSL pairs

ponytail: nearest-neighbour retrieval over 3,052 GKSL pairs + a word lexicon fallback.
Ceiling: only covers sentences close to the corpus (transport/airport/daily/emergency);
upgrade path is a seq2seq model (Korean -> gloss) trained on the same pairs.
"""
import collections
import csv
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "aihub")
GKSL = os.path.join(ROOT, "external", "GKSL-dataset", "dataset", "GKSL3k_original.csv")
WORDS = os.path.join(ROOT, "clean", "ksl_gloss_word_aihub.jsonl")
MATCH_MIN = 0.45  # calibration knob: below this similarity, fall back to the word lexicon
PARTICLES = sorted({"입니다", "이에요", "예요", "에서", "으로", "에게", "까지", "부터", "을", "를", "이", "가",
                    "은", "는", "에", "로", "도", "의", "요", "이요", "에요", "한테", "랑", "와", "과", "만"},
                   key=len, reverse=True)  # longest first
WH = ("어디", "언제", "누구", "무엇", "뭐", "왜", "어떻게", "몇")
NOT_WH = ("든지", "든", "라도", "이나", "나")  # 어디든, 뭐라도, 언제나: indefinite, not a question


def load_pairs():
    with open(GKSL, encoding="utf-8-sig") as f:
        return [{"korean": r["Word level Korean Language (WKL) sentence"].strip(),
                 "gloss": r["Gloss level Korean Sign Language (GKSL) sentence"].split(),
                 "question": r["question"] == "TRUE", "src": r["dataset"]} for r in csv.DictReader(f)]


def load_lexicon(pairs):
    vocab = {g for p in pairs for g in p["gloss"]}
    if os.path.exists(WORDS):
        vocab |= {json.loads(l)["gloss_text"] for l in open(WORDS, encoding="utf-8")}
    return vocab


def ngrams(text, n=2):
    t = re.sub(r"[^\w]", "", text)
    return collections.Counter(t[i:i + n] for i in range(max(1, len(t) - n + 1)))


def similarity(a, b):
    inter = sum((a & b).values())
    return 2 * inter / (sum(a.values()) + sum(b.values()) or 1)  # Dice over char bigrams


def jong(ch):
    """Final consonant index of a Hangul syllable (0 = none, 8 = ㄹ, 17 = ㅂ)."""
    return (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else -1


def question_ending(word):
    if word.endswith("니까"):  # 습니까/ㅂ니까 asks; 오니까/하니까 means "because"
        return word.endswith("습니까") or (len(word) > 2 and jong(word[-3]) == 17)
    if word.endswith("으니"):
        return False
    return (word.endswith(("나요", "까요", "니", "냐", "래요"))
            or (word.endswith("까") and len(word) > 1 and jong(word[-2]) == 8))  # ㄹ까: 갈까


def wh_word(word):
    for wh in WH:
        if word.startswith(wh):
            rest = word[len(wh):]
            return rest == "" or (not rest.startswith(NOT_WH) and rest in PARTICLES)
    return False


def is_question_text(text):
    """'?' -> question; ends with '.'/'!' -> statement; else question ending or wh-word (speech has no punctuation)."""
    t = text.strip()
    if "?" in t:
        return True
    if t.endswith((".", "!")):
        return False
    words = re.findall(r"\w+", t)
    return bool(words) and (question_ending(words[-1]) or any(wh_word(w) for w in words))


def lexicon_gloss(text, vocab):
    out = []
    for w in re.findall(r"[\w]+", text):
        cand = w
        for _ in range(4):  # original + up to 3 strips, longest suffix first
            if cand in vocab or cand + "다" in vocab:
                out.append(cand if cand in vocab else cand + "다")
                break
            p = next((p for p in PARTICLES if cand.endswith(p) and len(cand) > len(p)), None)
            if not p:
                break
            cand = cand[:-len(p)]
    return out


def translate(text, pairs, vocab, index=None, skip=None):
    index = index or [ngrams(p["korean"]) for p in pairs]
    q = ngrams(text)
    best, score = None, 0.0
    for i, (p, g) in enumerate(zip(pairs, index)):
        if i == skip:
            continue
        s = similarity(q, g)
        if s > score:
            best, score = p, s
    if best and score >= MATCH_MIN:
        return {"gloss": best["gloss"], "question": is_question_text(text) if re.search(r"[?.!]\s*$", text) else best["question"],
                "method": "retrieval", "score": round(score, 2), "matched": best["korean"]}
    return {"gloss": lexicon_gloss(text, vocab), "question": is_question_text(text),
            "method": "lexicon", "score": round(score, 2), "matched": None}


def subtitle(res):
    body = " · ".join(res["gloss"]) or "(gloss 없음)"
    return f"{body}  〔의문 표정〕" if res["question"] else body


def evaluate(pairs, vocab):
    index = [ngrams(p["korean"]) for p in pairs]
    exact = q_ok = retrieved = 0
    for i, p in enumerate(pairs):
        r = translate(p["korean"], pairs, vocab, index, skip=i)
        exact += r["gloss"] == p["gloss"]
        q_ok += r["question"] == p["question"]
        retrieved += r["method"] == "retrieval"
    n = len(pairs)
    print(f"leave-one-out on {n} pairs: gloss exact {exact / n:.1%}, question flag {q_ok / n:.1%}, "
          f"retrieval used {retrieved / n:.1%}")


def main():
    pairs = load_pairs()
    vocab = load_lexicon(pairs)
    assert lexicon_gloss("지하철을 타다", {"지하철", "타다"}) == ["지하철", "타다"]
    assert similarity(ngrams("왼쪽입니다"), ngrams("왼쪽입니다")) == 1.0
    assert lexicon_gloss("왼쪽이요", {"왼쪽"}) == ["왼쪽"] and lexicon_gloss("공항에서요", {"공항"}) == ["공항"]
    for s in ("비가 오니까 우산을 챙기세요.", "어디든 괜찮아요.", "몇 번 말했어요.", "비가 오니까 우산을 챙기세요", "어디든 괜찮아요"):
        assert not is_question_text(s), s
    for s in ("화장실이 어디에 있나요", "어디 가", "같이 갈까", "밥 먹었니", "가십니까", "뭐 해요?", "누구세요?"):
        assert is_question_text(s), s
    if sys.argv[1:] == ["--eval"]:
        return evaluate(pairs, vocab)
    lines = sys.argv[1:] or (l.strip() for l in sys.stdin if l.strip())
    for text in lines:
        r = translate(text, pairs, vocab)
        print(f"한국어: {text}\n자막  : {subtitle(r)}\n        [{r['method']} {r['score']}"
              + (f" ≈ {r['matched']}" if r["matched"] else "") + "]\n")


if __name__ == "__main__":
    main()
