"""Code check of an episode script against its guide text (step 1 of 2; free, no AI).

  python tools/check_script.py script.txt guide_source.txt [--speakers Will,Hannah] [--json]

Fails (exit 1) when the script
  * is not in the script format, or has the wrong sections / speakers / length / tags,
  * contains a year, a law-report citation or markup that a voice would read out,
  * uses a figure (number, amount, period, percentage, section number) that is not in the guide
    (or in the header's "invented" list),
  * uses a proper name (case, statute, person, place) that is not in the guide or "invented".
Small counting words (one to ten) with no unit are ignored. The check is deliberately strict; a
false alarm costs one rewrite, a missed error would cost far more. The AI check (step 2) judges meaning.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scriptfmt import ALLOWED_TAGS, TAG_RE, parse, strip_tags, tags_used, words  # noqa: E402

SECTIONS = ["rule", "exam mode", "recap"]
WORD_LIMITS = (1700, 5200)   # long enough to cover every main point; never padded
SECTION_WARN = {"rule": (500, 2600), "exam mode": (700, 2600), "recap": (70, 320)}
MAX_TAGS_PER_WORD = 1 / 80.0

UNITS = r"(?:days?|weeks?|months?|years?|hours?|minutes?|working|business|per|cent|percent|pounds?|pence|p|%)"
UNIT_RE = re.compile(r"^" + UNITS + r"$", re.I)

ONES = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALE = {"hundred": 100, "thousand": 1000, "million": 1000000}
NUMWORD = set(ONES) | set(TENS) | set(SCALE)

DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"}
ALLOWED_PROPER = DAYS | MONTHS | {"i", "i'm", "i'll", "i've", "i'd", "sqe", "sqe1", "english", "british", "britain", "england", "wales", "uk",
                                  "ok", "okay", "mr", "mrs", "ms", "miss", "dr", "sir", "dame", "lord", "lady"}
ALLOWED_CAPS = {"SQE", "SQE1", "UK", "OK", "I", "A", "AM", "PM", "TV", "VAT", "ID", "FLK1", "FLK2", "FLK"}
COMMON_STARTERS = set("""
a about above across actually after again against agreed ah aha all almost along already also although always
am an and another any anyone anything are around as at back basically be because been before behind being
below best better between both brilliant but by can careful carry certainly clearly come correct could crucially
did do does doesn down during each either else end enough essentially even ever every exactly fair finally
first for from frankly get give go going gone good got great had has have he hello her here hmm his hold honestly
how however huh i if important importantly in indeed inside instead interesting into is it its just keep kind
knows last lastly late lets like listen little long look lots lovely make many may maybe me mean might more most
much must my near need never next nice no nobody none nope nor not nothing notice now of off oh ok okay old
on once one only ooh or other ouch our out over own perfect phew picture plus precisely quite really remember
right sadly same say second see sense shall she should show simple simply since so some somebody someone
something sometimes sorry spot start still stop sure take tell than thank thanks that the their them then there
these they thing think third this those though three through thus time to today too total tricky try two under
unless until up us use used usually very wait want was watch we well went were what whatever when where whether
which while who whoever whole whose why will with within without wow would yeah yes yet you your
""".split())

_CW = Path(__file__).with_name("common_words.txt")
if _CW.exists():
    COMMON_STARTERS |= set(_CW.read_text(encoding="utf-8").split())

YEAR_RE = re.compile(r"\b(1[0-9]{3}|2[0-9]{3})\b")
CITE_RE = re.compile(r"\[\d{4}\]|\(\d{4}\)|\b(?:UKSC|UKHL|EWCA|EWHC|WLR|All ER|QBD|KBD|AC|QB|Ch|CLR|ECR)\b|"
                     r"\bat \[\d+\]")
MARKUP_RE = re.compile(r"[*_#\[\]{}|\\^~`=]|https?://|\bs\.\s?\d|\bss\.\s?\d")
NUM_RE = re.compile(r"£?\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?%?")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z']*|\d[\d,]*(?:\.\d+)?%?|£\d[\d,]*(?:\.\d+)?|[^\sA-Za-z\d]")


def words_to_int(tokens):
    """Value of a run of number words, or None."""
    total, cur, seen = 0, 0, False
    for t in tokens:
        t = t.lower()
        if t == "and":
            continue
        if t in ONES:
            cur += ONES[t]
        elif t in TENS:
            cur += TENS[t]
        elif t in SCALE:
            cur = max(cur, 1) * SCALE[t]
            if SCALE[t] >= 1000:
                total += cur
                cur = 0
        else:
            return None
        seen = True
    return total + cur if seen else None


def normalise(text):
    """Return text with number words turned into digits (so 'six months' == '6 months')."""
    text = re.sub(r"\ba (hundred|thousand|million)\b", r"one \1", text, flags=re.I)
    text = text.replace("-", " ")
    toks = re.findall(r"\S+|\s+", text)
    n = len(toks)

    def core(t):
        return t.lower().strip(".,;:!?()\"'\u201c\u201d\u2018\u2019")

    def next_real(j):
        j += 1
        while j < n and not toks[j].strip():
            j += 1
        return j

    out, i = [], 0
    while i < n:
        t = toks[i]
        if t.strip() and core(t) in NUMWORD:
            run, last, j = [], i, i
            while j < n:
                tj = toks[j]
                if not tj.strip():
                    j += 1
                    continue
                c = core(tj)
                if c in NUMWORD:
                    run.append(c)
                    last = j
                    if tj[-1] in ".,;:!?":
                        break
                    j += 1
                elif c == "and" and run and run[-1] in SCALE and next_real(j) < n and core(toks[next_real(j)]) in NUMWORD:
                    j += 1
                else:
                    break
            val = words_to_int(run)
            if val is not None:
                trailing = toks[last][-1] if toks[last][-1] in ".,;:!?)" else ""
                out.append(str(val) + trailing)
                i = last + 1
                continue
        out.append(t)
        i += 1
    return "".join(out)


def num_value(s):
    s = s.replace("£", "").replace(",", "").rstrip("%")
    s = re.sub(r"(st|nd|rd|th)$", "", s)
    try:
        v = float(s)
        return int(v) if v == int(v) else v
    except ValueError:
        return None


def _expand_suffixes(text):
    def rep(m):
        num = float(m.group(2).replace(",", ""))
        mult = {"k": 1000, "m": 1000000, "bn": 1000000000}[m.group(3).lower()]
        v = num * mult
        return "%s%d" % (m.group(1) or "", v) if v == int(v) else m.group(0)
    return re.sub(r"(£)?(\d[\d,]*(?:\.\d+)?)(k|m|bn)\b", rep, text, flags=re.I)


def figures(text, with_context=False):
    """Set of numeric values in text (digits and number words). Optionally (value, has_unit_or_pound)."""
    t = normalise(_expand_suffixes(text))
    vals = {}
    toks = t.split()
    for i, tok in enumerate(toks):
        core = tok.strip(".,;:!?()\"'")
        m = NUM_RE.fullmatch(core)
        if not m:
            continue
        v = num_value(core)
        if v is None:
            continue
        nxt = toks[i + 1].strip(".,;:!?()\"'") if i + 1 < len(toks) else ""
        prev = toks[i - 1].strip(".,;:!?()\"'").lower() if i > 0 else ""
        unit = bool(UNIT_RE.match(nxt)) or core.startswith("£") or core.endswith("%") or \
            prev in {"section", "sections", "rule", "part", "regulation", "paragraph", "para", "schedule", "article"} \
            or re.search(r"(st|nd|rd|th)$", core) is not None
        vals.setdefault(v, False)
        vals[v] = vals[v] or unit
    return vals if with_context else set(vals)


def lower_tokens(text):
    return {w.lower().strip("'") for w in re.findall(r"[A-Za-z][A-Za-z'-]*", text)}


def split_words(w):
    return [p for p in re.split(r"[-']", w) if p]


def proper_candidates(text):
    """Capitalised words (not inside tags). Returns list of (word, sentence_initial)."""
    text = TAG_RE.sub(" ", text)
    out = []
    start = True
    for tok in TOKEN_RE.findall(text):
        if re.match(r"[A-Za-z]", tok):
            core = re.sub(r"'s$|’s$", "", tok)
            if core and core[0].isupper() and not start and len(core) > 0:
                out.append((core, False))
            elif core and core[0].isupper() and start:
                out.append((core, True))
            start = False
        else:
            start = tok in ".?!:" or tok in {'"', "“", "‘"} or (start and tok in {'"', "“", "(", "…"})
            if tok in {"-", "—", "–", ","}:
                start = False
    return out


def check(script_text, guide_text, speakers=("Will", "Hannah")):
    errors, warnings, stats = [], [], {}
    try:
        sc = parse(script_text)
    except ValueError as e:
        return {"ok": False, "errors": ["format: %s" % e], "warnings": [], "stats": {}}
    meta, turns = sc["meta"], sc["turns"]
    if not meta.get("title"):
        errors.append("header: title missing")
    recap = meta.get("recap")
    if not isinstance(recap, list) or not 3 <= len(recap) <= 4:
        errors.append("header: recap must list 3 or 4 lines")
    invented = meta.get("invented") or []
    if isinstance(invented, str):
        invented = [invented]
    who = [t["who"] for t in turns]
    if set(who) != set(speakers):
        errors.append("speakers must be exactly %s (found %s)" % (list(speakers), sorted(set(who))))
    if who and who[0] != speakers[0]:
        errors.append("%s must speak first" % speakers[0])
    secs = [s.strip().lower() for s in sc["sections"]]
    if secs != SECTIONS:
        errors.append("sections must be exactly: Rule, Exam mode, Recap (found %s)" % sc["sections"])
    total = sum(words(t["text"]) for t in turns)
    stats["words"] = total
    stats["minutes_at_2.6_wps"] = round(total / 2.6 / 60, 1)
    if not WORD_LIMITS[0] <= total <= WORD_LIMITS[1]:
        errors.append("length %d words is outside %d-%d" % (total, *WORD_LIMITS))
    per = {}
    for t in turns:
        per[t["section"].lower()] = per.get(t["section"].lower(), 0) + words(t["text"])
    stats["section_words"] = per
    for s, (lo, hi) in SECTION_WARN.items():
        if s in per and not lo <= per[s] <= hi:
            warnings.append("section %s has %d words (aim %d-%d)" % (s, per[s], lo, hi))
    # tags
    tg = [t for turn in turns for t in tags_used(turn["text"])]
    bad = sorted({t for t in tg if t not in ALLOWED_TAGS})
    if bad:
        errors.append("tags not allowed: %s" % bad)
    if total and len(tg) > max(2, total * MAX_TAGS_PER_WORD):
        errors.append("too many tags (%d); use them sparingly" % len(tg))
    stats["tags"] = len(tg)
    # per-turn problems
    body = "\n".join(strip_tags(t["text"]) for t in turns)
    if MARKUP_RE.search(body):
        errors.append("markup or abbreviation a voice would read out: %r" % MARKUP_RE.search(body).group(0))
    for turn in turns:
        if len(turn["text"].split()) > 90:
            warnings.append("very long turn (%d words) in %s" % (len(turn["text"].split()), turn["section"]))
    if YEAR_RE.search(body):
        errors.append("a year appears: %s (no years, per the brief)" % sorted(set(YEAR_RE.findall(body))))
    c = CITE_RE.search(body)
    if c:
        errors.append("law-report citation style text: %r" % c.group(0))
    # figures
    guide_figs = figures(guide_text) | figures(" ".join(invented))
    script_figs = figures(body, with_context=True)
    unknown = []
    for v, has_unit in script_figs.items():
        if v in guide_figs:
            continue
        if isinstance(v, int) and 0 <= v <= 10 and not has_unit:
            continue
        unknown.append(v)
    if unknown:
        errors.append("figures not in the guide: %s" % sorted(unknown, key=float))
    # names
    guide_tokens = lower_tokens(guide_text)
    guide_upper = set(re.findall(r"\b[A-Z]{2,}[0-9]?\b", guide_text))
    inv_tokens = set()
    for item in invented:
        inv_tokens |= lower_tokens(str(item))
    script_lower = lower_tokens(" ".join(w for w in re.findall(r"\b[a-z][a-z']*\b", body)))
    speaker_l = {s.lower() for s in speakers}
    unknown_names = set()
    guide_text_l = re.sub(r"\s+", " ", guide_text.lower())
    for w, initial in proper_candidates(body):
        if w.isupper() and len(w) > 1:
            if w in guide_upper or w in ALLOWED_CAPS or w.lower() in script_lower or w.lower() in guide_tokens:
                continue
        lw = w.lower()
        if lw in speaker_l or lw in ALLOWED_PROPER or lw in guide_tokens or lw in inv_tokens:
            continue
        if any(p.lower() in guide_tokens or p.lower() in inv_tokens for p in split_words(w)):
            continue
        if initial and (lw in COMMON_STARTERS or lw in script_lower):
            continue
        if initial and lw in guide_tokens:
            continue
        unknown_names.add(w)
    if unknown_names:
        errors.append("names or capitalised words not in the guide or the header's invented list: %s"
                      % sorted(unknown_names))
    # Capitalised phrases ending in Act/Rules/etc must appear whole in the guide
    for m in re.finditer(r"\b((?:[A-Z][a-z]+ )+(?:(?:of|and|the) )?(?:[A-Z][a-z]+ )*(?:Act|Rules|Regulations|Code|Order|Directive))\b",
                         body):
        phrase = re.sub(r"\s+", " ", m.group(1)).lower()
        phrase = re.sub(r"^(the|a|an) ", "", phrase)
        if phrase not in guide_text_l and not any(phrase in str(i).lower() for i in invented):
            warnings.append("statute-style name not found whole in the guide: %r" % m.group(1))
    stats["invented"] = len(invented)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    speakers = ("Will", "Hannah")
    if "--speakers" in sys.argv:
        speakers = tuple(sys.argv[sys.argv.index("--speakers") + 1].split(","))
        args = [a for a in args if a != sys.argv[sys.argv.index("--speakers") + 1]]
    res = check(Path(args[0]).read_text(encoding="utf-8"), Path(args[1]).read_text(encoding="utf-8"), speakers)
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print("OK" if res["ok"] else "FAILED")
        for e in res["errors"]:
            print("  ERROR:", e)
        for w in res["warnings"]:
            print("  warning:", w)
        print("  stats:", res["stats"])
    sys.exit(0 if res["ok"] else 1)
