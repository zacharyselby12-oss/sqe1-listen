"""Turn a workshop guide (JSON from the app) into the text a script writer is allowed to see.

Only these parts are used: overview, turnsOn, numbers, confusables and, for each section, title, test,
details (starred first), traps and apply. Everything else (reference, cards, flow, tables ...) is dropped.
The guides themselves are never pushed to GitHub; only this module's logic lives there.

  python tools/guide_extract.py guide.json out.txt      # writes the source text, prints "hash words"
"""
import hashlib
import json
import sys


def episode_source(guide):
    return {
        "overview": guide.get("overview"),
        "turnsOn": guide.get("turnsOn"),
        "numbers": guide.get("numbers"),
        "confusables": guide.get("confusables"),
        "sections": [{k: s.get(k) for k in ("title", "test", "details", "traps", "apply")}
                     for s in guide.get("sections", [])],
    }


def source_hash(guide):
    s = json.dumps(episode_source(guide), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]


def _s(x):
    if x is None:
        return ""
    if isinstance(x, (list, tuple)):
        return "; ".join(_s(i) for i in x if i)
    return str(x).strip()


def to_text(guide):
    src = episode_source(guide)
    out = ["WORKSHOP: %s" % _s(guide.get("workshop")), ""]
    out += ["OVERVIEW", _s(src["overview"]), ""]
    if src["turnsOn"]:
        out.append("WHAT THE EXAM QUESTION TURNS ON")
        for t in src["turnsOn"]:
            line = "- " + _s(t.get("text"))
            if t.get("trap"):
                line += "  [TRAP: %s]" % _s(t["trap"])
            out.append(line)
        out.append("")
    if src["numbers"]:
        out.append("NUMBERS")
        for n in src["numbers"]:
            out.append("- %s | starts: %s | trigger: %s | consequence: %s" % (
                _s(n.get("figure")), _s(n.get("start")), _s(n.get("trigger")), _s(n.get("consequence"))))
        out.append("")
    if src["confusables"]:
        out.append("LOOK-ALIKES (CONFUSABLES)")
        for c in src["confusables"]:
            out.append("- %s  vs  %s: %s" % (_s(c.get("a")), _s(c.get("b")), _s(c.get("tell"))))
        out.append("")
    for i, sec in enumerate(src["sections"], 1):
        out.append("SECTION %d: %s" % (i, _s(sec.get("title"))))
        if sec.get("test"):
            out.append("TEST:")
            out += ["- " + _s(t) for t in sec["test"]]
        det = sec.get("details") or []
        det = sorted(det, key=lambda d: 0 if d.get("star") else 1)
        if det:
            out.append("DETAILS (starred first; * = starred, most important):")
            for d in det:
                line = "- %s%s" % ("* " if d.get("star") else "", _s(d.get("text")))
                if d.get("auth"):
                    line += "  (authority: %s)" % _s(d["auth"])
                out.append(line)
        if sec.get("traps"):
            out.append("TRAPS:")
            out += ["- " + _s(t) for t in sec["traps"]]
        if sec.get("apply"):
            out.append("APPLY (the guide's own checked scenarios):")
            for a in sec["apply"]:
                out.append("- Question: %s" % _s(a.get("question")))
                out.append("  Facts that decide it: %s" % _s(a.get("facts")))
                out.append("  Answer: %s" % _s(a.get("answer")))
                out.append("  Why: %s" % _s(a.get("why")))
        out.append("")
    return "\n".join(out).strip() + "\n"


if __name__ == "__main__":
    g = json.load(open(sys.argv[1], encoding="utf-8"))
    txt = to_text(g)
    open(sys.argv[2], "w", encoding="utf-8").write(txt)
    print(source_hash(g), len(txt.split()))
