#!/usr/bin/env python3
"""Quick check of what Google's speech service accepts. Every variant runs at once, each with a hard time limit.

The first probe showed that a request can hang for ever and ignore the library's own time limit, so each
request here runs in its own helper thread and the main program stops waiting after HARD_LIMIT seconds.

Writes reports/probe.json with, for each variant, how long it took and either the audio length or the exact error.
Run by tools/run.py when audition/request.json has "probe": true.
"""
import base64
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402

HANNAH = "voice_7hvws5hbx3yt"   # designed woman from audition pair D
BRITISH_LIBRARY = "en-gb-advisor-10"
LINE = "Hang on, that's bonkers. So the contract exists while the letter's just sat in a sorting office."
TAGGED = "<short pause> Sat in Swindon. Yes. And the law basically shrugs and says, well, you did everything you could. <laugh>"
HARD_LIMIT = 55


def ann(speaker=None, style=None):
    a = {"type": "speech_metadata"}
    if speaker:
        a["speaker"] = speaker
    if style:
        a["style"] = style
    return a


def text(t, *anns):
    item = {"type": "text", "text": t}
    if anns:
        item["annotations"] = list(anns)
    return item


def variants():
    one_hannah = [{"voice": HANNAH}]
    named_hannah = [{"speaker": "Hannah", "voice": HANNAH}]
    named_will = [{"speaker": "Will", "voice": BRITISH_LIBRARY}]
    two_list = [{"speaker": "Will", "voice": "Puck"}, {"speaker": "Hannah", "voice": "Kore"}]
    two_dict = {"speakers": [{"speaker": "Will", "voice": "Puck"}, {"speaker": "Hannah", "voice": "Kore"}]}
    pair_turns = [text("Right. Quick one before we start.", ann("Will", "warm, dry")),
                  text("Oh no. Is this a trick one?", ann("Hannah", "wary"))]
    return [
        ("C1 control: designed woman, plain text", [text(LINE)], one_hannah),
        ("L1 style only, no speaker (the case that hung), config without name", [text(LINE, ann(None, "thinking aloud"))], one_hannah),
        ("L2 speaker + style, config without name", [text(LINE, ann("Hannah", "thinking aloud"))], one_hannah),
        ("L3 speaker + style, config with the same name", [text(LINE, ann("Hannah", "thinking aloud"))], named_hannah),
        ("L4 speaker only (no style), config with name", [text(LINE, ann("Hannah"))], named_hannah),
        ("L5 speaker + style, config as {speakers:[..]} dict", [text(LINE, ann("Hannah", "thinking aloud"))],
         {"speakers": [{"speaker": "Hannah", "voice": HANNAH}]}),
        ("L6 library man, speaker + style, config with name", [text(LINE, ann("Will", "dry, amused"))], named_will),
        ("T1 tags <short pause> and <laugh> in the text, plain", [text(TAGGED)], one_hannah),
        ("T2 tags + speaker + style, config with name", [text(TAGGED, ann("Hannah", "amused"))], named_hannah),
        ("P1 two prebuilt voices, speaker + style per turn, list config", pair_turns, two_list),
        ("P2 two prebuilt voices, speaker + style per turn, dict config", pair_turns, two_dict),
    ]


def _one(cl, name, content, cfg, out, i):
    t0 = time.time()
    r = {"variant": name}
    try:
        it = cl.interactions.create(model="gemini-3.8-flash-tts",
                                    input=[{"type": "user_input", "content": content}],
                                    response_format={"type": "audio"},
                                    generation_config={"speech_config": cfg}, timeout=HARD_LIMIT)
        audio = getattr(it, "output_audio", None)
        data = getattr(audio, "data", None) if audio is not None else None
        if data:
            raw = base64.b64decode(data) if isinstance(data, str) else data
            r["audio_seconds"] = round(len(render.wav_to_pcm(raw)) / 2 / render.RATE, 2)
            r["ok"] = True
        else:
            r["ok"] = False
            r["error"] = "no audio; text=%r" % (str(getattr(it, "output_text", ""))[:200],)
    except Exception as e:  # noqa: BLE001
        r["ok"] = False
        r["error"] = "%s: %s" % (type(e).__name__, str(e)[:500])
    r["seconds"] = round(time.time() - t0, 1)
    out[i] = r


def run(out_path, log=print):
    cl = render.client()
    vs = variants()
    out = [None] * len(vs)
    threads = []
    t_start = time.time()
    for i, (name, content, cfg) in enumerate(vs):
        th = threading.Thread(target=_one, args=(cl, name, content, cfg, out, i), daemon=True)
        th.start()
        threads.append(th)
    for th in threads:
        th.join(max(0.0, HARD_LIMIT - (time.time() - t_start)))
    results = []
    for (name, _c, _cfg), r in zip(vs, out):
        if r is None:
            r = {"variant": name, "ok": False, "seconds": HARD_LIMIT,
                 "error": "HUNG: no answer from Google after %d seconds" % HARD_LIMIT}
        log("%s -> %s" % (name, {k: v for k, v in r.items() if k != "variant"}))
        results.append(r)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(results, indent=1), encoding="utf-8")
    sys.stdout.flush()
    return results


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "reports/probe.json")
