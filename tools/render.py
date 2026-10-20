"""Render a script to MP3 with Gemini TTS (gemini-3.8-flash-tts, Interactions API).

voices.json:
  {"model": "gemini-3.8-flash-tts", "mode": "pair" | "line",
   "lead":   {"name": "Will",   "voice": "<prebuilt name or voice_... id>"},
   "second": {"name": "Hannah", "voice": "<prebuilt name or voice_... id>"}}

mode "pair": two prebuilt voices, one multi-speaker request per chunk of the script.
mode "line": any voices (library or designed), one request per turn, stitched with short gaps.
"""
import base64
import io
import json
import math
import os
import struct
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scriptfmt import chunks, parse, words  # noqa: E402

RATE = 24000
GAP_TURN = 0.16      # seconds of silence between turns (line mode)
GAP_CHUNK = 0.30     # seconds between chunks
PAIR_CHUNK_WORDS = 380
WORDS_PER_SEC = 2.6  # for sanity checks only


def silence(sec):
    return b"\x00\x00" * int(RATE * sec)


def fake_pcm(n_words):
    sec = max(0.6, n_words / WORDS_PER_SEC)
    n = int(RATE * sec)
    return b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * i / RATE))) for i in range(n))


def wav_to_pcm(data):
    with wave.open(io.BytesIO(data)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("unexpected audio format: %s ch, %s bytes" % (w.getnchannels(), w.getsampwidth()))
        if w.getframerate() != RATE:
            raise ValueError("unexpected sample rate %s" % w.getframerate())
        return w.readframes(w.getnframes())


def client():
    from google import genai
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


TRACE = []  # (seconds since start, text) for every API attempt; saved by run.py so slow runs can be understood
_T0 = time.time()


def trace(msg):
    line = "%7.1fs %s" % (time.time() - _T0, msg)
    TRACE.append(line)
    print("  [trace] " + line, flush=True)


def save_trace(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(TRACE) + "\n", encoding="utf-8")


def _call(cl, model, content, speech_config, tries=7):
    delay, no_audio = 8, 0
    who = (content[0].get("text") or "")[:28].replace("\n", " ")
    for i in range(tries):
        t_start = time.time()
        try:
            it = cl.interactions.create(
                model=model,
                input=[{"type": "user_input", "content": content}],
                response_format={"type": "audio"},
                generation_config={"speech_config": speech_config},
                timeout=300,
            )
            audio = getattr(it, "output_audio", None)
            if audio is None or not getattr(audio, "data", None):
                no_audio += 1
                if no_audio >= 3:
                    raise RuntimeError("no audio came back three times (%s)"
                                       % (str(getattr(it, "output_text", "") or "")[:120] or "no text either"))
                print("  no audio came back, trying again", flush=True)
                time.sleep(4)
                continue
            data = audio.data
            raw = base64.b64decode(data) if isinstance(data, str) else data
            trace("ok %.1fs try %d: %s" % (time.time() - t_start, i + 1, who))
            return wav_to_pcm(raw)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            trace("error after %.1fs try %d: %s | %s" % (time.time() - t_start, i + 1, who, msg[:140].replace("\n", " ")))
            transient = any(x in msg for x in ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED",
                                               "UNAVAILABLE", "timed out", "Timeout", "ConnectError"))
            if i == tries - 1 or not transient:
                raise
            print("  retry in %ds (%s)" % (delay, msg[:90]), flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 90)
    raise RuntimeError("no audio after %d tries" % tries)


def _checked(cl, model, content, speech_config, n_words, label):
    """Call the API and make sure the audio length is plausible for the words sent."""
    expect = max(1.0, n_words / WORDS_PER_SEC)
    last = None
    for attempt in range(3):
        pcm = _call(cl, model, content, speech_config)
        dur = len(pcm) / 2 / RATE
        last = dur
        if 0.6 * expect <= dur <= 2.2 * expect:
            return pcm
        print("  %s: odd length %.1fs for %d words (expected about %.1fs), retrying" % (label, dur, n_words, expect),
              flush=True)
    raise RuntimeError("%s: audio length %.1fs never matched %d words" % (label, last or 0, n_words))


def _pair_content(turns):
    out = []
    for t in turns:
        ann = {"type": "speech_metadata", "speaker": t["who"]}
        if t["style"]:
            ann["style"] = t["style"]
        out.append({"type": "text", "text": t["text"], "annotations": [ann]})
    return out


def _line_content(t):
    item = {"type": "text", "text": t["text"]}
    if t["style"]:
        item["annotations"] = [{"type": "speech_metadata", "style": t["style"]}]
    return [item]


def render_pcm(turns, voices, fake=False, log=print):
    """Return PCM bytes (mono 16-bit 24 kHz) for the turns."""
    model = voices.get("model", "gemini-3.8-flash-tts")
    lead, second = voices["lead"], voices["second"]
    vmap = {lead["name"]: lead["voice"], second["name"]: second["voice"]}
    for t in turns:
        if t["who"] not in vmap:
            raise ValueError("unknown speaker %r (expected %s)" % (t["who"], list(vmap)))
    parts = []
    if voices.get("mode", "pair") == "pair":
        cl = None if fake else client()
        cfg = {"speakers": [{"speaker": lead["name"], "voice": lead["voice"]},
                            {"speaker": second["name"], "voice": second["voice"]}]}
        groups = chunks(turns, PAIR_CHUNK_WORDS)
        for i, g in enumerate(groups, 1):
            n = sum(words(t["text"]) for t in g)
            log("  chunk %d/%d (%d words)" % (i, len(groups), n))
            pcm = fake_pcm(n) if fake else _checked(cl, model, _pair_content(g), cfg, n, "chunk %d" % i)
            parts += [pcm, silence(GAP_CHUNK)]
    else:
        cl = None if fake else client()

        def one(idx_t):
            idx, t = idx_t
            n = words(t["text"])
            if fake:
                return idx, fake_pcm(n)
            cfg = [{"voice": vmap[t["who"]]}]
            return idx, _checked(cl, model, _line_content(t), cfg, n, "turn %d" % idx)

        log("  %d turns, line by line" % len(turns))
        with ThreadPoolExecutor(max_workers=int(os.environ.get("TTS_WORKERS", "3"))) as ex:
            results = dict(ex.map(one, list(enumerate(turns, 1))))
        for idx in range(1, len(turns) + 1):
            parts += [results[idx], silence(GAP_TURN)]
    return b"".join(parts)


def encode_mp3(pcm, out_path, title, artist="SQE1 Listen", album="SQE1 Listen"):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1",
           "-c:a", "libmp3lame", "-b:a", "64k", "-id3v2_version", "3",
           "-metadata", "title=" + title, "-metadata", "artist=" + artist, "-metadata", "album=" + album,
           str(out_path)]
    subprocess.run(cmd, input=pcm, check=True)
    return out_path


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def render_script(script_text, voices, out_mp3, title, fake=False, log=print):
    sc = parse(script_text)
    pcm = render_pcm(sc["turns"], voices, fake=fake, log=log)
    encode_mp3(pcm, out_mp3, title)
    return {"seconds": round(duration(out_mp3)), "bytes": Path(out_mp3).stat().st_size,
            "words": sum(words(t["text"]) for t in sc["turns"])}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--voices", default="voices.json")
    ap.add_argument("--fake", action="store_true")
    a = ap.parse_args()
    v = json.load(open(a.voices))
    text = Path(a.script).read_text(encoding="utf-8")
    info = render_script(text, v, a.out, parse(text)["meta"].get("title", "Episode"), fake=a.fake)
    print(info)
