#!/usr/bin/env python3
"""Render ONE two-voice chunk in its own process (render.py runs this with a hard time limit and kills it if it
hangs, so nothing inside the Google library can freeze a whole run).

  python tools/chunk_one.py in.json out.pcm
in.json: {"model", "content", "cfg", "n", "label", "limit"}. Prints "REQUESTS <n>" so the parent can count them.
Exit 0 = ok, 3 = Google's daily limit, 2 = any other failure.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
code = 0
try:
    pcm = render._checked(render.client(), spec["model"], spec["content"], spec["cfg"], spec["n"], spec["label"],
                          spec["limit"])
    Path(sys.argv[2]).write_bytes(pcm)
except render.QuotaExhausted as e:
    print("QUOTA %s" % str(e)[:400])
    code = 3
except Exception as e:  # noqa: BLE001
    print("ERROR %s: %s" % (type(e).__name__, str(e)[:400]))
    code = 2
print("REQUESTS %d" % render.REQUESTS["sent"], flush=True)
sys.exit(code)
