"""(b201; BUILD-ADDENDUM §56.2, decision 139) Thinking pauses by kind, each starting with a soft chime. Fake voices, no network.

Run from the repo root: python3 tests/test_think_kinds.py (exit 0 when every check passes)."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import render  # noqa: E402
from scriptfmt import parse  # noqa: E402

fails = 0


def ok(c, what):
    global fails
    print(("  ok  " if c else "  FAIL ") + what)
    fails += 0 if c else 1


def samples(pcm):
    return struct.unpack("<%dh" % (len(pcm) // 2), pcm)


def zero_runs(pcm, min_sec=1.0):
    """Lengths in seconds of runs of exact digital silence of at least min_sec."""
    out, run = [], 0
    for v in samples(pcm):
        if v == 0:
            run += 1
        else:
            if run >= render.RATE * min_sec:
                out.append(run / render.RATE)
            run = 0
    if run >= render.RATE * min_sec:
        out.append(run / render.RATE)
    return out


ok(render.pause_kind("scenario pause") == "scenario" and render.pause_kind("Calculation pause") == "calculation"
   and render.pause_kind("calc pause") == "calculation" and render.pause_kind("quick-fire pause") == "quick-fire"
   and render.pause_kind("quickfire pause") == "quick-fire" and render.pause_kind("quick fire pause") == "quick-fire",
   "pause kinds parse leniently")
ok(render.pause_kind("") is None and render.pause_kind("warm") is None and render.pause_kind("thinking aloud") is None
   and render.pause_kind("scenario") is None, "a style that isn't a pause mark gives no kind")
TABLE = [("scenario pause", "scenario"), ("Scenario Pause", "scenario"), ("calculation pause", "calculation"), ("calc pause", "calculation"),
         ("quick-fire pause", "quick-fire"), ("quickfire pause", "quick-fire"), ("quick fire pause", "quick-fire"),
         ("quick-fire scenario pause", "quick-fire"), ("calculation scenario pause", "calculation"), ("calculation", None), ("scenario", None),
         ("calc", None), ("quick-fire", None), ("pause", None), ("thinking aloud", None), ("", None)]
ok(all(render.pause_kind(st) == want for st, want in TABLE), "the kind table (b210): 'pause' required; quick-fire, then calculation, then scenario (%s)"
   % [(st, render.pause_kind(st)) for st, want in TABLE if render.pause_kind(st) != want])

c = render.chime()
cs = samples(c)
peak = max(abs(v) for v in cs)
ok(len(c) == int(render.RATE * render.CHIME_SEC) * 2, "the chime lasts %.1f s" % render.CHIME_SEC)
ok(abs(peak / 32767 - render.CHIME_PEAK) < 0.005, "the chime peaks at %.2f of full scale, as set (%.3f)" % (render.CHIME_PEAK, peak / 32767))
ok(max(abs(v) for v in cs[-200:]) < peak * 0.2, "the chime fades out")

script = """---
title: Test
---
## Map
Will: Today's big question is a short one.
Hannah: A question to start: does a duty arise, or not?
Will (scenario pause): <think>
Will: Yes, because the defendant made matters worse.
Hannah: And a date to work out: when is the defence due?
Will (calculation pause): <think>
Will: Twenty-eight days after service of the particulars.
Hannah: What's the summary for omissions?
Will (quick-fire pause): <think>
Will: Make matters worse and there's a duty; fail to make them better and there's none.
Hannah: And an old-style gap, with options: yes, or no?
Will: <think>
Will: Yes.
"""
turns = parse(script)["turns"]
voices = {"mode": "line", "lead": {"name": "Will", "voice": "Puck"}, "second": {"name": "Hannah", "voice": "Kore"}}
pcm = render.render_pcm(turns, voices, fake=True, log=lambda *a: None)
runs = zero_runs(pcm, 1.0)
want = [x - render.CHIME_SEC for x in (render.THINK_KIND_GAP["scenario"], render.THINK_KIND_GAP["calculation"], render.THINK_KIND_GAP["quick-fire"], render.THINK_GAP)]
ok(len(runs) == 4, "four long silences, one a pause (%s)" % [round(r, 2) for r in runs])
ok(all(0 <= r - w < 0.3 for r, w in zip(runs, want)),   # the chime's faded tail adds a fraction of a second of zeros
   "silence after each chime by kind: scenario %.1f, calculation %.1f, quick-fire %.1f, unmarked %.1f s"
   % tuple(want))
# each pause starts with the chime: the samples just before each long silence are the chime's (quiet), not a voice's
ok(all(r + render.CHIME_SEC >= 4.5 for r in runs[2:3]) and runs[2] >= 4.5, "a quick-fire pause still shows at least 4.5 s of silence (the publisher's check)")
no_think = parse("---\ntitle: T\n---\n## Map\nWill: One.\nHannah: Two.\n")["turns"]
pcm2 = render.render_pcm(no_think, voices, fake=True, log=lambda *a: None)
ok(zero_runs(pcm2, 1.0) == [], "a script with no <think> renders as before (no chime, no pause)")
sys.exit(1 if fails else 0)
