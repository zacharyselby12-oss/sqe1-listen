"""b199 (Nov 2026): episodes rendered from now on are served from the website as plain .mp3 addresses (GitHub Pages: Content-Type audio/mp3,
byte ranges, no redirect), newest first within the site cap; the release copy stays the master, an episode that rotates out goes
back to its release address, and every older item keeps its address and GUID. Run: python3 tests/test_b199_site_audio.py
(no network: downloads are replaced, and the address check runs against a local server). Prints ALL PASSED."""
import os, sys, json, re, tempfile, pathlib, threading, http.server, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import feed, run, render, check_site_audio as chk  # noqa: E402

fails = 0
def ok(c, name):
    global fails
    print(("  ok  " if c else "  FAIL ") + name)
    fails += 0 if c else 1

A = "https://github.com/o/r/releases/download/audio/"
B = "https://example.org/sqe1-listen"
cfg = json.load(open(ROOT / "config.json"))
cfg.pop("siteMaxMB", None)
os.environ.pop("SITE_AUDIO_SECONDS", None)


def ep(i, at, size, site=True, status="published", unit="u-bpp-Tort-09"):
    name = "%s-1a2b3c4d.mp3" % i
    e = {"id": i, "unitId": unit, "title": i, "status": status, "pubDate": at, "renderedAt": at, "audio": "audio/%s.mp3" % i,
         "audioUrl": A + name, "bytes": size, "seconds": 60, "recap": ["x"]}
    if site:
        e["siteAudio"] = "audio/" + name
    return e


