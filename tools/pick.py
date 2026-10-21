#!/usr/bin/env python3
"""Choose this run's new episodes and replays from Zac's app data (read only, saved to disk).

  python tools/pick.py --data DIR [--registry episodes/index.json] [--config config.json]
                       [--now ISO] [--out plan.json]

DIR holds the files that ArtifactData saved with out_dir (data/users/me/library/{units,guides,builds,board},
data/users/me/library/cpoints/cpo-order and data/users/me/mcqrules/entries). Nothing here calls an AI: the choice is
plain rules.

New episodes (at most config.maxNewPerDay in any 20 hours, so Google's daily speech allowance is enough, and at most
config.maxNewPerWeek in any 7 days, which keeps Claude usage in check), in this order:
  1. class between 3 days ago and 7 days ahead      (upcoming or just-held workshops; earliest class first)
  2. on his revision plan: Zac's own list, config.reviseNext (in the order listed), then the workshops the app's own
     order (cpo-order) puts on his study plan for the next 7 days (in the app's order)
  3. class 8 to 14 days ahead                         (made early, so it is ready well before the class)
  4. studied in the last 14 days
  5. a topic of the workshop has 2+ misses/confusions in the last 14 days
  6. everything else whose guide is applied          (the app's order where it has one, then module and number)
A workshop qualifies only if its v3 guide is applied in the live app: guide.v3, guide.conv.ver == "v3" and
builds/b-<unit> has status "applied", ver "v3" and the same run as the guide. A workshop is (re)made when it has
no episode yet, or when the guide's content hash differs from the one its episode was made from.

Replays (at most config.maxReplaysPerWeek in 7 days, one per episode per 7 days):
  misses (2+ misses/confusions on its topics in 14 days) > 7 days after studied > 30 days after studied
  > the 14 days before each paper.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from guide_extract import source_hash  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def dt(s):
    if not s:
        return None
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_all(data, pattern):
    out = []
    for p in sorted(Path(data).glob(pattern)):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print("warning: could not read %s: %s" % (p, e), file=sys.stderr)
    return out


def applied_v3(guide, build):
    conv = guide.get("conv") or {}
    return bool(guide.get("v3")) and conv.get("ver") == "v3" and bool(build) \
        and build.get("status") == "applied" and build.get("ver") == "v3" \
        and build.get("run") == conv.get("run") and bool(conv.get("run"))


def load_order(data):
    """The app's own priority order (library/cpoints/cpo-order, written by the app since 21 Oct 2026): unit id ->
    {tier, rank, due}. Its tier 2 is "on his study plan in the next 7 days". Empty if it wasn't saved."""
    for d in load_all(data, "**/library/cpoints/cpo-order.json"):
        return {u["id"]: u for u in d.get("units", []) if isinstance(u, dict) and u.get("id")}
    return {}


def slug(unit):
    return "%s-ws%02d" % (str(unit.get("module", "x")).lower(), int(unit.get("ws") or 0))


def prefix(unit, names):
    mod = str(unit.get("module"))
    return "%s WS%02d" % (names.get(mod, mod), int(unit.get("ws") or 0))


def current_episode(registry, unit_id):
    eps = [e for e in registry.get("episodes", []) if e.get("unitId") == unit_id
           and e.get("status") in ("queued", "review", "published", "held")]
    eps.sort(key=lambda e: e.get("madeAt") or "")
    return eps[-1] if eps else None


