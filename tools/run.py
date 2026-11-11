#!/usr/bin/env python3
"""Pipeline run by GitHub Actions (and by hand with --fake for tests).

  python tools/run.py [--fake] [--now ISO] [--ignore-shabbat]

1. Shabbat guard: from Fri 14:00 to Sat 20:00 (Europe/London) nothing renders or publishes.
2. Voice audition, if audition/request.json has a new id.
3. Render every episode with status "queued" (pilots go to "review" until approved).
4. Publish approved pilots, retire superseded episodes.
5. Build _site: feeds, cover, index page, review page, audition page. Audio lives in the repo's audio release; the newest
   episodes' MP3s are also put on the site itself and the feeds point there (b199, place_site_audio).
Writes episodes/index.json back. Sets GitHub outputs "skipped" and "failed".
"""
import json
import os
import re
import shutil
import sys
import time
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


def fetch_audio(url, path):
    """(b145) Download a published MP3 from its public address to path."""
    import urllib.request
    path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url.split("?")[0], timeout=300) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def copy_fixed_audio(index, config, fake=False):
    """(b145) A published part listed in config's "feedFixes" with an "audioName" gets the same MP3 under that new file name in the
    release (copied, not made again), and its audioUrl points there, so phones fetch it afresh. Done once: a part whose audioUrl
    already ends in its audioName is left alone."""
    fixes = config.get("feedFixes") or {}
    if not fixes or fake or not os.environ.get("GITHUB_REPOSITORY") or not shutil.which("gh"):
        return   # only in GitHub Actions, where the upload can happen
    for ep in index["episodes"]:
        new = (fixes.get(ep["id"]) or {}).get("audioName")
        url = ep.get("audioUrl") or ""
        if not new or fake or ep.get("status") != "published" or not url or url.split("?")[0].rsplit("/", 1)[-1] == new:
            continue
        tmp = ROOT / "audio" / new
        try:
            fetch_audio(url, tmp)
            if ep.get("bytes") and tmp.stat().st_size != ep["bytes"]:   # a download cut short raises nothing: never upload a short file
                raise IOError("downloaded %d bytes, expected %d" % (tmp.stat().st_size, ep["bytes"]))
            stored = upload_audio(tmp, new)
            if stored:
                ep["audioUrl"] = stored
                if ep.get("siteAudio"):
                    ep["siteAudio"] = "audio/" + new   # (b239) the website copy follows the new file name too
                print("  audio copied for %s: %s" % (ep["id"], stored), flush=True)
        except Exception as e:  # noqa: BLE001
            print("  could not copy the audio of %s yet: %s" % (ep["id"], e), flush=True)
        finally:
            if tmp.exists():
                tmp.unlink()


def store_audio(ep, voices_text):
    """Upload the episode's MP3 under a name that changes whenever the script or the voices change."""
    import hashlib
    local = ROOT / ep["audio"]
    if not local.exists():
        return
    tag = hashlib.sha256(((ep.get("renderedHash") or ep.get("scriptHash") or "") + voices_text).encode()).hexdigest()[:8]
    name = "%s-%s.mp3" % (ep["id"], tag)
    url = upload_audio(local, name)
    if url:
        ep["audioUrl"] = url
        ep["siteAudio"] = "audio/" + name   # (b199) also served from the website while it is among the newest (place_site_audio)
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
            ep.pop("siteAudio", None)   # (b199) a remake gets a new file name; the old one must never carry the new audio
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
            done_at = datetime.now(timezone.utc)
            if ep.get("pilot") and not ep.get("approved"):
                ep["status"] = "review"
            elif not_yet(ep, done_at) or in_shabbat(done_at):
                # DATA-CONTRACT 12 [A4.8]: an episode finished on Shabbat (or held to a time) waits, rendered, until then
                ep["status"] = "rendered"
                if in_shabbat(done_at) and not not_yet(ep, done_at):
                    ep["notBefore"] = shabbat_end(done_at)
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


