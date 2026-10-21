"""Render a script to MP3 with Gemini TTS (gemini-3.8-flash-tts, Interactions API).

voices.json:
  {"model": "gemini-3.8-flash-tts", "mode": "pair" | "line",
   "lead":   {"name": "Will",   "voice": "<prebuilt name or voice_... id>"},
   "second": {"name": "Hannah", "voice": "<prebuilt name or voice_... id>"}}

mode "pair": the two voices (a built-in name, a library id like en-gb-podcaster-4, or a designed voice_... id),
             one two-speaker request per chunk of about 380 words: about 6 requests for an episode.
mode "line": one request per turn, stitched with short gaps: about 110 requests for an episode, which does not fit
             Google's limit of 100 requests a day, so it is only for tiny tests.
"""
import base64
import io
import json
import math
import os
import struct
import subprocess
import sys
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def client(base_url=None):
    """The Google client, with its own silent retrying switched off.

    Left on, the library obeys a "come back in N seconds" answer for as long as Google says. When the daily limit
    for speech is used up, Google says "come back in hours", so a request just sat there (this is what froze the
    runs on 20 Oct). With it off, the answer arrives at once and render.py decides what to do.
    """
    from google import genai
    if base_url:  # only used by the tests, to point at a pretend server
        from google.genai import types
        cl = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", "test"),
                          http_options=types.HttpOptions(base_url=base_url))
    else:
        cl = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        cfg = cl.interactions.sdk_configuration
        cfg.retry_config.max_retries = 0
    except Exception as e:  # noqa: BLE001
        print("  warning: could not switch off the library's own retrying (%s)" % e, flush=True)
    return cl


TRACE_FILE = Path(__file__).resolve().parent.parent / "reports" / "last-run-trace.txt"
TRACE = []  # (seconds since start, text) for every API attempt; saved by run.py so slow runs can be understood
_T0 = time.time()


def trace(msg):
    line = "%7.1fs %s" % (time.time() - _T0, msg)
    TRACE.append(line)
    print("  [trace] " + line, flush=True)
    try:
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001  (a log problem must never stop the work)
        pass


def save_trace(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(TRACE) + "\n", encoding="utf-8")


class QuotaExhausted(RuntimeError):
    """Google's daily limit for speech requests is used up. Nothing more can be made until it resets
    (midnight in California, which is 08:00 in London)."""


class GoogleStuck(QuotaExhausted):
    """Google keeps hanging on requests (several chunks of one episode got no answer in time). The episode stays
    queued, like a used-up daily limit, instead of burning requests and an hour of waiting."""


HUNG_BUDGET = int(os.environ.get("HUNG_BUDGET", "3"))   # hung requests one episode may meet before it stops


REQUESTS = {"sent": 0}       # how many speech requests this run has sent to Google (counted even if they fail)
_COUNT_LOCK = threading.Lock()

ABORT = threading.Event()   # set when one line has failed for good, so the others stop waiting
LINE_LIMIT = 60             # seconds one single-line request may take before we give up on it
CHUNK_LIMIT = 300           # seconds one two-voice chunk (about 380 words, 2 to 3 minutes of speech) may take;
                            # a normal answer takes about 30 seconds


def _create_guarded(cl, kwargs, limit, abort=None):
    """Call Google in a helper thread and stop waiting after `limit` seconds.

    The library's own time limit did not stop a request that hung, so this one is ours: it always ends.
    """
    box = {}
    with _COUNT_LOCK:
        REQUESTS["sent"] += 1

    def go():
        try:
            box["it"] = cl.interactions.create(**kwargs)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=go, daemon=True)
    th.start()
    end = time.time() + limit
    abort = abort or ABORT
    while th.is_alive():
        th.join(0.5)
        if abort.is_set():
            raise RuntimeError("stopped: another line already failed")
        if time.time() > end:
            raise TimeoutError("HUNG: no answer from Google after %d seconds" % limit)
    if "err" in box:
        raise box["err"]
    return box["it"]