def pick(data, registry, config, now):
    units = {u["id"]: u for u in load_all(data, "**/library/units/*.json") if u.get("id")}
    guides = {g.get("unitId") or g.get("id"): g for g in load_all(data, "**/library/guides/*.json")}
    builds = {b.get("unitId"): b for b in load_all(data, "**/library/builds/b-*.json")}
    board = load_all(data, "**/library/board/*.json")
    entries = load_all(data, "**/mcqrules/entries/*.json")
    names = config.get("moduleNames", {})
    cap_new = config.get("maxNewPerWeek", 15)
    cap_day = config.get("maxNewPerDay", 5)
    cap_rep = config.get("maxReplaysPerWeek", 10)
    revise = [r["unitId"] if isinstance(r, dict) else r for r in config.get("reviseNext", [])]
    order = load_order(data)

    classes = {}
    for b in board:
        if b.get("kind") == "class" and b.get("unitId") and b.get("at"):
            classes[b["unitId"]] = dt(b["at"])
    d14 = now - timedelta(days=14)
    events = []  # (time, topicId) for misses and confusions in last 14 days
    for e in entries:
        t = dt(e.get("createdAt"))
        if t and t >= d14 and e.get("topicId"):
            events.append((t, e["topicId"], "miss"))
    for b in board:
        if b.get("kind") == "conf":
            t = dt(b.get("missAt") or b.get("openedAt"))
            if t and t >= d14 and b.get("topicId"):
                events.append((t, b["topicId"], "confusion"))

    def topic_events(unit):
        topics = set(unit.get("topics") or [])
        return sum(1 for _, tid, _k in events if tid in topics)

    skipped, cands = [], []
    for uid, unit in units.items():
        g, b = guides.get(uid), builds.get(uid)
        if not g:
            continue
        if not applied_v3(g, b):
            skipped.append({"unitId": uid, "why": "v3 guide not applied in the live app yet"})
            continue
        h = source_hash(g)
        cur = current_episode(registry, uid)
        remake = False
        if cur:
            if cur.get("guideHash") == h:
                continue  # already made (or held) for this exact guide
            remake = True
        cls = classes.get(uid)
        o = order.get(uid) or {}
        studied = dt(unit.get("studiedAt")) if unit.get("studied") else None
        n = topic_events(unit)
        tier, why, key = None, "", None
        if cls and now - timedelta(days=3) <= cls <= now + timedelta(days=7):
            tier, why = 1, "class on %s" % cls.date().isoformat()
            key = (0 if cls >= now else 1, abs((cls - now).total_seconds()))
        elif uid in revise:
            tier, why = 2, "on your revision list"
            key = (0, revise.index(uid))
        elif o.get("tier") == 2:
            tier, why = 2, "on your study plan this week (the app's order)"
            key = (1, int(o.get("rank") or 999))
        elif cls and now < cls <= now + timedelta(days=14):
            tier, why = 3, "class on %s" % cls.date().isoformat()
            key = (0, (cls - now).total_seconds())
        elif studied and studied >= d14:
            tier, why = 4, "studied on %s" % studied.date().isoformat()
            key = (0, -studied.timestamp())
        elif n >= 2:
            tier, why = 5, "%d misses/confusions in 14 days" % n
            key = (0, -n)
        else:
            tier, why = 6, "guide applied (no episode yet)"
            key = (int(o.get("rank") or 999), str(unit.get("module")), int(unit.get("ws") or 0))
        cands.append({"unitId": uid, "id": slug(unit) + ("-r%d" % (_remakes(registry, uid) + 2) if remake else ""),
                      "titlePrefix": prefix(unit, names), "workshop": g.get("workshop"), "tier": tier,
                      "reason": why, "guideHash": h, "remake": remake,
                      "supersedes": cur["id"] if cur and cur.get("status") in ("published", "review") else None,
                      "guideWords": None, "_key": key})
    cands.sort(key=lambda c: (c["tier"], c["_key"]))
    made7 = sum(1 for e in registry.get("episodes", [])
                if dt(e.get("madeAt")) and dt(e["madeAt"]) >= now - timedelta(days=7))
    made_day = sum(1 for e in registry.get("episodes", [])
                   if dt(e.get("madeAt")) and dt(e["madeAt"]) >= now - timedelta(hours=20))
    room_week, room_day = max(0, cap_new - made7), max(0, cap_day - made_day)
    room = min(room_week, room_day)
    chosen = cands[:room]
    for c in cands[room:]:
        why = ("over today's limit of %d new episodes (Google's speech allowance): it is made on the next run" % cap_day
               if room_day < room_week else "over the weekly limit of %d new episodes" % cap_new)
        skipped.append({"unitId": c["unitId"], "why": why})
    for c in chosen:
        c.pop("_key", None)

    replays = pick_replays(registry, units, events, now, config, cap_rep)
    remade = {c["supersedes"] for c in chosen if c.get("supersedes")}
    replays = [r for r in replays if r["episodeId"] not in remade]  # its audio is about to be replaced
    return {"now": now.isoformat(timespec="seconds"), "newEpisodes": chosen, "replays": replays,
            "skipped": skipped, "counts": {"newInLast7Days": made7, "newToday": made_day, "capNew": cap_new,
                                           "capDay": cap_day, "capReplays": cap_rep,
                                           "eligibleNew": len(cands), "unitsSeen": len(units)}}


