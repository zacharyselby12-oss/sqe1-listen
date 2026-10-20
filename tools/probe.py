#!/usr/bin/env python3
"""Quick check of what Google's service is doing right now.

Lane L (no speech made): can we reach Google and use the key at all?
Lane T (speech): the known-good plain request, the same request through Google's older route, then the mood label.
Each request has a hard time limit and runs in its own helper thread, so a stuck request cannot hide the others.

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

LINE = "Hang on, that's bonkers. So the contract exists while the letter's just sat in a sorting office."
LIMIT = 30
_LOCK = threading.Lock()
_T0 = time.time()


def _interactions(cl, content, cfg):
    it = cl.interactions.create(model="gemini-3.8-flash-tts", input=[{"type": "user_input", "content": content}],
                                response_format={"type": "audio"}, generation_config={"speech_config": cfg},
                                timeout=LIMIT)
    audio = getattr(it, "output_audio", None)
    data = getattr(audio, "data", None) if audio is not None else None
    if not data:
        return {"ok": False, "error": "no audio; text=%r" % (str(getattr(it, "output_text", ""))[:200],)}
    raw = base64.b64decode(data) if isinstance(data, str) else data
    return {"ok": True, "audio_seconds": round(len(render.wav_to_pcm(raw)) / 2 / render.RATE, 2)}


def _full_error(e):
    out = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:3000])}
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            out["headers"] = {k: v for k, v in dict(resp.headers).items()
                              if k.lower() in ("retry-after", "retry-after-ms", "x-ratelimit-reset", "date")}
        except Exception:  # noqa: BLE001
            pass
    for attr in ("details", "body", "status", "code"):
        v = getattr(e, attr, None)
        if v is not None:
            out[attr] = str(v)[:1500]
    return out


def l1(cl):
    try:
        return _interactions(cl, [{"type": "text", "text": LINE}], [{"voice": "Puck"}])
    except Exception as e:  # noqa: BLE001
        return _full_error(e)


def l2(cl):
    from google.genai import types
    try:
        r = cl.models.generate_content(
            model="gemini-3.8-flash-tts", contents=LINE,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")))))
        blob = r.candidates[0].content.parts[0].inline_data
        return {"ok": bool(blob and blob.data), "detail": "older route worked: %d bytes" % len(blob.data or b"")}
    except Exception as e:  # noqa: BLE001
        return _full_error(e)


LANES = [("Q", [("Q1 speech request, new route (full error text)", l1),
                ("Q2 speech request, older route (full error text)", l2)])]


def _one(cl, fn, box):
    t0 = time.time()
    try:
        r = fn(cl)
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:400])}
    r["seconds"] = round(time.time() - t0, 1)
    box.append(r)


def _lane(cl, label, items, results, out_path, log):
    for name, fn in items:
        box = []
        th = threading.Thread(target=_one, args=(cl, fn, box), daemon=True)
        t0 = time.time()
        th.start()
        th.join(LIMIT)
        r = box[0] if box else {"ok": False, "seconds": LIMIT,
                                "error": "HUNG: no answer from Google after %d seconds" % LIMIT}
        r.update(variant=name, lane=label, started=round(t0 - _T0, 1))
        with _LOCK:
            results.append(r)
            log("%s -> %s" % (name, {k: v for k, v in r.items() if k != "variant"}))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(results, indent=1), encoding="utf-8")
            sys.stdout.flush()


def run(out_path, log=print):
    global _T0
    _T0 = time.time()
    cl = render.client()
    results = []
    lanes = [threading.Thread(target=_lane, args=(cl, label, items, results, out_path, log), daemon=True)
             for label, items in LANES]
    for th in lanes:
        th.start()
    for th in lanes:
        th.join(3 * LIMIT + 20)
    return results


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "reports/probe.json")