def _call(cl, model, content, speech_config, limit=None, abort=None):
    """One request, with sensible retries: busy/overloaded answers are retried with a pause,
    a request that hangs is tried once more, anything else (a rejected request) stops at once."""
    limit = limit or LINE_LIMIT
    delay, no_audio, hung = 5, 0, 0
    who = (content[0].get("text") or "")[:28].replace("\n", " ")
    abort = abort or ABORT
    for i in range(6):
        if abort.is_set():
            raise RuntimeError("stopped: another line already failed")
        t_start = time.time()
        try:
            it = _create_guarded(cl, dict(
                model=model,
                input=[{"type": "user_input", "content": content}],
                response_format={"type": "audio"},
                generation_config={"speech_config": speech_config},
                timeout=limit,
            ), limit, abort)
            audio = getattr(it, "output_audio", None)
            if audio is None or not getattr(audio, "data", None):
                no_audio += 1
                trace("no audio try %d: %s" % (i + 1, who))
                if no_audio >= 3:
                    raise RuntimeError("no audio came back three times (%s)"
                                       % (str(getattr(it, "output_text", "") or "")[:120] or "no text either"))
                time.sleep(3)
                continue
            data = audio.data
            raw = base64.b64decode(data) if isinstance(data, str) else data
            trace("ok %.1fs try %d: %s" % (time.time() - t_start, i + 1, who))
            return wav_to_pcm(raw)
        except Exception as e:  # noqa: BLE001
            msg = "%s: %s" % (type(e).__name__, str(e))
            trace("error after %.1fs try %d: %s | %s" % (time.time() - t_start, i + 1, who, msg[:160].replace("\n", " ")))
            if "stopped: another line" in msg or "no audio came back three" in msg:
                raise
            low = msg.lower()
            if ("429" in msg or "resource_exhausted" in low or "ratelimit" in low) and (
                    "per_day" in low or "perday" in low or "requests per day" in low):
                raise QuotaExhausted("Google's daily limit for speech requests is used up: " + msg[:350]) from e
            if "HUNG" in msg:
                hung += 1
                lock = getattr(abort, "lock", None)
                if lock is not None:   # count hangs across the whole episode, not just this chunk
                    with lock:
                        abort.hung += 1
                        total = abort.hung
                    if total >= HUNG_BUDGET:
                        abort.set()
                        raise GoogleStuck("Google stopped answering: %d requests of this episode hung for %d seconds "
                                          "each; it stays queued for the next run" % (total, limit)) from e
                if hung >= 2:
                    raise
                continue
            busy = any(x in msg for x in ("429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                                          "ConnectError", "ConnectionReset", "RemoteProtocolError"))
            if not busy or i == 5:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 40)
    raise RuntimeError("no audio after several tries")


def _checked(cl, model, content, speech_config, n_words, label, limit=None, abort=None):
    """Call the API and make sure the audio length is plausible for the words sent."""
    expect = max(1.0, n_words / WORDS_PER_SEC)
    last = None
    for attempt in range(3):
        pcm = _call(cl, model, content, speech_config, limit, abort)
        dur = len(pcm) / 2 / RATE
        last = dur
        if 0.6 * expect <= dur <= 2.2 * expect:
            return pcm
        trace("odd length %.1fs for %d words (expected about %.1fs): %s" % (dur, n_words, expect, label))
    raise RuntimeError("%s: audio length %.1fs never matched %d words" % (label, last or 0, n_words))


def _checked_isolated(model, content, speech_config, n_words, label, limit, abort=None):
    """_checked in a separate process with a hard time limit: a hung or runaway request is killed outright, and the
    process is tried once more. Its speech requests are added to this run's count."""
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="chunk-"))
    (d / "in.json").write_text(json.dumps({"model": model, "content": content, "cfg": speech_config, "n": n_words,
                                           "label": label, "limit": limit}), encoding="utf-8")
    hard = 2 * limit + 60
    try:
        for attempt in (1, 2):
            if (abort or ABORT).is_set():
                raise RuntimeError("stopped: another line already failed")
            t0 = time.time()
            try:
                r = subprocess.run([sys.executable, str(Path(__file__).with_name("chunk_one.py")), str(d / "in.json"),
                                    str(d / "out.pcm")], capture_output=True, text=True, timeout=hard)
            except subprocess.TimeoutExpired:
                with _COUNT_LOCK:
                    REQUESTS["sent"] += 1
                trace("%s: own process killed after %ds (attempt %d)" % (label, hard, attempt))
                continue
            out = (r.stdout or "") + (r.stderr or "")[-600:]
            for ln in out.splitlines():
                if ln.startswith("REQUESTS "):
                    with _COUNT_LOCK:
                        REQUESTS["sent"] += int(ln.split()[1])
            if r.returncode == 0 and (d / "out.pcm").exists():
                trace("%s: ok in own process, %.1fs (attempt %d)" % (label, time.time() - t0, attempt))
                return (d / "out.pcm").read_bytes()
            trace("%s: own process failed after %.1fs (attempt %d): %s" % (label, time.time() - t0, attempt,
                                                                          out.strip().replace("\n", " | ")[-300:]))
            if r.returncode == 3:
                raise QuotaExhausted("Google's daily limit for speech requests is used up (%s)" % label)
        raise RuntimeError("%s: no audio after two tries in its own process" % label)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _pair_content(turns, suffix=""):
    """One text block per turn, each with its speaker and mood. `suffix` is added to every mood (for example an
    accent instruction when a built-in voice is used)."""
    out = []
    for t in turns:
        ann = {"type": "speech_metadata", "speaker": t["who"]}
        style = ", ".join(x for x in (t["style"], suffix) if x)
        if style:
            ann["style"] = style
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
    abort = threading.Event()   # this piece of work only: a failure here never stops other work running alongside
    abort.hung, abort.lock = 0, threading.Lock()
    if voices.get("mode", "pair") == "pair":
        cl = None if fake else client()
        cfg = [{"speaker": lead["name"], "voice": lead["voice"]},
               {"speaker": second["name"], "voice": second["voice"]}]   # Google's documented shape for two voices
        groups = chunks(turns, int(voices.get("chunkWords") or PAIR_CHUNK_WORDS))   # voices.json can set bigger chunks
        suffix = voices.get("styleSuffix", "")

        cache_dir = os.environ.get("CHUNK_CACHE_DIR")

        def one_chunk(i_g):
            i, g = i_g
            n = sum(words(t["text"]) for t in g)
            log("  chunk %d/%d (%d words)" % (i, len(groups), n))
            if fake:
                return i, fake_pcm(n)
            content = _pair_content(g, suffix)
            cached = None
            if cache_dir:   # a chunk made in an earlier run (same words, voices and model) is reused, not re-requested
                import hashlib
                key = hashlib.sha256(json.dumps([model, cfg, content], sort_keys=True).encode("utf-8")).hexdigest()[:32]
                cached = Path(cache_dir) / (key + ".pcm")
                if cached.exists() and cached.stat().st_size > 0:
                    trace("chunk %d: reused from an earlier run" % i)
                    return i, cached.read_bytes()
            if os.environ.get("ISOLATE_CHUNKS") == "1":
                pcm = _checked_isolated(model, content, cfg, n, "chunk %d" % i, CHUNK_LIMIT, abort)
            else:
                pcm = _checked(cl, model, content, cfg, n, "chunk %d" % i, CHUNK_LIMIT, abort)
            if cached is not None:
                try:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    tmp = cached.with_suffix(".part")
                    tmp.write_bytes(pcm)
                    tmp.replace(cached)
                except OSError:
                    pass
            return i, pcm

        # a few chunks at a time, so an episode takes minutes rather than a quarter of an hour; order is kept
        done, failure, quota = {}, None, None
        ex = ThreadPoolExecutor(max_workers=int(os.environ.get("PAIR_WORKERS", "2")))
        futs = {ex.submit(one_chunk, it): it[0] for it in enumerate(groups, 1)}
        for f in as_completed(futs):
            if f.cancelled():
                continue
            try:
                i, pcm = f.result()
                done[i] = pcm
            except Exception as e:  # noqa: BLE001
                if isinstance(e, QuotaExhausted) and quota is None:
                    quota = e
                if failure is None:
                    failure = "chunk %d: %s: %s" % (futs[f], type(e).__name__, str(e)[:300])
                abort.set()   # the other chunks stop at their next check; never cancel futures here: a future
                              # cancelled by shutdown(cancel_futures=True) never wakes as_completed, which then hangs
        ex.shutdown(wait=True)
        if quota is not None:
            raise quota
        if failure:
            raise RuntimeError("could not make the audio. First failure was " + failure)
        for i in range(1, len(groups) + 1):
            parts += [done[i], silence(GAP_CHUNK)]
    else:
        cl = None if fake else client()

        def one(idx_t):
            idx, t = idx_t
            n = words(t["text"])
            if fake:
                return idx, fake_pcm(n)
            cfg = [{"voice": vmap[t["who"]]}]
            return idx, _checked(cl, model, _line_content(t), cfg, n, "turn %d" % idx, None, abort)

        log("  %d turns, line by line" % len(turns))
        results, failure, quota = {}, None, None
        ex = ThreadPoolExecutor(max_workers=int(os.environ.get("TTS_WORKERS", "3")))
        futs = {ex.submit(one, it): it[0] for it in enumerate(turns, 1)}
        for f in as_completed(futs):
            if f.cancelled():
                continue
            try:
                idx, pcm = f.result()
                results[idx] = pcm
            except Exception as e:  # noqa: BLE001
                if isinstance(e, QuotaExhausted) and quota is None:
                    quota = e
                if failure is None:   # the first real failure; later ones are just lines told to stop
                    failure = "line %d: %s: %s" % (futs[f], type(e).__name__, str(e)[:300])
                abort.set()   # the other chunks stop at their next check; never cancel futures here: a future
                              # cancelled by shutdown(cancel_futures=True) never wakes as_completed, which then hangs
        ex.shutdown(wait=True)
        if quota is not None:
            raise quota
        if failure:
            raise RuntimeError("could not make the audio. First failure was " + failure)
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
    subprocess.run(cmd, input=pcm, check=True, timeout=1200)   # never hang a run on the encoder
    return out_path


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True, timeout=120)
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
