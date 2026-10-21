"""Tests for the picker, the replay rules, the feed and the Shabbat guard, on made-up data.
Run: python tests/test_pick.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import feed  # noqa: E402
import pick  # noqa: E402
import run as runmod  # noqa: E402
from guide_extract import source_hash  # noqa: E402

NOW = datetime(2026, 10, 21, 7, 0, tzinfo=timezone.utc)


def iso(d):
    return d.isoformat().replace("+00:00", "Z")


def guide(uid, text, run="r1"):
    return {"unitId": uid, "id": uid, "v3": True, "conv": {"run": run, "ver": "v3"}, "workshop": uid,
            "overview": text, "turnsOn": [], "numbers": [], "confusables": [], "sections": []}


def build(uid, run="r1", status="applied"):
    return {"id": "b-" + uid, "unitId": uid, "status": status, "ver": "v3", "run": run}


def unit(uid, module, ws, studied=None, topics=()):
    return {"id": uid, "module": module, "ws": str(ws), "studied": bool(studied),
            "studiedAt": iso(studied) if studied else None, "topics": list(topics)}


def write(d, rel, obj):
    p = Path(d) / "data/users/me" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def make_data(d):
    units = [unit("u-bpp-Contract-01", "Contract", 1, NOW - timedelta(days=8), ["CL-01"]),
             unit("u-bpp-Contract-02", "Contract", 2, NOW - timedelta(days=31), ["CL-02"]),
             unit("u-bpp-DR-06", "DR", 6, None, ["DR-06"]),
             unit("u-bpp-BLP-06", "BLP", 6, None, ["BL-06"]),
             unit("u-bpp-Tort-01", "Tort", 1, NOW - timedelta(days=2), ["TL-01"]),
             unit("u-bpp-PP-01", "PP", 1, NOW - timedelta(days=10), ["PP-01"]),
             unit("u-bpp-WAE-01", "WAE", 1, None, ["WE-01"]),
             unit("u-bpp-Land-01", "Land", 1, NOW - timedelta(days=9), ["LD-01"])]
    for u in units:
        write(d, "library/units/%s.json" % u["id"], u)
        write(d, "library/guides/%s.json" % u["id"], guide(u["id"], "text of " + u["id"]))
        if u["id"] != "u-bpp-Tort-01":  # Tort is not applied in the live app
            write(d, "library/builds/b-%s.json" % u["id"], build(u["id"]))
    write(d, "library/board/cl-u-bpp-DR-06.json", {"kind": "class", "unitId": "u-bpp-DR-06", "at": iso(NOW + timedelta(days=2))})
    write(d, "library/board/cl-u-bpp-BLP-06.json", {"kind": "class", "unitId": "u-bpp-BLP-06", "at": iso(NOW - timedelta(days=5))})
    for i in range(2):
        write(d, "mcqrules/entries/e%d.json" % i, {"createdAt": iso(NOW - timedelta(days=3)), "topicId": "WE-01"})
        write(d, "mcqrules/entries/f%d.json" % i, {"createdAt": iso(NOW - timedelta(days=4)), "topicId": "CL-01"})
    write(d, "library/board/cf1.json", {"kind": "conf", "topicId": "PP-01", "missAt": iso(NOW - timedelta(days=1))})


def ep(uid, eid, hash_, when, **extra):
    e = {"id": eid, "unitId": uid, "status": "published", "guideHash": hash_, "madeAt": iso(when), "pubDate": iso(when)}
    e.update(extra)
    return e


def picker():
    with tempfile.TemporaryDirectory() as d:
        make_data(d)
        old = NOW - timedelta(days=9)
        h = lambda u: source_hash(guide(u, "text of " + u))  # noqa: E731
        reg = {"episodes": [
            ep("u-bpp-Contract-01", "contract-ws01", h("u-bpp-Contract-01"), old),
            ep("u-bpp-Contract-02", "contract-ws02", h("u-bpp-Contract-02"), old),
            ep("u-bpp-PP-01", "pp-ws01", "oldhash", old),
            ep("u-bpp-Land-01", "land-ws01", h("u-bpp-Land-01"), old)], "replays": []}
        cfg = json.loads((ROOT / "config.json").read_text())

        plan = pick.pick(d, reg, cfg, NOW)
        new = {c["id"]: c for c in plan["newEpisodes"]}
        print("new:", [(c["id"], c["tier"]) for c in plan["newEpisodes"]])
        assert list(new) == ["dr-ws06", "pp-ws01-r2", "wae-ws01", "blp-ws06"], list(new)
        assert new["pp-ws01-r2"]["supersedes"] == "pp-ws01" and new["pp-ws01-r2"]["remake"]
        assert [new[k]["tier"] for k in new] == [1, 3, 4, 5], [new[k]["tier"] for k in new]
        assert not any(c["unitId"] == "u-bpp-Tort-01" for c in plan["newEpisodes"])
        reasons = {s["unitId"]: s["why"] for s in plan["skipped"]}
        assert "not applied" in reasons["u-bpp-Tort-01"]

        # the revision list comes straight after classes
        rv = pick.pick(d, reg, dict(cfg, reviseNext=["u-bpp-WAE-01"]), NOW)
        assert [c["id"] for c in rv["newEpisodes"]] == ["dr-ws06", "wae-ws01", "pp-ws01-r2", "blp-ws06"]
        assert rv["newEpisodes"][1]["tier"] == 2

        # the daily limit: two allowed today, the rest wait for the next run
        two = pick.pick(d, reg, dict(cfg, maxNewPerDay=2), NOW)
        assert [c["id"] for c in two["newEpisodes"]] == ["dr-ws06", "pp-ws01-r2"]
        assert any("today's limit" in s["why"] for s in two["skipped"])

        reps = {r["episodeId"]: r for r in plan["replays"]}
        print("replays:", [(r["episodeId"], r["reason"]) for r in plan["replays"]])
        assert "misses" in reps["contract-ws01"]["reason"]   # misses beat the 7-day replay; one replay per episode
        assert "30 days" in reps["contract-ws02"]["reason"]
        assert "pp-ws01" not in reps                          # being remade, so no replay of the old audio
        assert "7 days" in reps["land-ws01"]["reason"]        # studied 9 days ago, nothing else
        assert [r["episodeId"] for r in plan["replays"]] == ["contract-ws01", "land-ws01", "contract-ws02"]

        # a second run straight after: the chosen work is in the registry, so nothing is chosen twice
        reg2 = json.loads(json.dumps(reg))
        for c in plan["newEpisodes"]:
            reg2["episodes"].append({"id": c["id"], "unitId": c["unitId"], "status": "queued",
                                     "guideHash": c["guideHash"], "madeAt": iso(NOW)})
            for old_ep in reg2["episodes"]:  # what registry.py add-episode --supersedes does
                if old_ep["id"] == c.get("supersedes"):
                    old_ep["supersededBy"] = c["id"]
        for r in plan["replays"]:
            reg2["replays"].append({"id": r["id"], "episodeId": r["episodeId"], "reason": r["reason"], "pubDate": iso(NOW)})
        again = pick.pick(d, reg2, cfg, NOW + timedelta(hours=1))
        assert again["newEpisodes"] == [] and again["replays"] == [], again

        # weekly cap on new episodes: 3 made in the last 7 days
        left = pick.pick(d, reg2, dict(cfg, maxNewPerWeek=3), NOW + timedelta(days=1))
        assert left["newEpisodes"] == []
        # replay cap: 3 replays already in the last 7 days leave no room under a cap of 3
        capped = pick.pick(d, reg2, dict(cfg, maxReplaysPerWeek=3), NOW + timedelta(days=1))
        assert capped["replays"] == []

        # cap of 1: only the top tier is chosen, the rest are listed as skipped with the reason
        one = pick.pick(d, reg, dict(cfg, maxNewPerWeek=1), NOW)
        assert [c["id"] for c in one["newEpisodes"]] == ["dr-ws06"]
        assert any("weekly limit" in s["why"] for s in one["skipped"])

        # a second remake gets the next number
        reg3 = json.loads(json.dumps(reg))
        reg3["episodes"].append(ep("u-bpp-PP-01", "pp-ws01-r2", "stillold", NOW - timedelta(days=1)))
        third = pick.pick(d, reg3, cfg, NOW)
        assert "pp-ws01-r3" in [c["id"] for c in third["newEpisodes"]], [c["id"] for c in third["newEpisodes"]]

        # a paper window: Contract is in FLK1; 10 days before 11 Jan 2027 its published episodes are replayed
        window = pick.pick(d, reg, cfg, datetime(2027, 1, 1, 7, 0, tzinfo=timezone.utc))
        why = {r["episodeId"]: r["reason"] for r in window["replays"]}
        assert any("FLK1" in w for w in why.values()), why
    print("picker OK")


def shabbat():
    f = runmod.in_shabbat
    z = lambda s: datetime.fromisoformat(s).astimezone(timezone.utc)  # noqa: E731
    cases = [("2026-10-23T12:59:00+00:00", False), ("2026-10-23T13:00:00+00:00", True),   # Fri 14:00 BST
             ("2026-10-24T18:59:00+00:00", True), ("2026-10-24T19:00:00+00:00", False),   # Sat 20:00 BST
             ("2026-10-30T13:59:00+00:00", False), ("2026-10-30T14:00:00+00:00", True),   # Fri 14:00 GMT
             ("2026-10-31T19:59:00+00:00", True), ("2026-10-31T20:00:00+00:00", False),   # Sat 20:00 GMT
             ("2026-10-25T06:00:00+00:00", False), ("2026-10-21T06:00:00+00:00", False)]
    for s, want in cases:
        assert f(z(s)) == want, (s, want)
    print("shabbat guard OK")


def feed_follows_remake():
    idx = {"episodes": [
        {"id": "a", "title": "A old", "status": "superseded", "supersededBy": "a-r2", "audio": "audio/a.mp3",
         "pubDate": "2026-10-01T07:00:00+00:00", "recap": ["x"]},
        {"id": "a-r2", "title": "A new", "status": "published", "audio": "audio/a-r2.mp3", "bytes": 5, "seconds": 600,
         "pubDate": "2026-10-10T07:00:00+00:00", "recap": ["y"]}],
        "replays": [{"id": "rp-a-d7", "episodeId": "a", "reason": "7 days", "pubDate": "2026-10-12T07:00:00+00:00"}]}
    items = feed.items_for(idx)
    assert [i["guid"] for i in items] == ["sqe1listen-rp-a-d7", "sqe1listen-a-r2"], [i["guid"] for i in items]
    assert items[0]["ep"]["audio"] == "audio/a-r2.mp3" and items[0]["title"] == "Replay · A new"
    print("feed follows remake OK")


if __name__ == "__main__":
    shabbat()
    feed_follows_remake()
    picker()
    print("ALL OK")
