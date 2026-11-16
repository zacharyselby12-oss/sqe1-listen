"""b307 (Nov 2026): registry.py set-summary corrects an episode's show notes (DR WS02's revision episode said the defendant "must have
applied promptly"): only that episode's summary changes, and only from exactly --was; nothing else in the episode list, no script and
no audio. Run: python3 tests/test_b307_set_summary.py (no network). Prints ALL PASSED."""
import io, json, os, shutil, subprocess, sys, tempfile, pathlib
from contextlib import redirect_stdout
from types import SimpleNamespace
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import feed, registry  # noqa: E402

fails = 0
def ok(c, name):
    global fails
    print(("  ok  " if c else "  FAIL ") + name)
    fails += 0 if c else 1

ID = "dr-ws02-rev-v1"
WAS = ("A default judgment wrongly entered must be set aside, but otherwise the defendant needs a real prospect of defending or some "
       "other good reason, and must have applied promptly.")
NOW = ("A default judgment wrongly entered must be set aside, but otherwise the court may set it aside for a real prospect of defending "
       "or some other good reason, having regard to whether the defendant applied promptly.")
A = "https://github.com/o/r/releases/download/audio/"
idx = {"episodes": [
    {"id": ID, "unitId": "u-bpp-DR-02", "title": "DR WS02 · Revision · 20 min", "guideHash": "0dfa60f1df", "script": "scripts/%s.txt" % ID,
     "scriptHash": "c7f7ac01ac70", "audio": "audio/%s.mp3" % ID, "recap": ["Default judgment needs a defendant in default."],
     "map": ["Default judgment"], "summary": WAS, "status": "published", "renderedHash": "c7f7ac01ac70",
     "audioUrl": A + ID + "-3b2fcaa5.mp3", "siteAudio": "audio/%s-3b2fcaa5.mp3" % ID, "pubDate": "2026-11-11T17:47:15+00:00", "bytes": 3},
    {"id": "dr-ws03-rev-v1", "unitId": "u-bpp-DR-03", "title": "DR WS03 · Revision · 18 min", "summary": WAS, "status": "published",
     "recap": ["x"], "pubDate": "2026-11-12T08:00:00+00:00", "audioUrl": A + "dr-ws03-rev-v1-11111111.mp3", "bytes": 3}],
    "replays": [{"id": "rp-x", "episodeId": ID, "reason": "a week on", "pubDate": "2026-11-15T08:00:00+00:00"}]}
TEXT = json.dumps(idx, indent=2, ensure_ascii=False) + "\n"   # as registry.py and run.py write it


def fresh():
    p = pathlib.Path(tempfile.mkdtemp()) / "episodes" / "index.json"
    p.parent.mkdir(parents=True)
    p.write_text(TEXT, encoding="utf-8")
    registry.REG = p
    return p


def run(**kw):
    """set_summary as the command line calls it: (what it printed, the SystemExit message or None)."""
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            registry.set_summary(SimpleNamespace(**dict({"id": ID, "was": WAS, "now": NOW}, **kw)))
    except SystemExit as e:
        return out.getvalue(), str(e)
    return out.getvalue(), None


print("1. only the summary changes, from exactly --was")
p = fresh()
said, err = run()
after = p.read_text(encoding="utf-8")
want = json.loads(TEXT)
want["episodes"][0]["summary"] = NOW
ok(err is None and json.loads(after) == want, "the episode's summary is the new one, and the list is otherwise as it was")
changed = [(a, b) for a, b in zip(TEXT.splitlines(), after.splitlines()) if a != b]
ok(len(TEXT.splitlines()) == len(after.splitlines()) and len(changed) == 1 and changed[0][1].strip() == '"summary": %s,' % json.dumps(NOW, ensure_ascii=False),
   "byte for byte, one line of the file differs: that episode's summary (the other episode with the same summary, the replays and every other field untouched)")
ok(after.endswith("}\n") and after == json.dumps(want, indent=2, ensure_ascii=False) + "\n", "written as registry.py always writes it (indent 2, a final newline)")
ok(said.strip() == "summary of %s changed" % ID and WAS not in said and NOW not in said, "it says what it did, with no summary text")
ok(feed._notes(json.loads(after)["episodes"][0]).startswith(NOW + "\n\n") and WAS not in feed._notes(json.loads(after)["episodes"][0]),
   "the feed's show notes now open with the new summary (the old wording is gone)")

print("2. applied once: a second call changes nothing")
st = p.stat().st_mtime_ns
said, err = run()
ok(err is None and p.read_text(encoding="utf-8") == after and p.stat().st_mtime_ns == st, "already the new one: nothing written")
ok("already the new one" in said, "and it says so")

print("3. refusals write nothing")
p = fresh()
errs = []
said, err = run(was=WAS + " ")
errs.append(err)
ok(err and "is not --was" in err and p.read_text(encoding="utf-8") == TEXT, "--was must be exact: a different summary changes nothing (%s)" % err)
said, err = run(was="Another sentence.", now="A third sentence.")
errs.append(err)
ok(err and "nothing changed" in err and p.read_text(encoding="utf-8") == TEXT, "a summary that is neither --was nor --now is left as it is")
said, err = run(id="no-such-ep")
errs.append(err)
ok(err == "no such episode: no-such-ep" and p.read_text(encoding="utf-8") == TEXT, "an episode not in the list: refused")
said, err = run(now="  ")
errs.append(err)
ok(err and "--now is empty" in err and p.read_text(encoding="utf-8") == TEXT, "an empty --now: refused (a summary is never cleared this way)")
ok(all(e and WAS not in e and NOW not in e for e in errs), "every refusal says why, with no summary text")

print("4. the command line")
d = pathlib.Path(tempfile.mkdtemp())
(d / "tools").mkdir()
for f in ("registry.py", "scriptfmt.py"):
    shutil.copy(ROOT / "tools" / f, d / "tools" / f)
(d / "episodes").mkdir()
(d / "episodes" / "index.json").write_text(TEXT, encoding="utf-8")
cmd = [sys.executable, "-I", str(d / "tools" / "registry.py"), "set-summary", ID]
r = subprocess.run(cmd + ["--was=" + WAS, "--now=" + NOW], capture_output=True, text=True, cwd=tempfile.gettempdir())
got = json.loads((d / "episodes" / "index.json").read_text(encoding="utf-8"))
ok(r.returncode == 0 and got == want, "set-summary ID --was=... --now=... changes the repo's own episode list, from any folder (%s)" % (r.stderr.strip()[-200:]))
r = subprocess.run(cmd + ["--was", WAS, "--now", NOW], capture_output=True, text=True)
ok(r.returncode == 0 and "already the new one" in r.stdout, "run again: exit 0, nothing to do")
(d / "episodes" / "index.json").write_text(TEXT, encoding="utf-8")
r = subprocess.run(cmd + ["--was=Another sentence.", "--now=" + NOW], capture_output=True, text=True)
ok(r.returncode == 1 and "nothing changed" in r.stderr and (d / "episodes" / "index.json").read_text(encoding="utf-8") == TEXT,
   "a mismatch: exit 1 and the file untouched")
r = subprocess.run([sys.executable, "-I", str(d / "tools" / "registry.py"), "set-summary", ID, "--now=" + NOW], capture_output=True, text=True)
ok(r.returncode == 2 and (d / "episodes" / "index.json").read_text(encoding="utf-8") == TEXT, "--was is required")
print("\nALL PASSED" if not fails else "\n%d FAILED" % fails)
sys.exit(1 if fails else 0)
