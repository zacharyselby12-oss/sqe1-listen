#!/usr/bin/env python3
"""Quick check of what Google's speech service accepts.

Two lanes run side by side. Inside a lane the requests go one after another, each with a hard time limit,
so one stuck request cannot hide the others. Lane A uses two of Google's own built-in voices. Lane B uses
a British library voice and the woman we designed. The same shapes are tried in both lanes, so the results show
whether a hang comes from the voice type, from the mood label, from the tags or from sending many at once.

Writes reports/probe.json after every request.
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
LIBRARY_MAN = "en-gb-advisor-10"
LINE = "Hang on, that's bonkers. So the contract exists while the letter's just sat in a sorting office."
TAGGED = "<short pause> Sat in Swindon. Yes. And the law basically shrugs and says, well, you did everything you could. <laugh>"
LIMIT = 40
_LOCK = threading.Lock()


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


def lane_a():
    one = [{"voice": "Puck"}]
    pair_turns = [text("Right. Quick one before we start.", ann("Will", "warm, dry")),
                  text("Oh no. Is this a trick one?", ann("Hannah", "wary"))]
    pair_turns_plain = [text("Right. Quick one before we start.", ann("Will")),
                        text("Oh no. Is this a trick one?", ann("Hannah"))]
    two_list = [{"speaker": "Will", "voice": "Puck"}, {"speaker": "Hannah", "voice": "Kore"}]
    two_dict = {"speakers": [{"speaker": "Will", "voice": "Puck"}, {"speaker": "Hannah", "voice": "Kore"}]}
    return [
        ("A1 built-in voice, plain (control)", [text(LINE)], one),
        ("A2 built-in voice, mood only (no speaker)", [text(LINE, ann(None, "thinking aloud"))], one),
        ("A3 built-in voice, speaker + mood", [text(LINE, ann("Hannah", "thinking aloud"))], one),
        ("A4 built-in voice, <short pause> and <laugh> tags, plain", [text(TAGGED)], one),
        ("A5 two built-in voices, speaker + mood, list config", pair_turns, two_list),
        ("A6 two built-in voices, speaker + mood, dict config", pair_turns, two_dict),
        ("A7 two built-in voices, speaker only, dict config (round-1 shape)", pair_turns_plain, two_dict),
    ]


def lane_b():
    lib = [{"voice": LIBRARY_MAN}]
    des = [{"voice": HANNAH}]
    return [
        ("B1 British library man, plain (control)", [text(LINE)], lib),
        ("B2 designed woman, plain (control)", [text(LINE)], des),
        ("B3 British library man, mood only (no speaker)", [text(LINE, ann(None, "dry, amused"))], lib),
        ("B4 British library man, speaker + mood", [text(LINE, ann("Will", "dry, amused"))], lib),
        ("B5 British library man, tags, plain", [text(TAGGED)], lib),
        ("B6 designed woman, mood only (no speaker)", [text(LINE, ann(None, "thinking aloud"))], des),
        ("B7 designed woman, speaker + mood", [text(LINE, ann("Hannah", "thinking aloud"))], des),
    ]


def _one(cl, name, content, cfg, box):
    t0 = time.time()
    r = {"variant": name}
    try:
        it = cl.interactions.create(model="gemini-3.8-flash-tts",
                                    input=[{"type": "user_input", "content": content}],
                                    response_format={"type": "audio"},
                                    generation_config={"speech_config": cfg}, timeout=LIMIT)
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
        r["error"] = "%s: %s" % (type(e).__name__, str(e)[:400])
    r["seconds"] = round(time.time() - t0, 1)
    box.append(r)


def _lane(cl, label, variants, results, out_path, log):
    for name, content, cfg in variants:
        box = []
        th = threading.Thread(target=_one, args=(cl, name, content, cfg, box), daemon=True)
        t0 = time.time()
        th.start()
        th.join(LIMIT)
        if box:
            r = box[0]
        else:
            r = {"variant": name, "ok": False, "seconds": LIMIT,
                 "error": "HUNG: no answer from Google after %d seconds" % LIMIT}
        r["lane"] = label
        r["started"] = round(t0 - _T0, 1)
        with _LOCK:
            results.append(r)
            log("%s -> %s" % (name, {k: v for k, v in r.items() if k != "variant"}))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(results, indent=1), encoding="utf-8")
            sys.stdout.flush()


_T0 = time.time()


def run(out_path, log=print):
    global _T0
    _T0 = time.time()
    cl = render.client()
    results = []
    lanes = [threading.Thread(target=_lane, args=(cl, "A", lane_a(), results, out_path, log), daemon=True),
             threading.Thread(target=_lane, args=(cl, "B", lane_b(), results, out_path, log), daemon=True)]
    for th in lanes:
        th.start()
    for th in lanes:
        th.join(7 * LIMIT + 30)
    return results


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "reports/probe.json")