calls = []
def fake_fetch(url, path, short=0):
    calls.append(url.rsplit("/", 1)[-1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:   # sparse: the right size without writing the bytes
        f.truncate(sizes[url.rsplit("/", 1)[-1]] - short)
run.fetch_audio = fake_fetch
sizes = {}


def fresh_root(audition_bytes=100):
    run.ROOT = pathlib.Path(tempfile.mkdtemp())
    (run.ROOT / "audition" / "out").mkdir(parents=True)
    with open(run.ROOT / "audition" / "out" / "pair-1.mp3", "wb") as f:
        f.truncate(audition_bytes)
    site = run.ROOT / "_site"
    (site / "audio").mkdir(parents=True)
    return site


def encl(index, on_site, area=None):
    d = pathlib.Path(tempfile.mkdtemp())
    feed.build(index, cfg, B, d / "f.xml", area=area, on_site=on_site)
    t = (d / "f.xml").read_text(encoding="utf-8")
    return dict(zip(re.findall(r"<guid[^>]*>([^<]+)</guid>", t), re.findall(r'<enclosure url="([^"]+)" length="(\d+)"', t)))


print("1. a fresh render's upload names the same file for the release and the site")
run.ROOT = pathlib.Path(tempfile.mkdtemp())
(run.ROOT / "audio").mkdir()
(run.ROOT / "audio" / "n9.mp3").write_bytes(b"abc")
run.upload_audio = lambda path, name: A + name
e = {"id": "n9", "audio": "audio/n9.mp3", "renderedHash": "h"}
run.store_audio(e, "pair:a+b")
name = e["audioUrl"].rsplit("/", 1)[-1]
ok(re.fullmatch(r"n9-[0-9a-f]{8}\.mp3", name) and e["siteAudio"] == "audio/" + name, "audioUrl (release) and siteAudio name one file")
run.upload_audio = lambda path, name: None
e2 = {"id": "n9", "audio": "audio/n9.mp3", "renderedHash": "h"}
run.store_audio(e2, "pair:a+b")
ok("siteAudio" not in e2 and "audioUrl" not in e2, "no upload, no site address (the next run's self-heal makes it again)")

print("2. a remake drops the old site name with the old release address")
render.render_script = lambda text, voices, out, title, fake=False: (pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True),
                                                                      pathlib.Path(out).write_bytes(b"new"),
                                                                      {"bytes": 3, "seconds": 1, "words": 1})[2]
(run.ROOT / "scripts").mkdir()
(run.ROOT / "scripts" / "n9.txt").write_text("Host: hi\n", encoding="utf-8")
old = dict(ep("n9", "2026-11-12T08:00:00+00:00", 9), status="queued", script="scripts/n9.txt")
voices = {"mode": "pair", "lead": {"voice": "a"}, "second": {"voice": "b"}}
run.render_queued({"episodes": [old]}, voices, run.datetime.now(run.timezone.utc), True, cfg)
ok(old["status"] == "published" and "siteAudio" not in old and "audioUrl" not in old, "re-rendered: no stale siteAudio or audioUrl")

print("3. the newest fit, in order; the first that doesn't fit ends the list")
os.environ["GITHUB_REPOSITORY"] = "o/r"
site = fresh_root(100)
cfg["siteMaxMB"] = 0.0003    # 300 bytes in all: 100 voice test, so 200 for episodes
run.SITE_SPARE_BYTES = 0
eps = [ep("old1", "2026-11-01T08:00:00+00:00", 50, site=False, unit="u-bpp-DR-08"),
       ep("n0", "2026-11-12T08:00:00+00:00", 10), ep("n1", "2026-11-13T08:00:00+00:00", 80),
       ep("n2", "2026-11-14T08:00:00+00:00", 50), ep("n3", "2026-11-15T08:00:00+00:00", 80),
       ep("n4", "2026-11-16T08:00:00+00:00", 5, status="rendered"), ep("n5", "2026-11-16T09:00:00+00:00", 5, status="superseded"),
       ep("bad", "2026-11-16T10:00:00+00:00", 5)]
eps[-1]["siteAudio"] = "audio/../../evil.mp3"
idx = {"episodes": eps, "replays": [{"id": "r1", "episodeId": "n2", "pubDate": "2026-11-17T08:00:00+00:00", "reason": "test"}]}
sizes.update({e["audioUrl"].rsplit("/", 1)[-1]: e["bytes"] for e in eps})
(run.ROOT / "audio").mkdir()
with open(run.ROOT / "audio" / "n3.mp3", "wb") as f:
    f.truncate(80)                                   # n3 was made in this run
calls.clear()
placed = run.place_site_audio(idx, cfg, site)
ok(placed == {"n3": "audio/n3-1a2b3c4d.mp3", "n2": "audio/n2-1a2b3c4d.mp3"}, "n3 and n2 on the site; n1 doesn't fit, n0 not jumped in (%s)" % placed)
ok(calls == ["n2-1a2b3c4d.mp3"], "only n2 downloaded from the release; n3 copied from this run's render (%s)" % calls)
ok(all((site / p).stat().st_size == next(e["bytes"] for e in eps if e["id"] == i) for i, p in placed.items()), "each file has the recorded size")
ok(not (run.ROOT / "evil.mp3").exists() and not list(site.rglob("evil*")), "a site path outside audio/ is never written")
ok(run.tree_bytes(site) + 100 <= 300, "site plus voice test within the cap")

print("4. the feeds")
before, after = encl(idx, None), encl(idx, placed)
ok(after["sqe1listen-n3"] == (B + "/audio/n3-1a2b3c4d.mp3", "80") and after["sqe1listen-n2"] == (B + "/audio/n2-1a2b3c4d.mp3", "50"),
   "placed episodes: a plain .mp3 on the site, length = file size")
ok(after["sqe1listen-r1"] == after["sqe1listen-n2"], "a replay follows its episode to the site address")
ok(all(after[g] == before[g] for g in before if g not in ("sqe1listen-n3", "sqe1listen-n2", "sqe1listen-r1")) and set(after) == set(before),
   "every other item keeps its release address and GUID (old1, n1 rotated out, n0)")
ok(encl(idx, placed, area="Tort")["sqe1listen-n3"][0] == B + "/audio/n3-1a2b3c4d.mp3", "the subject's own show too")
t = (run.ROOT / "f.xml")
feed.build(idx, cfg, B, t, on_site=placed)
ok(t.read_text(encoding="utf-8").count('type="audio/mpeg"') == len(after), "every enclosure typed audio/mpeg")

print("5. failures keep the release address")
for short, why in ((1, "a short download"),):
    site = fresh_root(100)
    run.fetch_audio = lambda url, path: fake_fetch(url, path, short=1)
    p = run.place_site_audio({"episodes": [ep("n2", "2026-11-14T08:00:00+00:00", 50)]}, cfg, site)
    ok(p == {} and not list((site / "audio").glob("*.mp3")), "%s is removed and not served" % why)
def boom(url, path):
    raise OSError("network down")
run.fetch_audio = boom
site = fresh_root(100)
ok(run.place_site_audio({"episodes": [ep("n2", "2026-11-14T08:00:00+00:00", 50)]}, cfg, site) == {}, "a failed download: release address")
run.fetch_audio = fake_fetch
os.environ.pop("GITHUB_REPOSITORY")
site = fresh_root(100)
calls.clear()
ok(run.place_site_audio({"episodes": [ep("n2", "2026-11-14T08:00:00+00:00", 50)]}, cfg, site) == {} and calls == [],
   "outside GitHub Actions nothing is downloaded")
os.environ["GITHUB_REPOSITORY"] = "o/r"
os.environ["SITE_AUDIO_SECONDS"] = "0"
site = fresh_root(100)
calls.clear()
ok(run.place_site_audio({"episodes": [ep("n2", "2026-11-14T08:00:00+00:00", 50)]}, cfg, site) == {} and calls == [], "out of time: not fetched")
os.environ.pop("SITE_AUDIO_SECONDS")
site = fresh_root(100)
odd = [dict(ep("n2", "2026-11-14T08:00:00+00:00", 50), renderedAt="not a date"), dict(ep("n3", "2026-11-15T08:00:00+00:00", 50), bytes="50")]
ok(run.place_site_audio({"episodes": odd}, cfg, site) == {"n2": "audio/n2-1a2b3c4d.mp3"}, "an odd date or size in the list never stops the run")

site = fresh_root(100)
pre = [ep("p1", "2026-11-13T09:00:00+00:00", 50, site=False), ep("p0", "2026-11-12T09:00:00+00:00", 50, site=False)]
sizes.update({e["audioUrl"].rsplit("/", 1)[-1]: e["bytes"] for e in pre})
ok(run.place_site_audio({"episodes": pre}, cfg, site) == {}, "without siteAudioFrom, episodes rendered before b199 stay on the release")
cfg["siteAudioFrom"] = "2026-11-13T00:00:00Z"
ok(run.place_site_audio({"episodes": pre}, cfg, site) == {"p1": "audio/p1-1a2b3c4d.mp3"},
   "siteAudioFrom (opt-in): an episode rendered since then joins under its release name; an earlier one doesn't")
cfg["siteAudioFrom"] = "Friday"
ok(run.place_site_audio({"episodes": pre}, cfg, site) == {}, "a siteAudioFrom that isn't a date is ignored, never a crash")
cfg.pop("siteAudioFrom")

print("6. build_site end to end")
site = fresh_root(100)
(run.ROOT / "audio").mkdir()
run.build_site(idx, dict(cfg, siteMaxMB=0), site, B)   # the feeds and pages are written before the audio is placed: measure them
pages = run.tree_bytes(site)
cfg["siteMaxMB"] = (pages + 100 + 200) / 1e6           # as section 3: 100 voice test, 200 for episodes
site = fresh_root(100)
(run.ROOT / "audio").mkdir()
n = run.build_site(idx, cfg, site, B)
x = (site / "feed.xml").read_text(encoding="utf-8")
ok(B + "/audio/n3-1a2b3c4d.mp3" in x and B + "/audio/n2-1a2b3c4d.mp3" in x and A + "n1-1a2b3c4d.mp3" in x and A + "old1-1a2b3c4d.mp3" in x,
   "feed.xml: the newest on the site, the rest on the release (%d items)" % n)
ok((site / "audio" / "n2-1a2b3c4d.mp3").exists() and (site / "audio" / "n3-1a2b3c4d.mp3").exists(), "their files are in the site")

print("6b. b237: a run stopped while the audio is placed still leaves a site with feeds, on release addresses")
site = fresh_root(100)
(run.ROOT / "audio").mkdir()
class Stopped(BaseException):
    pass
def stopped_fetch(url, path):                      # as the 35-minute limit: part of a file written, then the run ends
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"ID3partial")
    raise Stopped()
