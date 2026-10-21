#!/usr/bin/env python3
"""After the two Opus checks of one script (run side by side): merge their fixes, apply them, run the code check,
and write the CHANGES file and the brief for the Opus verify of the changed lines.

  python3 tools/fixflow.py <id> <dir> <source.txt>
  (<dir>/out/<id>.txt is the script; <dir>/out/<id>.check.json and <dir>/out/<id>.lines.json are the two checks.
   Writes <dir>/out/<id>.prefix.txt (the script before the fixes), <id>.merged.json, <id>.changes.txt and
   <dir>/verify-<id>.md, the verify brief: give it to a fresh Opus helper, which writes <dir>/out/<id>.verify.json.)
"""
import difflib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
name, d, src = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
out = d / "out"
script = out / (name + ".txt")
pre = out / (name + ".prefix.txt")
merged = out / (name + ".merged.json")
shutil.copyfile(script, pre)

r = subprocess.run([sys.executable, str(REPO / "tools/merge_checks.py"), str(merged),
                    str(out / (name + ".check.json")), str(out / (name + ".lines.json"))],
                   capture_output=True, text=True)
print(r.stdout.strip())
problems = json.loads(merged.read_text())["problems"]
for i, p in enumerate(problems, 1):
    print("\n#%d %s [%s] %s\n   LINE: %s\n   FIX:  %s" % (i, p.get("type"), p.get("src"), (p.get("why") or "")[:260],
                                                       p["line"][:220], p["fix"][:400]))
r = subprocess.run([sys.executable, str(REPO / "tools/apply_fixes.py"), str(script), str(merged)],
                   capture_output=True, text=True, cwd=REPO)
print("\nAPPLY:", r.stdout.strip()[-2500:], r.stderr.strip()[-800:])
r = subprocess.run([sys.executable, str(REPO / "tools/check_script.py"), str(script), str(src)],
                   capture_output=True, text=True, cwd=REPO)
print("\nCODE CHECK:", r.stdout.strip())

# CHANGES file for the verify step
a = pre.read_text().split("\n")
b = script.read_text().split("\n")
why = {p["line"]: p.get("why", "") for p in problems}
chunks = []
sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == "equal":
        continue
    old = a[i1:i2]
    reason = next((why[l.strip()] for l in old if l.strip() in why), "")
    if not reason and i1 > 0:
        reason = why.get(a[i1 - 1].strip(), "")
    chunks.append("PROBLEM: %s\nBEFORE: %s\nOLD: %s\nNEW: %s\nAFTER: %s\n" % (
        reason or "(see the new line)", a[i1 - 1] if i1 > 0 else "(start)",
        "\n     ".join(old) if old else "(new)", "\n     ".join(b[j1:j2]) if j2 > j1 else "(deleted)",
        a[i2] if i2 < len(a) else "(end)"))
changes = out / (name + ".changes.txt")
changes.write_text("\n".join(chunks), encoding="utf-8")
tpl = (REPO / "prompts/verify_fixes.md").read_text()
brief = (tpl.replace("{GUIDE_TEXT}", str(src)).replace("{CHANGES}", str(changes))
            .replace("{OUT_PATH}", str(out / (name + ".verify.json"))))
(d / ("verify-%s.md" % name)).write_text(brief, encoding="utf-8")
print("\n%d changed places -> %s" % (len(chunks), changes))
