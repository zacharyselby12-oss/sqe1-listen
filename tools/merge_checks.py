#!/usr/bin/env python3
"""Merge the two Opus checks of one script (run side by side) into one fix list for apply_fixes.py.

  python tools/merge_checks.py merged.json check.json lines.json

Keeps every problem that carries a fix. Two fixes for the same line: identical ones are kept once; for different ones
the first is kept and the second is printed as a conflict to settle before the verify step. SOURCE-ERROR reports
(fix 'none') are printed, never applied. Exit 0 when there are no conflicts, 1 otherwise.
"""
import json
import sys
from pathlib import Path


def main():
    out, paths = Path(sys.argv[1]), [Path(p) for p in sys.argv[2:]]
    merged, by_line, conflicts, reports = [], {}, [], []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        for pr in data.get("problems", []):
            fix = (pr.get("fix") or "").strip()
            line = (pr.get("line") or "").strip()
            if pr.get("type") == "SOURCE-ERROR" or fix.lower() in ("", "none"):
                reports.append((p.name, pr))
                continue
            key = (line, fix.upper().startswith("ADD:"))
            if key in by_line:
                if by_line[key]["fix"].strip() != fix:   # keep the first; show the second for a decision
                    conflicts.append({"line": line, "a": by_line[key]["fix"], "b": fix,
                                      "why_a": by_line[key].get("why"), "why_b": pr.get("why")})
                continue
            item = dict(pr, fix=fix, line=line, src=p.name)
            by_line[key] = item
            merged.append(item)
    out.write_text(json.dumps({"verdict": "fail" if merged else "pass", "problems": merged}, indent=1,
                              ensure_ascii=False), encoding="utf-8")
    print("merged %d fixes from %s" % (len(merged), ", ".join(p.name for p in paths)))
    for name, pr in reports:
        print("REPORT (not applied) from %s: %s | %s" % (name, pr.get("type"), (pr.get("why") or "")[:300]))
    for c in conflicts:
        print("CONFLICT on line: %s\n  A: %s\n  B: %s" % (c["line"][:160], c["a"][:300], c["b"][:300]))
    sys.exit(1 if conflicts else 0)


if __name__ == "__main__":
    main()