run.fetch_audio = stopped_fetch
cfg_cut = dict(cfg); cfg_cut["siteMaxMB"] = (pages + 100 + 200) / 1e6
try:
    run.build_site(idx, cfg_cut, site, B)
    ok(False, "the stop should have ended the build")
except Stopped:
    pass
x = (site / "feed.xml").read_text(encoding="utf-8") if (site / "feed.xml").exists() else ""
ok(x and (site / "feeds" / "Tort.xml").exists() and (site / "subscribe" / "index.html").exists() and (site / "index.html").exists(),
   "feed.xml, feeds/, subscribe/ and index.html exist")
ok(B + "/audio/" not in x and A + "n3-1a2b3c4d.mp3" in x and A + "n2-1a2b3c4d.mp3" in x, "every enclosure is on its release address")
ok(not list((site / "audio").glob("*")), "no half-copied MP3 under its real name in the site (%s)" % list((site / "audio").glob("*")))
run.fetch_audio = fake_fetch

print("6c. b239: siteMaxMB 0 switches site audio off")
site = fresh_root(100)
(run.ROOT / "audio").mkdir()
calls.clear()
cfg_off = dict(cfg); cfg_off["siteMaxMB"] = 0
ok(run.place_site_audio(idx, cfg_off, site) == {} and calls == [], "0: nothing placed, nothing downloaded")
cfg_off["siteMaxMB"] = "0"
ok(run.place_site_audio(idx, cfg_off, site) == {}, "\"0\" as text: off too")
cfg_off["siteMaxMB"] = "lots"
ok(len(run.place_site_audio({"episodes": [ep("n2", "2026-11-14T08:00:00+00:00", 50)]}, cfg_off, fresh_root(100))) == 1, "an unreadable value: the default cap")
run.build_site(idx, cfg_off | {"siteMaxMB": 0}, site, B)
ok(B + "/audio/" not in (site / "feed.xml").read_text(encoding="utf-8"), "build_site with 0: feeds all on release addresses")

