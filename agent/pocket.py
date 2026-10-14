"""학생별 '낱말 주머니'.

학생마다 아는 낱말 / 배우는 중인 낱말 / 모르는 낱말이 다르다. 글을 낱말(어절) 단위로 나눠
이 학생이 아는 낱말이 몇 % 인지, 새 낱말이 몇 개인지 잰다. 학생 반응(몰라요/맞혔어요)으로 주머니가 바뀐다.
"""

import re
from functools import lru_cache

from . import data
from .config import COVERAGE_MIN, KNOWN_AFTER_CORRECT, MAX_NEW_WORDS

_PUNCT = re.compile(r"[\s.,!?·…\"'“”‘’()\[\]{}:;~\-—]+")
_PARTICLES = sorted(["입니다", "이었어요", "였어요", "이다", "이고", "이라고", "라고", "이에요", "예요", "이야", "에서", "에게", "으로", "로", "을", "를", "이", "가",
                     "은", "는", "의", "에", "도", "와", "과", "하고", "이나", "나", "만", "까지", "부터"],
                    key=len, reverse=True)


@lru_cache(maxsize=1)
def _lexicon():
    exact, stems = {}, {}
    for band, items in data.lexicon()["bands"].items():
        for it in items:
            it = it.strip()
            if not it:
                continue
            if it.startswith("="):
                exact.setdefault(it[1:], int(band))
            else:
                stems.setdefault(it, int(band))
    core = {}
    for g in data.glossary():
        for f in g["forms"]:
            core[f] = g["word"]
    return exact, sorted(stems.items(), key=lambda kv: -len(kv[0])), core


_QUOTES = re.compile(r"[\"'“”‘’]")
_PAREN = re.compile(r"\([^)]*\)")


def tokens(text: str) -> list[str]:
    """글을 어절로 나눈다. 따옴표는 지우고(낱말을 쪼개지 않게), 괄호 속 풀이는 세지 않는다."""
    t = _PAREN.sub("", _QUOTES.sub("", text or ""))
    return [x for x in _PUNCT.split(t) if x and not x.isdigit()]


def _strip_particle(tok: str) -> str:
    for p in _PARTICLES:
        if tok.endswith(p) and len(tok) > len(p):
            return tok[: -len(p)]
    return tok


def _match(tok: str):
    exact, stems, core = _lexicon()
    if tok in exact:
        return tok, exact[tok]
    for stem, band in stems:
        if tok.startswith(stem):
            return stem, band
    return None


def lookup(tok: str) -> tuple[str, int | None]:
    """어절 → (낱말 이름, 난이도). 목록에 없으면 난이도 None."""
    m = _match(tok) or _match(_strip_particle(tok))
    return m if m else (_strip_particle(tok), None)


def is_core(word: str) -> bool:
    """오늘 배울 교과 핵심 용어인가 (바꾸지 않고 가르치는 낱말)."""
    return word in data.target_terms()


# ── 학생 주머니 상태 ─────────────────────────────────────────────

def _book(state, student_id: str) -> dict:
    return state.pocket.setdefault(student_id, {})


def status(state, student_id: str, word: str, band: int | None) -> str:
    rec = _book(state, student_id).get(word)
    if rec:
        return rec["status"]
    s = data.student(student_id)
    if word in s.get("known_extra", []):
        return "known"
    if band is not None and band <= s["vocab_band"] and not is_core(word):
        return "known"
    if band is not None and band <= s["vocab_band"] and is_core(word) and s["vocab_band"] >= 3:
        return "known"
    return "unknown"


def record(state, student_id: str, word: str, result: str) -> dict:
    book = _book(state, student_id)
    rec = book.setdefault(word, {"status": "unknown", "correct": 0})
    if result == "dont_know":
        rec.update(status="unknown", correct=0)
    elif result == "correct":
        rec["correct"] += 1
        rec["status"] = "known" if rec["correct"] >= KNOWN_AFTER_CORRECT else "learning"
    else:
        raise ValueError("result 는 'dont_know' 또는 'correct' 여야 합니다.")
    return {"word": word, **rec}


def summary(state, student_id: str) -> dict:
    exact, stems, _ = _lexicon()
    s = data.student(student_id)
    words = {w: b for w, b in list(exact.items()) + stems}
    # 물은/물이/물을 처럼 모양만 다른 것은 한 낱말로 센다
    known = len({_strip_particle(w) for w, b in words.items() if status(state, student_id, w, b) == "known"})
    book = _book(state, student_id)
    return {
        "known_count": known,
        "learning": {w: r["correct"] for w, r in book.items() if r["status"] == "learning"},
        "marked_unknown": [w for w, r in book.items() if r["status"] == "unknown"],
        "newly_known": [w for w, r in book.items() if r["status"] == "known"],
        "vocab_band": s["vocab_band"],
    }


def known_examples(state, student_id: str, limit: int = 150) -> list[str]:
    exact, stems, _ = _lexicon()
    out = []
    for w, b in stems + list(exact.items()):
        if len(out) >= limit:
            break
        if status(state, student_id, w, b) == "known" and not w.startswith("="):
            out.append(w)
    return out


def analyze(state, student_id: str, text: str) -> dict:
    toks = tokens(text)
    known, items = 0, []
    new, learning, core_new = [], [], []
    for t in toks:
        word, band = lookup(t)
        st = status(state, student_id, word, band)
        if st == "known":
            known += 1
        elif st == "learning":
            if word not in learning:
                learning.append(word)
        else:
            if word not in new:
                new.append(word)
                if is_core(word):
                    core_new.append(word)
        items.append({"token": t, "word": word, "status": st})
    total = len(toks) or 1
    cov = round(known / total * 100)
    passed = cov >= COVERAGE_MIN and len(new) <= MAX_NEW_WORDS
    # 고칠 계획: 핵심 용어가 아닌 새 낱말은 아는 말로 바꾸고, 핵심 용어는 중요한 순서로 기준 개수만 남긴다
    order = data.target_terms()
    core_sorted = sorted(core_new, key=lambda w: order.index(w) if w in order else 99)
    keep = core_sorted[:MAX_NEW_WORDS]
    return {"coverage": cov, "total_words": len(toks), "known_words": known, "new_words": new,
            "core_new_words": core_sorted, "learning_words": learning, "passed": passed,
            "words_to_replace": [w for w in new if not is_core(w)],
            "terms_to_keep": keep, "terms_to_defer": core_sorted[MAX_NEW_WORDS:],
            "known_list": list(dict.fromkeys(i["word"] for i in items if i["status"] == "known")), "items": items}
