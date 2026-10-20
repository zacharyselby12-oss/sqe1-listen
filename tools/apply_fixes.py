#!/usr/bin/env python3
"""Apply the Opus checker's line fixes to a script (the cheap 'fix once' step).

  python tools/apply_fixes.py script.txt check.json

For every problem whose "line" matches a script line exactly, the line is replaced by "fix" ("delete" removes it;
"ADD: <line(s)>" inserts new lines after it, for an omission).
Prints what was applied and what could not be matched (those need the reviser helper). Exit 0 if every problem was
applied, 1 if some were not. The script must then be code-checked and checked by Opus again.
"""
import json
import re
import sys
from pathlib import Path

TURN = re.compile(r"^[A-Z][A-Za-z]+(?: \([^()]{1,60}\))?: \S")


def main():
    sp, cp = Path(sys.argv[1]), Path(sys.argv[2])
    check = json.loads(cp.read_text(encoding="utf-8"))
    lines = sp.read_text(encoding="utf-8").split("\n")
    left = []
    for pr in check.get("problems", []):
        target = (pr.get("line") or "").strip()
        fix = (pr.get("fix") or "").strip()
        idx = [i for i, l in enumerate(lines) if l.strip() == target]
        if fix.upper().startswith("ADD:"):   # an omission: insert the new line(s) after the target line
            new = [x.strip() for x in fix[4:].strip().split("\n") if x.strip()]
            if len(idx) != 1 or not new or not all(TURN.match(x) for x in new):
                left.append(pr)
                continue
            lines[idx[0] + 1:idx[0] + 1] = new
            print("added:", pr.get("type"), "| after", target[:60])
            continue
        if len(idx) != 1 or not (fix.lower() == "delete" or TURN.match(fix)):
            left.append(pr)
            continue
        if fix.lower() == "delete":
            del lines[idx[0]]
        else:
            lines[idx[0]] = fix
        print("applied:", pr.get("type"), "|", target[:70])
    sp.write_text("\n".join(lines), encoding="utf-8")
    for pr in left:
        print("NOT applied:", pr.get("type"), "|", (pr.get("line") or "")[:70])
    sys.exit(1 if left else 0)


if __name__ == "__main__":
    main()
