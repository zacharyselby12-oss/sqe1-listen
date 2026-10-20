"""Pre-flight: run render.py against a local fake of Google's Interactions API and check the requests it sends.
Run: python tests/test_render_shapes.py   (no key, no network)."""
import base64
import io
import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import render  # noqa: E402
from scriptfmt import parse  # noqa: E402

CAPTURED = []


def wav_bytes(seconds):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(render.fake_pcm(int(seconds * 2.6)))
    return buf.getvalue()


VOICES = [
    {"id": "Algieba", "display_name": "Algieba", "type": "prebuilt", "gender": "male", "accent": "British",
     "language_code": "en-GB", "context": "Conversational", "persona": "Warm"},
    {"id": "Achird", "display_name": "Achird", "type": "prebuilt", "gender": "male", "accent": "American",
     "language_code": "en-US", "context": "Narration", "persona": "Calm"},
    {"id": "Despina", "display_name": "Despina", "type": "prebuilt", "gender": "female", "accent": "British",
     "language_code": "en-GB", "context": "Conversational", "persona": "Smooth"}]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        CAPTURED.append((self.path, None))
        if self.path.startswith("/v1beta/voices"):
            gender = "female" if "gender=female" in self.path else "male"
            self._json({"voices": [v for v in VOICES if v["gender"] == gender and v["language_code"] == "en-GB"],
                        "next_page_token": ""})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        CAPTURED.append((self.path, body))
        if self.path.startswith("/v1beta/voices"):
            v = dict(body.get("voice", body))
            v["id"] = "voice_new%d" % len([c for c in CAPTURED if c[0].startswith("/v1beta/voices") and c[1]])
            self._json(v)
            return
        words = 0
        for item in body["input"][0]["content"]:
            words += len(item["text"].split())
        out = {"id": "int_test", "status": "completed", "model": body.get("model"),
               "steps": [{"type": "user_input", "content": body["input"][0]["content"]},
                         {"type": "model_output", "content": [{
                             "type": "audio", "mime_type": "audio/wav", "sample_rate": 24000, "channels": 1,
                             "data": base64.b64encode(wav_bytes(words / 2.6)).decode()}]}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    from google import genai
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cl = genai.Client(api_key="test-key", http_options={"api_version": "v1beta",
                                                          "base_url": "http://127.0.0.1:%d" % srv.server_port})
    render.client = lambda: cl
    turns = parse((ROOT / "audition" / "sample.txt").read_text(encoding="utf-8"))["turns"]
    # pair mode
    v = {"mode": "pair", "model": "gemini-3.8-flash-tts", "lead": {"name": "Will", "voice": "Puck"},
         "second": {"name": "Hannah", "voice": "Kore"}}
    pcm = render.render_pcm(turns, v, log=lambda *a: None)
    assert len(pcm) > 24000 * 2 * 30, "pair audio too short"
    path, body = CAPTURED[0]
    print("pair request path:", path)
    print(json.dumps(body, indent=1)[:900])
    assert body["response_format"] == {"type": "audio"}
    assert body["generation_config"]["speech_config"]["speakers"] == [
        {"speaker": "Will", "voice": "Puck"}, {"speaker": "Hannah", "voice": "Kore"}]
    assert body["input"][0]["type"] == "user_input"
    first = body["input"][0]["content"][0]
    ann0 = first["annotations"][0]  # the audition sample may give the first line a mood, so only the speaker is fixed
    assert ann0["type"] == "speech_metadata" and ann0["speaker"] == "Will", ann0
    n_pair = len(CAPTURED)
    # line mode with a designed-voice-style id
    v2 = {"mode": "line", "lead": {"name": "Will", "voice": "voice_abc123"}, "second": {"name": "Hannah", "voice": "Kore"}}
    render.render_pcm(turns[:4], v2, log=lambda *a: None)
    lines = CAPTURED[n_pair:]
    assert len(lines) == 4
    print("line request:", json.dumps(lines[0][1]["generation_config"]), json.dumps(lines[0][1]["input"][0]["content"])[:160])
    by_text = {l[1]["input"][0]["content"][0]["text"]: l[1] for l in lines}
    assert by_text[turns[0]["text"]]["generation_config"]["speech_config"] == [{"voice": "voice_abc123"}]
    assert by_text[turns[1]["text"]]["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    # mp3
    out = ROOT / "tmp" / "shape-test.mp3"
    render.encode_mp3(pcm, out, "t")
    print("mp3 ok, %.1f s, %d bytes" % (render.duration(out), out.stat().st_size))
    # audition: library and designed British voices
    import audition
    n_before = len(CAPTURED)
    res = audition.run(ROOT, ROOT / "tmp" / "aud", fake=False, log=lambda *a: None)
    for r in res:
        print("candidate", r["id"], "ok" if r["ok"] else "FAILED " + r.get("error", ""), r.get("note", ""))
    assert all(r["ok"] for r in res), res
    new = CAPTURED[n_before:]
    created = [c for c in new if c[0].startswith("/v1beta/voices") and c[1]]
    print("voices.create bodies:", json.dumps(created[0][1])[:400])
    assert (ROOT / "tmp" / "aud" / "index.html").exists()
    srv.shutdown()
    print("ALL OK")


if __name__ == "__main__":
    main()