def not_yet(ep, now):
    nb = ep.get("notBefore")
    return bool(nb) and now < datetime.fromisoformat(nb.replace("Z", "+00:00"))


def shabbat_end(now, tz="Europe/London"):
    """The Saturday 20:00 London that ends this Shabbat, in UTC."""
    t = now.astimezone(ZoneInfo(tz))
    sat = (t + timedelta(days=(5 - t.weekday()) % 7)).replace(hour=20, minute=0, second=0, microsecond=0)
    if sat <= t:
        sat += timedelta(days=7)
    return sat.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def settle(index, now):
    """Publish approved pilots and held episodes whose time has come; retire episodes superseded by a published remake."""
    for ep in index["episodes"]:
        if ep.get("status") == "rendered" and not not_yet(ep, now) and not in_shabbat(now):
            ep["status"] = "published"
            ep["pubDate"] = now.isoformat(timespec="seconds")
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


STARTED = time.monotonic()
SITE_MAX_MB = 900            # (b199) GitHub Pages refuses a site over 1 GB: the whole site (voice test and covers too) stays under this
SITE_SPARE_BYTES = 2000000   # room kept for the feeds and pages, written after the audio
SITE_AUDIO_NAME = re.compile(r"^audio/[A-Za-z0-9][A-Za-z0-9._-]*\.mp3$")


