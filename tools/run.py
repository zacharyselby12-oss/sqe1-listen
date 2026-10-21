#!/usr/bin/env python3
"""Pipeline run by GitHub Actions (and by hand with --fake for tests).

  python tools/run.py [--fake] [--now ISO] [--ignore-shabbat]

1. Shabbat guard: from Fri 14:00 to Sat 20:00 (Europe/London) nothing renders or publishes.
2. Voice audition, if audition/request.json has a new id.
3. Render every episode with status "queued" (pilots go to "review" until approved).
4. Publish approved pilots, retire superseded episodes.
5. Build _site: feeds, cover, index page, review page, audition page. Audio lives in the repo's audio release.
Writes episodes/index.json back. Sets GitHub outputs "skipped" and "failed".
"""
import json
import os
import shutil
import sys
from datetime import timedelta, datetime, timezone
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
import audition  # noqa: E402
import feed  # noqa: E402
import render  # noqa: E402
from scriptfmt import parse, script_hash, total_words  # noqa: E402


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


AUDIO_RELEASE = "audio"   # episode MP3s live as files of this GitHub release, not in the repo or the website


def upload_audio(path, asset_name):
    """Put an MP3 in the repo's "audio" release and return its public address (None outside GitHub Actions)."""
    import subprocess
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo or not shutil.which("gh"):
        return None
    if subprocess.run(["gh", "release", "view", AUDIO_RELEASE, "--repo", repo], capture_output=True,
                      timeout=90).returncode != 0:
        subprocess.run(["gh", "release", "create", AUDIO_RELEASE, "--repo", repo, "--title", "Episode audio",
                        "--notes", "Audio files for the SQE1 Listen feed. Please do not delete.", "--latest=false"],
                       check=True, capture_output=True, timeout=90)
    rel = json.loads(subprocess.run(["gh", "api", "repos/%s/releases/tags/%s" % (repo, AUDIO_RELEASE)],
                                    check=True, capture_output=True, text=True, timeout=90).stdout)
    for a in rel.get("assets", []):   # same name again (a remake): replace it
        if a.get("name") == asset_name:
            subprocess.run(["gh", "api", "-X", "DELETE", "repos/%s/releases/assets/%s" % (repo, a["id"])],
                           check=True, capture_output=True, timeout=90)
    # uploaded with the MP3 type, so podcast apps are told it is audio
    subprocess.run(["gh", "api", "-X", "POST", "-H", "Content-Type: audio/mpeg", "--input", str(path),
                    "https://uploads.github.com/repos/%s/releases/%s/assets?name=%s" % (repo, rel["id"], asset_name)],
                   check=True, capture_output=True, timeout=600)   # an upload that stalls must not hang the run
    return "https://github.com/%s/releases/download/%s/%s" % (repo, AUDIO_RELEASE, asset_name)


def store_audio(ep, voices_text):
    """Upload the episode's MP3 under a name that changes whenever the script or the voices change."""
    import hashlib
    local = ROOT / ep["audio"]
    if not local.exists():
        return
    tag = hashlib.sha256(((ep.get("renderedHash") or ep.get("scriptHash") or "") + voices_text).encode()).hexdigest()[:8]
    url = upload_audio(local, "%s-%s.mp3" % (ep["id"], tag))
    if url:
        ep["audioUrl"] = url
        print("  audio stored: %s" % url, flush=True)


