"""Claude 다듬기: refine a Korean sentence into KSL gloss via the logged-in Claude Code CLI (headless).

No API key handling: shells out to `claude -p ... --output-format json`.
ponytail: one CLI process per sentence (~5 s incl. startup). Upgrade path if latency matters:
a long-lived Messages API client with prompt caching.
"""
import json
import re
import subprocess
import tempfile
import time

from gloss_subtitle import ngrams, similarity

SKIP_AT = 0.86  # near-exact corpus match: the corpus gloss is already right, don't call Claude
TIMEOUT_S = 30
INSTRUCTIONS = (
    "너는 한국어 문장을 농인이 읽기 쉬운 한국수어(KSL) gloss 자막으로 바꾸는 변환기다. "
    "규칙: gloss는 수어 단어를 한국어 원형(가다, 먹다, 없다)으로 적고 수어 어순대로 배열한다. "
    "조사·어미·높임은 버린다. 시간 표현은 문장 앞, 의문사(어디, 무엇, 언제, 누구, 왜, 방법, 얼마)와 "
    "부정(아니다, 불가능, 없다)은 문장 끝. 고유명사·숫자는 그대로 두고 fingerspell에도 넣는다. "
    "의문문/부정문 여부는 비수지 신호로 따로 표시한다. 아래 말뭉치 예문의 gloss 어휘와 어순을 최대한 따른다."
)
OUTPUT_SPEC = 'JSON 하나만 출력: {"gloss": [...], "question": bool, "negation": bool, "time": str|null, "fingerspell": [...]}'


def nearest(text, pairs, index, k=8):
    q = ngrams(text)
    scored = sorted(((similarity(q, g), p) for p, g in zip(pairs, index)), key=lambda x: -x[0])
    return scored[:k]


def build_prompt(text, examples):
    lines = [f"- {p['korean']} → {' '.join(p['gloss'])} (의문: {'예' if p['question'] else '아니오'})" for _, p in examples]
    return f"{INSTRUCTIONS}\n\n말뭉치 예문:\n" + "\n".join(lines) + f"\n\n문장: {text}\n\n{OUTPUT_SPEC}"


def parse_result(text):
    """Pull the JSON object out of Claude's reply and validate it; None if unusable."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    gloss = d.get("gloss")
    if not (isinstance(gloss, list) and gloss and all(isinstance(g, str) and g.strip() for g in gloss)):
        return None
    fs = d.get("fingerspell") or []
    return {
        "gloss": [g.strip() for g in gloss],
        "question": bool(d.get("question")),
        "negation": bool(d.get("negation")),
        "time": d.get("time") if isinstance(d.get("time"), str) else None,
        "fingerspell": [f for f in fs if isinstance(f, str)] if isinstance(fs, list) else [],
    }


def refine(text, pairs, index):
    """Returns (result | None, info) where info has latency_ms and error/skipped."""
    examples = nearest(text, pairs, index)
    if examples and examples[0][0] >= SKIP_AT:
        return None, {"skipped": True, "score": round(examples[0][0], 2)}
    cmd = ["claude", "-p", "--output-format", "json", "--strict-mcp-config", "--no-session-persistence",
           "--effort", "low", "--tools", "", "--", build_prompt(text, examples)]
    t0 = time.monotonic()
    try:
        # cwd outside the project so no CLAUDE.md is picked up
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=tempfile.gettempdir())
    except FileNotFoundError:
        return None, {"error": "claude CLI not found"}
    except subprocess.TimeoutExpired:
        return None, {"error": "timeout", "latency_ms": TIMEOUT_S * 1000}
    ms = int((time.monotonic() - t0) * 1000)
    try:
        envelope = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None, {"error": "bad CLI output", "latency_ms": ms}
    if envelope.get("is_error"):
        return None, {"error": str(envelope.get("result"))[:200], "latency_ms": ms}
    res = parse_result(envelope.get("result"))
    return res, ({"latency_ms": ms} if res else {"error": "invalid JSON from Claude", "latency_ms": ms})


if __name__ == "__main__":
    assert parse_result('```json\n{"gloss": ["말", "하다"], "question": false}\n```')["gloss"] == ["말", "하다"]
    assert parse_result('{"gloss": []}') is None and parse_result("no json") is None
    assert parse_result('{"gloss": ["오늘", ""]}') is None
    print("ok")