def tree_bytes(path):
    path = Path(path)
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def place_site_audio(index, config, site):
    """(b199) The newest episodes' MP3s go on the website itself, so the feeds give them a plain .mp3 address that GitHub Pages
    serves with byte ranges and no redirect (its Content-Type is audio/mp3; the feed's enclosure type stays audio/mpeg). (A release download answers with a redirect to an expiring
    application/octet-stream link, and Apple Podcasts sometimes fails its first try at one and then won't play it.)
    Only published episodes rendered since b199 (they carry "siteAudio"), newest audio first, as many as fit under the site cap
    (config "siteMaxMB", default SITE_MAX_MB); the first that doesn't fit ends the list, so an episode that rotates out never comes
    back. The release copy stays the master: each run copies the file from this run's render or downloads it from the release
    (in GitHub Actions only), checked against the recorded size. An episode that isn't placed keeps its release address.
    Opt-in: config "siteAudioFrom" (a date) also takes episodes rendered since then without "siteAudio" (under their release name).
    Returns {episode id: path of its MP3 under the site}."""
    from concurrent.futures import ThreadPoolExecutor
    try:   # "siteMaxMB": 0 switches site audio off (b239); a missing or unreadable value means the default
        cap_mb = config.get("siteMaxMB")
        cap_mb = SITE_MAX_MB if cap_mb is None else float(cap_mb)
    except (TypeError, ValueError):
        cap_mb = SITE_MAX_MB
    if cap_mb <= 0:
        print("website audio: switched off (config siteMaxMB is 0); every episode keeps its release address", flush=True)
        return {}
    room = (int(cap_mb * 1000000) - tree_bytes(site)
            - tree_bytes(ROOT / "audition" / "out") - SITE_SPARE_BYTES)   # main() copies the voice test in after this
    def made(e):   # newest audio first; a date that can't be read sorts last rather than stopping the run
        try:
            return feed.parse_dt(e.get("renderedAt") or e.get("pubDate"))
        except Exception:  # noqa: BLE001
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

    try:   # opt-in (off by default): config "siteAudioFrom" (a date) also takes episodes rendered since then, before b199 landed
        since = feed.parse_dt(config["siteAudioFrom"]) if config.get("siteAudioFrom") else None
    except Exception:  # noqa: BLE001
        since = None
        print("  config siteAudioFrom is not a date: ignored", flush=True)

    def site_path(e):
        if SITE_AUDIO_NAME.match(e.get("siteAudio") or ""):
            return e["siteAudio"]
        url = (e.get("audioUrl") or "").split("?")[0]
        if since and e.get("renderedAt") and "/releases/download/" in url and made(e) >= since:
            name = "audio/" + url.rsplit("/", 1)[-1]
            return name if SITE_AUDIO_NAME.match(name) else None
        return None

    eps = [e for e in index.get("episodes", []) if e.get("status") == "published" and e.get("audioUrl")
           and isinstance(e.get("bytes"), int) and e["bytes"] > 0 and site_path(e)]
    eps.sort(key=made, reverse=True)
    window = []
    for e in eps:
        if int(e["bytes"]) > room:
            break
        window.append(e)
        room -= int(e["bytes"])
    stop = min(time.monotonic() + float(os.environ.get("SITE_AUDIO_SECONDS", "300")), STARTED + 32 * 60)   # the step stops at 35
    fetch = bool(os.environ.get("GITHUB_REPOSITORY"))   # downloads in GitHub Actions only, as copy_fixed_audio

    tmpdir = Path(str(site) + ".tmp")   # (b237) outside the site: a stopped run leaves nothing half-copied in what is deployed
    shutil.rmtree(tmpdir, ignore_errors=True)

    def place(e):
        dest = site / site_path(e)
        tmp = tmpdir / site_path(e).replace("/", "_")
        local = ROOT / e["audio"]
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.parent.mkdir(parents=True, exist_ok=True)
            if local.exists() and local.stat().st_size == int(e["bytes"]):
                shutil.copy2(local, tmp)                  # made in this run
            elif fetch and time.monotonic() < stop:
                fetch_audio(e["audioUrl"], tmp)           # from the release, the master copy
            else:
                return e, "not fetched (%s)" % ("out of time" if fetch else "outside GitHub Actions")
            if tmp.stat().st_size != int(e["bytes"]):    # a download cut short raises nothing: never serve a short file
                raise IOError("%d bytes, expected %d" % (tmp.stat().st_size, int(e["bytes"])))
            os.replace(tmp, dest)                         # only a whole, size-checked file ever appears under its real name
            return e, None
        except Exception as err:  # noqa: BLE001
            for f in (tmp, dest):
                if f.exists():
                    f.unlink()
            return e, "%s: %s" % (type(err).__name__, str(err)[:200])

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(place, window))
    shutil.rmtree(tmpdir, ignore_errors=True)
    placed = {e["id"]: site_path(e) for e, err in results if err is None}
    for e, err in results:
        if err:
            print("  %s stays on its release address this run: %s" % (e["id"], err), flush=True)
    print("website audio: %d episode(s) on the site (%.0f MB); %d newer-than-b199 episode(s) on the release address only"
          % (len(placed), sum(int(e["bytes"]) for e in window if e["id"] in placed) / 1e6, len(eps) - len(placed)), flush=True)
    return placed


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
    # (b237) Feeds and pages first, on release addresses, so that a run stopped while the audio is placed still leaves a complete
    # site; then the audio (temporary name, then rename); then the feeds again with the site addresses of what was placed.
    counts = feed.build_all(index, config, burl, site)
    (site / "review").mkdir()
    (site / "review" / "index.html").write_text(review_page(index), encoding="utf-8")
    (site / "index.html").write_text(
        "<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\"><meta name=\"robots\" "
        "content=\"noindex\"><title>SQE1 Listen</title></head><body><h1>SQE1 Listen</h1>"
        "<p>Private podcast. <a href=\"subscribe/\">Add it to Apple Podcasts</a> (everything, or one show per area of law).</p>"
        "<p><a href=\"review/\">Episodes waiting for review</a> &middot; <a href=\"audition/\">Voice test</a></p></body></html>", encoding="utf-8")
    on_site = place_site_audio(index, config, site)   # (b199) the newest episodes' MP3s, served from the site
    if on_site:
        counts = feed.build_all(index, config, burl, site, on_site=on_site)
    return counts["all"]


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
            e.get("status") == "queued" or (e.get("status") == "rendered" and not not_yet(e, now))
            for e in index.get("episodes", [])):
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

    copy_fixed_audio(index, config, fake)   # (b145) the parts listed in config's feedFixes: their audio under a new file name
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