def _remakes(registry, uid):
    return sum(1 for e in registry.get("episodes", []) if e.get("unitId") == uid) - 1


def pick_replays(registry, units, events, now, config, cap):
    all_eps = {e["id"]: e for e in registry.get("episodes", [])}
    eps = []
    for e in registry.get("episodes", []):
        if e.get("status") != "published":
            continue
        nxt = all_eps.get(e.get("supersededBy"))
        if nxt and nxt.get("status") in ("queued", "review", "published"):
            continue  # a remake is on its way: replay that one instead, once it is out
        eps.append(e)
    by_unit = {}
    for e in eps:
        if e.get("unitId") not in by_unit or (e.get("madeAt") or "") > (by_unit[e["unitId"]].get("madeAt") or ""):
            by_unit[e["unitId"]] = e
    recent = [r for r in registry.get("replays", []) if dt(r.get("pubDate")) and dt(r["pubDate"]) >= now - timedelta(days=7)]
    room = max(0, cap - len(recent))
    last_replay = {}
    for r in registry.get("replays", []):
        t = dt(r.get("pubDate"))
        if t and (r["episodeId"] not in last_replay or t > last_replay[r["episodeId"]]):
            last_replay[r["episodeId"]] = t
    done_ids = {r["id"] for r in registry.get("replays", [])}
    out = []

    def add(ep, rid, reason, prio):
        if rid in done_ids or any(o["id"] == rid or o["episodeId"] == ep["id"] for o in out):
            return
        lr = last_replay.get(ep["id"])
        if lr and now - lr < timedelta(days=7):
            return
        pub = dt(ep.get("pubDate"))
        if pub and now - pub < timedelta(days=2):
            return  # published too recently to need a replay
        out.append({"id": rid, "episodeId": ep["id"], "reason": reason, "prio": prio,
                    "pubDate": now.isoformat(timespec="seconds")})

    for uid, ep in by_unit.items():
        unit = units.get(uid) or {}
        topics = set(unit.get("topics") or [])
        n = sum(1 for _, tid, _k in events if tid in topics)
        week = now.isocalendar()
        if n >= 2:
            add(ep, "rp-%s-m%d-%02d" % (ep["id"], week[0], week[1]), "%d misses/confusions in 14 days" % n, 0)
        st = dt(unit.get("studiedAt")) if unit.get("studied") else None
        if st:
            for days, prio in ((7, 1), (30, 2)):
                due = st + timedelta(days=days)
                if due <= now <= due + timedelta(days=6):
                    add(ep, "rp-%s-d%d" % (ep["id"], days), "%d days after you studied it" % days, prio)
        for pname, paper in (config.get("papers") or {}).items():
            exam = dt(paper["date"])
            if exam and exam - timedelta(days=14) <= now <= exam and str(unit.get("module")) in paper.get("modules", []):
                add(ep, "rp-%s-%s" % (ep["id"], pname.lower()), "14 days before %s" % pname, 3)
    out.sort(key=lambda r: r["prio"])
    return out[:room]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--registry", default=str(ROOT / "episodes" / "index.json"))
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--now")
    ap.add_argument("--out")
    a = ap.parse_args()
    now = dt(a.now) if a.now else datetime.now(timezone.utc)
    reg = json.loads(Path(a.registry).read_text(encoding="utf-8")) if Path(a.registry).exists() else {}
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    plan = pick(a.data, reg, cfg, now)
    txt = json.dumps(plan, indent=2, ensure_ascii=False)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