print("6d. b239: copy_fixed_audio moves siteAudio to the new file name too")
run.ROOT = pathlib.Path(tempfile.mkdtemp()); (run.ROOT / "audio").mkdir()
sizes["f1-1a2b3c4d.mp3"] = 40
fx_ep = ep("f1", "2026-11-14T08:00:00+00:00", 40)
fx_old = ep("f2", "2026-11-14T09:00:00+00:00", 40, site=False)
sizes["f2-1a2b3c4d.mp3"] = 40
run.upload_audio = lambda path, name: A + name
real_which = run.shutil.which
run.shutil.which = lambda c: "/usr/bin/gh"
run.copy_fixed_audio({"episodes": [fx_ep, fx_old]}, {"feedFixes": {"f1": {"audioName": "f1-new.mp3"}, "f2": {"audioName": "f2-new.mp3"}}})
run.shutil.which = real_which
ok(fx_ep["audioUrl"] == A + "f1-new.mp3" and fx_ep["siteAudio"] == "audio/f1-new.mp3", "siteAudio follows the new audioName")
ok(fx_old["audioUrl"] == A + "f2-new.mp3" and "siteAudio" not in fx_old, "an episode without siteAudio is not given one")

print("7. at this weekend's volume (real defaults: 900 MB cap, the repo's voice test, revision episodes ~8.3 MB)")
cfg.pop("siteMaxMB")
run.SITE_SPARE_BYTES = 2000000
aud = run.tree_bytes(ROOT / "audition" / "out")
site = fresh_root(aud)
(run.ROOT / "audio").mkdir()
big = [ep("w%03d" % k, "2026-11-%02dT%02d:%02d:00+00:00" % (13 + k // 40, (k % 40) // 3, k % 3 * 20), 8300000) for k in range(82)]
sizes.update({e["audioUrl"].rsplit("/", 1)[-1]: e["bytes"] for e in big})
p = run.place_site_audio({"episodes": big}, cfg, site)
ok(len(p) == 82, "all 82 (80 + the 2 queued) fit, so none rotates out this weekend (%d placed, voice test %.0f MB)" % (len(p), aud / 1e6))
more = big + [ep("x%03d" % k, "2026-11-20T%02d:%02d:00+00:00" % (k // 3, k % 3 * 20), 8300000) for k in range(30)]
sizes.update({e["audioUrl"].rsplit("/", 1)[-1]: e["bytes"] for e in more})
site = fresh_root(aud)
p2 = run.place_site_audio({"episodes": more}, cfg, site)
out = [e["id"] for e in big if e["id"] not in p2]
ok(all(("x%03d" % k) in p2 for k in range(30)) and out == [e["id"] for e in big[:len(out)]],
   "30 more: all new ones on the site; the %d oldest go back to the release address, oldest first" % len(out))
ok(run.tree_bytes(site) + aud + run.SITE_SPARE_BYTES <= 900000000, "the whole site stays under 900 MB (%.0f MB of episodes)" % (run.tree_bytes(site) / 1e6))

print("8. the address check (local server standing in for GitHub Pages)")
FILES = {"/s/audio/good.mp3": (b"ID3" + b"x" * 97, "audio/mpeg"), "/s/audio/type.mp3": (b"x" * 100, "application/octet-stream"),
         "/s/audio/short.mp3": (b"x" * 99, "audio/mpeg"),
         "/s/audio/pages.mp3": (b"ID3" + b"x" * 97, "audio/mp3")}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_GET(self):
        if self.path == "/s/audio/moved.mp3":   # as a release download: a redirect to an octet-stream link
            self.send_response(302); self.send_header("Location", "/signed?x=1"); self.end_headers(); return
        if self.path not in FILES:
            self.send_response(404); self.end_headers(); return
        body, ctype = FILES[self.path]
        m = re.match(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
        a, b = (int(m.group(1)), int(m.group(2))) if m else (0, len(body) - 1)
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        if m:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(body)))
        self.send_header("Content-Length", str(b - a + 1)); self.end_headers(); self.wfile.write(body[a:b + 1])
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = "http://127.0.0.1:%d/s" % srv.server_port
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), chk._NoRedirect)
ok(chk.probe(base + "/audio/good.mp3", 100, opener) is None, "206, audio/mpeg, right size: passes")
ok(chk.probe(base + "/audio/pages.mp3", 100, opener) is None, "audio/mp3, as GitHub Pages sends it: passes (b238)")
ok("302" in (chk.probe(base + "/audio/moved.mp3", 100, opener) or ""), "a redirect fails")
ok("not audio/mpeg or audio/mp3" in (chk.probe(base + "/audio/type.mp3", 100, opener) or ""), "the wrong type fails")
ok("99 bytes" in (chk.probe(base + "/audio/short.mp3", 100, opener) or ""), "a size unlike the feed's fails")
fx = {"episodes": [dict(ep(k, "2026-11-1%dT08:00:00+00:00" % j, 100), siteAudio="audio/%s.mp3" % k) for j, k in enumerate(["good", "moved"])]
      + [ep("rel", "2026-11-01T08:00:00+00:00", 100, site=False)], "replays": []}
fp = run.ROOT / "check.xml"
feed.build(fx, cfg, base, fp, on_site={"good": "audio/good.mp3", "moved": "audio/moved.mp3"})
ok(chk.enclosures(fp, chk.ET.parse(fp).getroot().findtext("channel/link")) == [(base + "/audio/moved.mp3", "100"), (base + "/audio/good.mp3", "100")],
   "only the site's addresses are checked (the release one is left out)")
ok(chk.main(["x", str(fp)], opener=opener, wait=0) == 1, "a feed with a bad site address fails the check")
fx["episodes"] = fx["episodes"][:1] + fx["episodes"][2:]
feed.build(fx, cfg, base, fp, on_site={"good": "audio/good.mp3"})
ok(chk.main(["x", str(fp)], opener=opener, wait=0) == 0, "a feed whose site addresses are all right passes")
srv.shutdown()

print("ALL PASSED" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
