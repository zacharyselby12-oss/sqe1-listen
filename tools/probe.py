#!/usr/bin/env python3
"""Quick check of what Google's speech service accepts. One request per variant, no retries, short time limit.

Writes reports/probe.json with, for each variant, how long it took and either the audio length or the exact error.
Run by tools/run.py when audition/request.json has "probe": true.
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402

HANNAH = "voice_7hvws5hbx3yt"   # designed woman from audition pair D
BRITISH_LIBRARY = "en-gb-advisor-10"
LINE = "Hang on, that's bonkers. So the contract exists while the letter's just sat in a sorting office."


def variants():
    plain = [{"type": "text", "text": LINE}]
    styled = [{"type": "text", "text": LINE, "annotations": [{"type": "speech_metadata", "style": "thinking aloud"}]}]
    tagged = [{"type": "text", "text": "<short pause> " + LINE}]
    return [
        ("V1 prebuilt Puck, plain text", plain, [{"voice": "Puck"}]),
        ("V2 designed woman (id), plain text", plain, [{"voice": HANNAH}]),
        ("V3 designed woman, mood as annotation", styled, [{"voice": HANNAH}]),
        ("V4 designed woman, short-pause tag", tagged, [{"voice": HANNAH}]),
        ("V5 library man (id), plain text", plain, [{"voice": BRITISH_LIBRARY}]),
        ("V6 library man, mood as annotation", styled, [{"voice": BRITISH_LIBRARY}]),
    ]


def run(out_path, log=print):
    cl = render.client()
    results = []
    for name, content, cfg in variants():
        t0 = time.time()
        r = {"variant": name}
        try:
            it = cl.interactions.create(model="gemini-3.8-flash-tts",
                                        input=[{"type": "user_input", "content": content}],
                                        response_format={"type": "audio"},
                                        generation_config={"speech_config": cfg}, timeout=60)
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
        log("%s -> %s" % (name, {k: v for k, v in r.items() if k != "variant"}))
        results.append(r)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(results, indent=1), encoding="utf-8")  # saved after every variant
    return results


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "reports/probe.json")
