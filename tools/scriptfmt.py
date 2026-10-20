"""Episode script format.

A script is a small header, '## Section' lines and speaker turns:

    ---
    title: Contract WS01 · Contract Formation
    recap:
    - First recap line.
    - Second recap line.
    invented:
    - Ash
    - £500
    ---
    ## Rule
    Will: Welcome back.
    Hannah (teasing): Is it a drama, though?
    ## Exam mode
    ...
    ## Recap
    ...

Header keys the writer gives: title, recap (3-4 lines), invented (names, places, figures the
writer made up). The pipeline adds id, unit, guide_hash and made.
"""
import hashlib
import re

ALLOWED_TAGS = {"laugh", "sigh", "cough", "breath", "short pause", "long pause", "gasp",
                "whispers", "throat-clearing"}
TURN_RE = re.compile(r"^([A-Z][A-Za-z]+)(?: \(([^()]{1,60})\))?:\s*(\S.*)$")
TAG_RE = re.compile(r"<([^<>]{1,30})>")


def _parse_header(lines):
    meta, key = {}, None
    for ln in lines:
        if not ln.strip():
            continue
        if ln.startswith("- "):
            if key is None:
                raise ValueError("list item before any key in header")
            if not isinstance(meta.get(key), list):
                meta[key] = [] if not meta.get(key) else [meta[key]]
            meta[key].append(ln[2:].strip())
            continue
        m = re.match(r"^([a-z_]+):\s*(.*)$", ln)
        if not m:
            raise ValueError("bad header line: " + ln[:60])
        key, val = m.group(1), m.group(2).strip()
        meta[key] = val if val else []
    return meta


def parse(text):
    """Return {'meta': dict, 'turns': [dict], 'sections': [str]}."""
    text = text.replace("\r\n", "\n").strip() + "\n"
    meta, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1:
            raise ValueError("header not closed with ---")
        meta = _parse_header(text[4:end].split("\n"))
        body = text[end + 5:]
    turns, sections, section = [], [], "Main"
    for n, ln in enumerate(body.split("\n"), 1):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("## "):
            section = s[3:].strip()
            sections.append(section)
            continue
        m = TURN_RE.match(s)
        if not m:
            raise ValueError("body line %d is not a turn or a '## heading': %s" % (n, s[:60]))
        turns.append({"who": m.group(1), "style": m.group(2) or "", "text": m.group(3).strip(),
                      "section": section})
    return {"meta": meta, "turns": turns, "sections": sections}


def strip_tags(text):
    return TAG_RE.sub("", text)


def words(text):
    return len(strip_tags(text).split())


def total_words(turns):
    return sum(words(t["text"]) for t in turns)


def tags_used(text):
    return [m.group(1).strip().lower() for m in TAG_RE.finditer(text)]


def chunks(turns, max_words):
    """Group turns into chunks of at most max_words, never crossing a section boundary."""
    out, cur, n, sec = [], [], 0, None
    for t in turns:
        w = words(t["text"])
        if cur and (t["section"] != sec or n + w > max_words):
            out.append(cur)
            cur, n = [], 0
        cur.append(t)
        n += w
        sec = t["section"]
    if cur:
        out.append(cur)
    return out


def script_hash(text):
    norm = "\n".join(l.strip() for l in text.replace("\r\n", "\n").split("\n") if l.strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def add_header_fields(text, **fields):
    """Return the script text with extra key: value lines added to its header."""
    text = text.replace("\r\n", "\n").strip() + "\n"
    if not text.startswith("---\n"):
        raise ValueError("script has no header")
    end = text.find("\n---\n", 4)
    head, rest = text[4:end], text[end:]
    lines = [l for l in head.split("\n") if not any(l.startswith(k + ":") for k in fields)]
    extra = ["%s: %s" % (k, v) for k, v in fields.items()]
    return "---\n" + "\n".join(extra + lines) + rest
