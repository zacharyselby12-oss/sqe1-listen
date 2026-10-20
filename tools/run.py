#!/usr/bin/env python3
"""Pipeline run by GitHub Actions (and by hand with --fake for tests).

  python tools/run.py [--fake] [--now ISO] [--ignore-shabbat]

1. Shabbat guard: from Fri 14:00 to Sat 20:00 (Europe/London) nothing renders or publishes.
2. Voice audition, if audition/request.json has a new id.
3. Render every episode with status "queued" (pilots go to "review" until approved).
4. Publish approved pilots, retire superseded episodes.
5. Build _site: feed.xml, audio, cover, index page, review page, audition page.
Writes episodes/index.json back. Sets GitHub outputs "skipped" and "failed".
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
import audition  # noqa: E402
import feed  # noqa: E402
import render  # noqa: E402
from scriptfmt import parse, script_hash  # noqa: E402


def load(p, default=None):
    p = ROOT / p
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save(p, data):
    (ROOT / p).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def in_shabbat(now, tz="Europe/London"):
    t = now.astimezone(ZoneInfo(tz))
    minutes = t.hour * 60 + t.minute
    return (t.weekday() == 4 and minutes >= 14 * 60) or (t.weekday() == 5 and minutes < 20 * 60)


def gh_output(**kv):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write("%s=%s\n" % (k, v))


def base_url(config):
    if config.get("base_url"):
        return config["base_url"].rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return "https://%s.github.io/%s" % (owner.lower(), name)
    return "https://example.invalid/sqe1-listen"


def render_queued(index, voices, now, fake):
    """Render every queued episode. Returns (failed ids, daily-limit message or None)."""
    failed = []
    for ep in index["episodes"]:
        if ep.get("status") != "queued":
            continue
        try:
            text = (ROOT / ep["script"]).read_text(encoding="utf-8")
            print("rendering %s (%s)" % (ep["id"], ep["title"]), flush=True)
            info = render.render_script(text, voices, ROOT / ep["audio"], ep["title"], fake=fake)
            ep.update(bytes=info["bytes"], seconds=info["seconds"], words=info["words"],
                      renderedHash=script_hash(text), renderedAt=now.isoformat(timespec="seconds"),
                      voices=voices.get("mode", "pair") + ":" + voices["lead"]["voice"] + "+" + voices["second"]["voice"])
            ep.pop("lastError", None)
            if ep.get("pilot") and not ep.get("approved"):
                ep["status"] = "review"
            else:
                ep["status"] = "published"
                ep["pubDate"] = ep.get("pubDate") or now.isoformat(timespec="seconds")
        except render.QuotaExhausted as e:
            # not the episode's fault: it stays queued and is tried again after Google's limit resets
            ep["lastError"] = "waiting for Google's daily speech limit to reset"
            print("  STOPPED: %s" % e, flush=True)
            return failed, str(e)
        except Exception as e:  # noqa: BLE001
            ep["lastError"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            ep["renderTries"] = ep.get("renderTries", 0) + 1
            failed.append(ep["id"])
            print("  FAILED %s (try %d): %s" % (ep["id"], ep["renderTries"], ep["lastError"]), flush=True)
            if ep["renderTries"] >= 3:
                ep["status"] = "held"
                ep["holdReason"] = "audio failed 3 times: " + ep["lastError"]
    return failed, None


def settle(index, now):
    """Publish approved pilots; retire episodes superseded by a published remake."""
    for ep in index["episodes"]:
        if ep.get("status") == "review" and ep.get("approved"):
            ep["status"] = "published"
            ep["pubDate"] = now.isoformat(timespec="seconds")
    published = {e["id"] for e in index["episodes"] if e.get("status") == "published"}
    for ep in index["episodes"]:
        if ep.get("status") == "published" and ep.get("supersededBy") in published:
            ep["status"] = "superseded"


def review_page(index):
    rows = []
    for ep in index["episodes"]:
        if ep.get("status") == "review":
            rows.append("<section><h2>%s</h2><ul>%s</ul><audio controls preload=\"none\" src=\"../%s\"></audio>"
                        "</section>" % (escape(ep["title"]),
                                        "".join("<li>%s</li>" % escape(l) for l in ep.get("recap", [])),
                                        escape(ep["audio"])))
    if not rows:
        rows = ["<p>Nothing waiting for review.</p>"]
    return ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\"><title>Episodes to review</title>"
            "<style>body{font:18px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}"
            "section{border:2px solid #333;border-radius:8px;padding:1rem;margin:1rem 0}"
            "audio{width:100%}</style></head><body><h1>Episodes to review</h1>" + "".join(rows)
            + "</body></html>")


def build_site(index, config, site, burl):
    if site.exists():
        shutil.rmtree(site)
    (site / "audio").mkdir(parents=True)
    for ep in index["episodes"]:
        if ep.get("status") in ("published", "review") and (ROOT / ep["audio"]).exists():
            shutil.copy2(ROOT / ep["audio"], site / ep["audio"])
    if (ROOT / "cover.png").exists():
        shutil.copy2(ROOT / "cover.png", site / "cover.png")
    n = feed.build(index, config, burl, site / "feed.xml")
    (site / "review").mkdir()
    (site / "review" / "index.html").write_text(review_page(index), encoding="utf-8")
    (site / "index.html").write_text(
        "<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\"><meta name=\"robots\" "
        "content=\"noindex\"><title>SQE1 Listen</title></head><body><h1>SQE1 Listen</h1>"
        "<p>Private podcast feed: <a href=\"feed.xml\">feed.xml</a></p></body></html>", encoding="utf-8")
    return n


PACIFIC = ZoneInfo("America/Los_Angeles")   # Google's daily limits reset at midnight here


def pacific_day(now):
    return now.astimezone(PACIFIC).date().isoformat()


def note_requests(now, quota_message=None):
    """Keep a tally of speech requests per Google day (Pacific time), so a run can see how many are left."""
    path = ROOT / "reports" / "speech-requests.json"
    log = load("reports/speech-requests.json", {"days": {}}) or {"days": {}}
    day = pacific_day(now)
    if render.REQUESTS["sent"]:
        log["days"][day] = log["days"].get(day, 0) + render.REQUESTS["sent"]
    for old_day in sorted(log["days"])[:-14]:   # keep two weeks
        log["days"].pop(old_day)
    if quota_message:
        log["limitHit"] = {"day": day, "at": now.isoformat(timespec="seconds"), "message": quota_message[:600]}
    elif log.get("limitHit", {}).get("day") != day:
        log.pop("limitHit", None)               # a new Google day: the limit has reset
    path.parent.mkdir(parents=True, exist_ok=True)
    save("reports/speech-requests.json", log)


def main():
    fake = "--fake" in sys.argv
    now = datetime.now(timezone.utc)
    if "--now" in sys.argv:
        now = datetime.fromisoformat(sys.argv[sys.argv.index("--now") + 1])
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    config = load("config.json")
    tz = config.get("timezone", "Europe/London")
    if in_shabbat(now, tz) and "--ignore-shabbat" not in sys.argv:
        print("Shabbat: nothing rendered or published.")
        gh_output(skipped="true", failed="")
        return 0
    gh_output(skipped="false")
    index = load("episodes/index.json", {"episodes": [], "replays": []})
    voices = load("voices.json")
    site = ROOT / (os.environ.get("SITE_DIR") or "_site")
    failed = []

    req = load("audition/request.json", {}) or {}
    done = load("audition/done.json", {}) or {}
    if req.get("probe") and req.get("id") != done.get("id") and not fake:
        import probe  # a quick test of what Google accepts, written to reports/probe.json
        print("running the quick probe", flush=True)
        probe.run(ROOT / "reports" / "probe.json")
        save("audition/done.json", {"id": req["id"], "at": now.isoformat(timespec="seconds"), "probe": True})
        gh_output(failed="")
        return 0
    audition_out = ROOT / "audition" / "out"
    if req.get("id") and req.get("id") != done.get("id"):
        print("running voice audition", req["id"], flush=True)
        results = audition.run(ROOT, audition_out, fake=fake, only=req.get("only"), dump=bool(req.get("dumpLibrary")),
                                 fresh=bool(req.get("fresh")))
        quota_msg = next((r.get("quota") for r in results if r.get("quota")), None)
        if quota_msg:   # do not mark the round as done: it is run again after the limit resets
            note_requests(now, quota_msg)
            gh_output(failed="", quota="hit")
            print("Google's daily speech limit is used up; the audition will be run again later.", flush=True)
            return 0
        save("audition/done.json", {"id": req["id"], "at": now.isoformat(timespec="seconds"),
                                    "ok": [r["id"] for r in results if r["ok"]],
                                    "failed": [r["id"] for r in results if not r["ok"]]})

    for ep in index["episodes"]:  # self-heal: an episode whose audio file is missing is made again
        if ep.get("status") in ("published", "review") and not (ROOT / ep["audio"]).exists():
            print("audio missing for %s: it will be rendered again" % ep["id"])
            ep["status"] = "queued"
    quota_msg = None
    if voices and not voices.get("pending"):
        more, quota_msg = render_queued(index, voices, now, fake)
        failed += more
    elif any(e.get("status") == "queued" for e in index["episodes"]):
        print("voices not chosen yet: episodes stay queued")
    settle(index, now)
    save("episodes/index.json", index)

    n = build_site(index, config, site, base_url(config))
    if audition_out.exists():
        shutil.copytree(audition_out, site / "audition")
    print("site built: %d feed items" % n)
    if not fake:
        note_requests(now, quota_msg)
    if quota_msg:
        print("Google's daily speech limit is used up; the rest waits for the next run after it resets.", flush=True)
    gh_output(failed=",".join(failed), quota="hit" if quota_msg else "")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            render.save_trace(ROOT / "reports" / "last-run-trace.txt")
        except Exception as e:  # noqa: BLE001
            print("could not save the trace: %s" % e)
    sys.exit(code)
