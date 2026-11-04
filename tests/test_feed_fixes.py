"""b145 (Nov 2026): config's "feedFixes" gives listed parts a new feed GUID and a copy of their audio under a new file name; the new
GUID goes out only together with the new file. Run: python3 tests/test_feed_fixes.py (no network: download and upload are
replaced). Prints ALL PASSED."""
import os, sys, json, re, shutil, tempfile, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import feed, run  # noqa: E402

fails = 0
def ok(c, name):
    global fails
    print(("  ok  " if c else "  FAIL ") + name)
    fails += 0 if c else 1

A = "https://github.com/o/r/releases/download/audio/"
OLD, NEW = "dr-ws08-v23-p1-e01b39fd.mp3", "dr-ws08-v23-p1-r2-e01b39fd.mp3"
idx = {"episodes": [
    {"id": "dr-ws08-v23-p1", "status": "published", "pubDate": "2026-11-01T08:00:00+00:00", "title": "DR WS08 · Part 1",
     "unitId": "u-bpp-DR-08", "audio": "audio/dr-ws08-v23-p1.mp3", "audioUrl": A + OLD + "?v=2", "bytes": 3},
    {"id": "pp-ws09-v23-p1", "status": "published", "pubDate": "2026-11-04T08:00:00+00:00", "title": "PP WS09 · Part 1",
     "unitId": "u-bpp-PP-09", "audio": "audio/pp-ws09-v23-p1.mp3", "audioUrl": A + "pp-ws09-v23-p1-11111111.mp3", "bytes": 3}], "replays": []}
fx = {"dr-ws08-v23-p1": {"guid": "sqe1listen-dr-ws08-v23-p1-r2", "audioName": NEW}}
cfg = json.load(open(ROOT / "config.json"))
cfg["feedFixes"] = fx

print("1. the feed")
g = {it["ep"]["id"]: it["guid"] for it in feed.items_for(idx, fx)}
ok(g["dr-ws08-v23-p1"] == "sqe1listen-dr-ws08-v23-p1", "before its audio is copied, a listed part keeps its old GUID (never a new GUID on the old file)")
done = json.loads(json.dumps(idx))
done["episodes"][0]["audioUrl"] = A + NEW
g = {it["ep"]["id"]: it["guid"] for it in feed.items_for(done, fx)}
ok(g == {"dr-ws08-v23-p1": "sqe1listen-dr-ws08-v23-p1-r2", "pp-ws09-v23-p1": "sqe1listen-pp-ws09-v23-p1"}, "once copied, it goes out under its new GUID; others keep theirs")
ok({it["guid"] for it in feed.items_for(done)} == {"sqe1listen-dr-ws08-v23-p1", "sqe1listen-pp-ws09-v23-p1"}, "with no fixes, nothing changes")


def built(index):
    d = pathlib.Path(tempfile.mkdtemp())
    feed.build_all(index, cfg, "https://example.org/sqe1-listen", d)
    out = {}
    for p in [d / "feed.xml"] + sorted((d / "feeds").glob("*.xml")):
        if p.exists():
            t = p.read_text(encoding="utf-8")
            out[str(p.relative_to(d))] = (re.findall(r"<guid[^>]*>([^<]+)</guid>", t), re.findall(r'<enclosure url="([^"]+)"', t))
    return out


b0, b1 = built(idx), built(done)
dr = [k for k in b1 if "DR" in k]
ok(dr and all("sqe1listen-dr-ws08-v23-p1-r2" in b1[k][0] and A + NEW in b1[k][1] for k in dr)
   and all("sqe1listen-dr-ws08-v23-p1" in b0[k][0] and A + OLD + "?v=2" in b0[k][1] for k in dr),
   "every feed holding the part: the new GUID and the new file together, or the old ones together (%s)" % dr)
ok(all(b0[k] == b1[k] for k in b0 if not any("dr-ws08" in x for x in b0[k][0])), "feeds without the part are unchanged")

print("2. the copy (in GitHub Actions only)")
calls = []
run.fetch_audio = lambda url, path: (calls.append(("get", url)), path.parent.mkdir(parents=True, exist_ok=True), path.write_bytes(b"mp3"))
run.upload_audio = lambda path, name: (calls.append(("put", name)), A + name)[1]
run.ROOT = pathlib.Path(tempfile.mkdtemp())
os.environ.pop("GITHUB_REPOSITORY", None)
i0 = json.loads(json.dumps(idx))
run.copy_fixed_audio(i0, {"feedFixes": fx})
ok(calls == [] and i0 == idx, "outside GitHub Actions nothing is downloaded or changed")
os.environ["GITHUB_REPOSITORY"] = "o/r"
which = shutil.which
run.shutil.which = lambda name: "/usr/bin/" + name
try:
    i2 = json.loads(json.dumps(idx))
    run.copy_fixed_audio(i2, {"feedFixes": fx})
    ok(i2["episodes"][0]["audioUrl"] == A + NEW, "the listed part's audio is copied under its new name and its audioUrl points there")
    ok(calls == [("get", A + OLD + "?v=2"), ("put", NEW)], "one download (its current address) and one upload")
    ok(i2["episodes"][1]["audioUrl"] == idx["episodes"][1]["audioUrl"], "a part not listed is left alone")
    ok(not list((run.ROOT / "audio").glob("*.mp3")), "the temporary copy is removed")
    calls.clear()
    run.copy_fixed_audio(i2, {"feedFixes": fx})
    ok(calls == [], "done once: a second run copies nothing")
    i3 = json.loads(json.dumps(idx))
    run.copy_fixed_audio(i3, {"feedFixes": fx}, fake=True)
    ok(calls == [] and i3 == idx, "a fake run copies nothing")
    i6 = json.loads(json.dumps(idx))
    i6["episodes"][0]["bytes"] = 999
    run.copy_fixed_audio(i6, {"feedFixes": fx})
    ok(i6["episodes"][0]["audioUrl"] == idx["episodes"][0]["audioUrl"] and ("put", NEW) not in calls, "a download of the wrong size is never uploaded")
    calls.clear()
    def raises(path, name):
        raise RuntimeError("upload failed")
    run.upload_audio = raises
    i5 = json.loads(json.dumps(idx))
    run.copy_fixed_audio(i5, {"feedFixes": fx})
    ok(i5 == idx, "an upload that fails changes nothing (the next run tries again)")
    def boom(url, path):
        raise OSError("network down")
    run.fetch_audio = boom
    i4 = json.loads(json.dumps(idx))
    run.copy_fixed_audio(i4, {"feedFixes": fx})
    ok(i4 == idx and built(i4) == b0, "a failed download changes nothing, and the feed keeps the old GUID with the old file")
finally:
    run.shutil.which = which
print("\nALL PASSED" if not fails else "\n%d FAILED" % fails)
sys.exit(1 if fails else 0)