def requests_needed(words, voices):
    """About how many speech requests an episode of this length takes."""
    if voices.get("mode", "pair") == "pair":
        size = int(voices.get("chunkWords") or render.PAIR_CHUNK_WORDS)
        return -(-words // size) + 2                          # chunks, plus two spare for a retry
    return words // 20 + 5                                      # line by line: about one request per turn


def render_queued(index, voices, now, fake, config=None, only_pilots=False, voice_note=None):
    """Render queued episodes (or only the pilots), two at a time. Returns (failed ids, daily-limit message or None).

    Before starting, the episodes are counted against what is left of Google's daily speech allowance: those that
    fit are made, the rest stay queued for the next run."""
    from concurrent.futures import ThreadPoolExecutor
    failed, note = [], None
    cap = int((config or {}).get("speechRequestsPerDay", 100))
    reserve = int((config or {}).get("speechRequestsReserve", 10))
    log = load("reports/speech-requests.json", {"days": {}}) or {"days": {}}
    # Google's daily limit resets at midnight Pacific: its own refusal on 21 Oct said "retry in 16h25m" at 14:34 UTC,
    # i.e. at 07:00 UTC. So only today's Google day counts (a rolling 24 hours would block the morning after a busy day).
    used = log["days"].get(pacific_day(now), 0)
    left = cap - reserve - used - render.REQUESTS["sent"]
    todo = []
    for ep in index["episodes"]:
        if ep.get("status") != "queued" or (only_pilots and not ep.get("pilot")):
            continue
        if not fake:
            try:
                words = total_words(parse((ROOT / ep["script"]).read_text(encoding="utf-8"))["turns"])
            except Exception:  # noqa: BLE001
                words = 2300
            need = requests_needed(words, voices)
            if os.environ.get("CHUNK_CACHE_DIR") and voices.get("mode", "pair") == "pair":
                need = 1 if not limit_hit_recently(now) else need   # pieces are kept: start if anything is left
            if need > left or (need == 1 and left <= 0):
                ep["lastError"] = "waiting for Google's daily speech allowance (needs about %d, %d left today)" % (need, max(left, 0))
                print("  %s: %s" % (ep["id"], ep["lastError"]), flush=True)
                note = note or ("daily allowance reached: " + ep["lastError"])
                continue
            left -= need
        todo.append(ep)

    def make(ep):
        try:
            text = (ROOT / ep["script"]).read_text(encoding="utf-8")
            print("rendering %s (%s)" % (ep["id"], ep["title"]), flush=True)
            return ep, text, render.render_script(text, voices, ROOT / ep["audio"], ep["title"], fake=fake), None
        except Exception as e:  # noqa: BLE001
            return ep, None, None, e

    with ThreadPoolExecutor(max_workers=int(os.environ.get("EPISODE_WORKERS", "2"))) as ex:
        results = list(ex.map(make, todo))
    for ep, text, info, err in results:   # bookkeeping in one place, in episode order
        if err is None:
            ep.update(bytes=info["bytes"], seconds=info["seconds"], words=info["words"],
                      renderedHash=script_hash(text), renderedAt=now.isoformat(timespec="seconds"),
                      voices=voices.get("mode", "pair") + ":" + voices["lead"]["voice"] + "+" + voices["second"]["voice"])
            ep.pop("audioUrl", None)
            if not fake:
                try:
                    store_audio(ep, ep["voices"])
                except Exception as e:  # noqa: BLE001
                    print("  could not store the audio of %s yet: %s" % (ep["id"], e), flush=True)
            ep.pop("lastError", None)
            if voice_note:
                ep["voiceNote"] = voice_note
            else:
                ep.pop("voiceNote", None)
            if ep.get("pilot") and not ep.get("approved"):
                ep["status"] = "review"
            else:
                ep["status"] = "published"
                ep["pubDate"] = ep.get("pubDate") or now.isoformat(timespec="seconds")
        elif isinstance(err, render.QuotaExhausted):
            # not the episode's fault: it stays queued and is tried again after Google's limit resets
            ep["lastError"] = ("Google stopped answering; it is tried again in the next run"
                               if isinstance(err, render.GoogleStuck) else
                               "waiting for Google's daily speech limit to reset")
            print("  STOPPED: %s" % err, flush=True)
            note = str(err)
        else:
            ep["lastError"] = "%s: %s" % (type(err).__name__, str(err)[:300])
            ep["renderTries"] = ep.get("renderTries", 0) + 1
            failed.append(ep["id"])
            print("  FAILED %s (try %d): %s" % (ep["id"], ep["renderTries"], ep["lastError"]), flush=True)
            if ep["renderTries"] >= 3:
                ep["status"] = "held"
                ep["holdReason"] = "audio failed 3 times: " + ep["lastError"]
    return failed, note


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
            rows.append("<section><h2>%s</h2>%s<ul>%s</ul><audio controls preload=\"none\" src=\"%s\"></audio>"
                        "</section>" % (escape(ep["title"]),
                                        ("<p><small>%s</small></p>" % escape(ep["voiceNote"])) if ep.get("voiceNote") else "",
                                        "".join("<li>%s</li>" % escape(l) for l in ep.get("recap", [])),
                                        escape(ep.get("audioUrl") or "../" + ep["audio"])))
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
        if ep.get("status") in ("published", "review") and not ep.get("audioUrl") and (ROOT / ep["audio"]).exists():
            shutil.copy2(ROOT / ep["audio"], site / ep["audio"])   # only until it is stored in the release
    if (ROOT / "cover.png").exists():
        shutil.copy2(ROOT / "cover.png", site / "cover.png")
    if (ROOT / "covers").exists():
        shutil.copytree(ROOT / "covers", site / "covers")
    counts = feed.build_all(index, config, burl, site)
    n = counts["all"]
    (site / "review").mkdir()
    (site / "review" / "index.html").write_text(review_page(index), encoding="utf-8")
    (site / "index.html").write_text(
        "<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\"><meta name=\"robots\" "
        "content=\"noindex\"><title>SQE1 Listen</title></head><body><h1>SQE1 Listen</h1>"
        "<p>Private podcast. <a href=\"subscribe/\">Add it to Apple Podcasts</a> (everything, or one show per area of law).</p>"
        "<p><a href=\"review/\">Episodes waiting for review</a> &middot; <a href=\"audition/\">Voice test</a></p></body></html>", encoding="utf-8")
    return n


PACIFIC = ZoneInfo("America/Los_Angeles")   # Google's daily limits reset at midnight here


def pacific_day(now):
    return now.astimezone(PACIFIC).date().isoformat()


def rolling_requests(log, now):
    """Speech requests recorded in the last 24 hours (Google's daily limit behaves like a rolling window)."""
    cutoff = now - timedelta(hours=24)
    return sum(n for at, n in log.get("recent", []) if datetime.fromisoformat(at) >= cutoff)


def limit_hit_recently(now, minutes=20):
    """True if Google refused for its daily limit within the last few minutes (so a scheduled retry waits)."""
    hit = (load("reports/speech-requests.json", {}) or {}).get("limitHit") or {}
    try:
        return now - datetime.fromisoformat(hit["at"]) < timedelta(minutes=minutes)
    except (KeyError, ValueError, TypeError):
        return False


def note_requests(now, quota_message=None):
    """Keep a tally of speech requests per Google day (Pacific time), so a run can see how many are left."""
    path = ROOT / "reports" / "speech-requests.json"
    log = load("reports/speech-requests.json", {"days": {}}) or {"days": {}}
    day = pacific_day(now)
    if render.REQUESTS["sent"]:
        log["days"][day] = log["days"].get(day, 0) + render.REQUESTS["sent"]
        log.setdefault("recent", []).append([now.isoformat(timespec="seconds"), render.REQUESTS["sent"]])
    cutoff = now - timedelta(hours=48)
    log["recent"] = [r for r in log.get("recent", []) if datetime.fromisoformat(r[0]) >= cutoff]
    for old_day in sorted(log["days"])[:-14]:   # keep two weeks
        log["days"].pop(old_day)
    if quota_message:
        log["limitHit"] = {"day": day, "at": now.isoformat(timespec="seconds"), "message": quota_message[:600]}
    elif log.get("limitHit", {}).get("day") != day:
        log.pop("limitHit", None)               # a new Google day: the limit has reset
    path.parent.mkdir(parents=True, exist_ok=True)
    save("reports/speech-requests.json", log)


def provisional_voices(prov, audition_out):
    """The first candidate in prov["order"] that worked in the latest voice test: (id, voices, note) or None."""
    rep = audition_out / "report.json"
    if not rep.exists():
        return None
    results = {r["id"]: r for r in json.loads(rep.read_text(encoding="utf-8"))}
    for cid in prov.get("order", []):
        r = results.get(str(cid))
        if r and r.get("ok") and r.get("voices"):
            return str(cid), r["voices"], r.get("note", "")
    return None


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
    index = load("episodes/index.json", {"episodes": [], "replays": []})
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not any(
            e.get("status") == "queued" for e in index.get("episodes", [])):
        print("scheduled check: nothing is waiting, so nothing to do")
        gh_output(skipped="true", failed="")
        return 0
    gh_output(skipped="false")
    voices = load("voices.json")
    site = ROOT / (os.environ.get("SITE_DIR") or "_site")
    failed = []

    req = load("audition/request.json", {}) or {}
    done = load("audition/done.json", {}) or {}
    paused_until = config.get("speechPausedUntil")
    if paused_until and now < datetime.fromisoformat(paused_until.replace("Z", "+00:00")) and not fake:
        # Google's daily limit is used up: no speech is attempted, the site is rebuilt as it is
        print("speech paused until %s (Google's daily limit); nothing is spoken in this run" % paused_until, flush=True)
        settle(index, now)
        save("episodes/index.json", index)
        build_site(index, config, site, base_url(config))
        if (ROOT / "audition" / "out").exists():
            shutil.copytree(ROOT / "audition" / "out", site / "audition")
        gh_output(failed="")
        return 0
    if req.get("probe") and req.get("id") != done.get("id") and not fake:
        import probe  # a quick test of what Google accepts, written to reports/probe.json
        print("running the quick probe", flush=True)
        probe.run(ROOT / "reports" / "probe.json")
        save("audition/done.json", {"id": req["id"], "at": now.isoformat(timespec="seconds"), "probe": True})
        gh_output(failed="")
        return 0
    audition_out = ROOT / "audition" / "out"
    if req.get("designOnly") and req.get("id") != done.get("id") and not fake:
        # make the voices listed in audition/design.json (no speech is made) and remember their ids
        print("designing voices (no speech is made)", flush=True)
        spec = load("audition/design.json", {"voices": []})
        cl = render.client()
        made = load("audition/designed.json", {}) or {}
        for v in spec["voices"]:
            if v["key"] in made:
                continue
            made[v["key"]] = {"id": audition.design_voice(cl, v, v.get("name") or ("SQE1 Listen " + v["key"])),
                              "prompt": v["prompt"]}
            print("  designed %s -> %s" % (v["key"], made[v["key"]]["id"]), flush=True)
        save("audition/designed.json", made)
        audition.dump_library(cl, audition_out, print)
        save("audition/done.json", {"id": req["id"], "at": now.isoformat(timespec="seconds"), "designOnly": True})
        gh_output(failed="")
        return 0
    if req.get("dumpOnly") and req.get("id") != done.get("id") and not fake:
        print("saving the list of voices (no speech is made)", flush=True)
        audition.dump_library(render.client(), audition_out, print)   # asks Google for the voice list only
        save("audition/done.json", {"id": req["id"], "at": now.isoformat(timespec="seconds"), "dumpOnly": True})
        gh_output(failed="")
        return 0
    if req.get("notBefore") and now < datetime.fromisoformat(req["notBefore"].replace("Z", "+00:00")):
        print("the voice audition waits until %s" % req["notBefore"], flush=True)
    elif req.get("id") and req.get("id") != done.get("id"):
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

    for ep in index["episodes"]:  # audio made before the release storage existed: move it there
        if (ep.get("status") in ("published", "review") and not ep.get("audioUrl") and (ROOT / ep["audio"]).exists()
                and not fake):
            try:
                store_audio(ep, ep.get("voices", ""))
            except Exception as e:  # noqa: BLE001
                print("  could not store the audio of %s yet: %s" % (ep["id"], e), flush=True)
    for ep in index["episodes"]:  # self-heal: an episode whose audio is nowhere is made again
        if ep.get("status") in ("published", "review") and not ep.get("audioUrl") and not (ROOT / ep["audio"]).exists():
            print("audio missing for %s: it will be rendered again" % ep["id"])
            ep["status"] = "queued"
    quota_msg = None
    if voices and not voices.get("pending"):
        more, quota_msg = render_queued(index, voices, now, fake, config)
        failed += more
    elif voices and voices.get("provisional") and any(e.get("status") == "queued" and e.get("pilot")
                                                       for e in index["episodes"]):
        # Voices not chosen yet: make the pilots with the first voice from the test that worked, so Zac can hear a
        # whole episode. Nothing goes into the feed until he approves.
        pick = provisional_voices(voices["provisional"], audition_out)
        if pick:
            cid, pv, note = pick
            print("pilots use voice %s from the test for now: %s" % (cid, note), flush=True)
            more, quota_msg = render_queued(index, pv, now, fake, config, only_pilots=True,
                                            voice_note="Voice %s from the voice test (%s). It can be changed." % (cid, note))
            failed += more
        else:
            print("no voice from the test worked yet: the pilots wait", flush=True)
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
