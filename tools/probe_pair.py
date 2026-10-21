#!/usr/bin/env python3
"""Time one two-voice chunk of an episode against Google, to see whether Google is answering normally.

  python tools/probe_pair.py scripts/<id>.txt <chunk number> reports/probe-pair.json
Writes {"chunk", "words", "seconds", "audio_seconds", "error"}; one or two speech requests.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402
from scriptfmt import parse, words  # noqa: E402

script, n, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
voices = json.loads(Path("voices.json").read_text(encoding="utf-8"))
turns = parse(Path(script).read_text(encoding="utf-8"))["turns"]
groups = render.chunks(turns, int(voices.get("chunkWords") or render.PAIR_CHUNK_WORDS))
g = groups[n - 1]
lead, second = voices["lead"], voices["second"]
cfg = [{"speaker": lead["name"], "voice": lead["voice"]}, {"speaker": second["name"], "voice": second["voice"]}]
res = {"script": script, "chunk": n, "of": len(groups), "words": sum(words(t["text"]) for t in g)}
t0 = time.time()
try:
    pcm = render._checked(render.client(), voices.get("model", "gemini-3.8-flash-tts"),
                          render._pair_content(g, voices.get("styleSuffix", "")), cfg, res["words"], "probe", 240)
    res["audio_seconds"] = round(len(pcm) / 2 / render.RATE, 1)
except Exception as e:  # noqa: BLE001
    res["error"] = "%s: %s" % (type(e).__name__, str(e)[:500])
res["seconds"] = round(time.time() - t0, 1)
res["requests"] = render.REQUESTS.get("sent")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res))
