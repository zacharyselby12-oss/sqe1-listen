#!/usr/bin/env python3
"""Small bookkeeping commands for episodes/index.json (so the AI never edits JSON by hand).

  registry.py add-episode --unit U --id ID --script scripts/ID.txt --guide-hash H [--pilot]
                          [--supersedes OLD] [--hold REASON] [--checks TEXT] [--check-json FILE]
  registry.py add-replay  --episode ID --reason TEXT [--id RID] [--pub ISO]
  registry.py approve ID            # pilots: let the episode go into the feed
  registry.py retire ID             # take an episode out of the feed
  registry.py show
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scriptfmt import add_header_fields, parse, script_hash  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REG = ROOT / "episodes" / "index.json"


def load():
    return json.loads(REG.read_text(encoding="utf-8")) if REG.exists() else {"episodes": [], "replays": []}


def save(idx):
    REG.parent.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(idx, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_episode(a):
    idx = load()
    path = ROOT / a.script
    text = path.read_text(encoding="utf-8")
    sc = parse(text)
    meta = sc["meta"]
    if a.id in {e["id"] for e in idx["episodes"]}:
        raise SystemExit("episode id already exists: " + a.id)
    made = now_iso()
    text = add_header_fields(text, id=a.id, unit=a.unit, guide_hash=a.guide_hash, made=made)
    path.write_text(text, encoding="utf-8")
    ep = {"id": a.id, "unitId": a.unit, "title": meta.get("title", a.id), "guideHash": a.guide_hash,
          "script": a.script, "scriptHash": script_hash(text), "audio": "audio/%s.mp3" % a.id,
          "recap": meta.get("recap", []), "madeAt": made,
          "status": "held" if a.hold else "queued", "pilot": bool(a.pilot), "approved": False,
          "checks": a.checks or ""}
    if a.hold:
        ep["holdReason"] = a.hold
    if a.check_json and Path(a.check_json).exists():
        cj = json.loads(Path(a.check_json).read_text(encoding="utf-8"))
        # only the count goes in the (public) episode list: the sentences are guide content and stay out of GitHub
        ep["omittedStarred"] = len(cj.get("coverage", []))
        ep["banterLines"] = cj.get("banter_lines")
    if a.supersedes:
        for e in idx["episodes"]:
            if e["id"] == a.supersedes:
                e["supersededBy"] = a.id
        ep["supersedes"] = a.supersedes
    idx["episodes"].append(ep)
    save(idx)
    print("added", a.id, ep["status"])


def add_replay(a):
    idx = load()
    ep = next((e for e in idx["episodes"] if e["id"] == a.episode), None)
    if not ep:
        raise SystemExit("no such episode: " + a.episode)
    rid = a.id or "rp-%s-%s" % (a.episode, datetime.now(timezone.utc).strftime("%Y%m%d"))
    if rid in {r["id"] for r in idx["replays"]}:
        raise SystemExit("replay id already exists: " + rid)
    idx["replays"].append({"id": rid, "episodeId": a.episode, "reason": a.reason, "pubDate": a.pub or now_iso()})
    save(idx)
    print("added", rid)


def set_flag(a, **kw):
    idx = load()
    for e in idx["episodes"]:
        if e["id"] == a.id:
            e.update(kw)
            save(idx)
            print("updated", a.id, kw)
            return
    raise SystemExit("no such episode: " + a.id)


def show(_a):
    idx = load()
    for e in idx["episodes"]:
        print("%-22s %-10s pilot=%-5s approved=%-5s %s" % (e["id"], e["status"], e.get("pilot"), e.get("approved"),
                                                           e["title"]))
    print("replays:", len(idx["replays"]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add-episode")
    p.add_argument("--unit", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--guide-hash", required=True)
    p.add_argument("--pilot", action="store_true")
    p.add_argument("--supersedes")
    p.add_argument("--hold")
    p.add_argument("--checks")
    p.add_argument("--check-json", help="the Opus check result: its coverage notes are kept on the episode")
    p.set_defaults(fn=add_episode)
    p = sub.add_parser("add-replay")
    p.add_argument("--episode", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--id")
    p.add_argument("--pub")
    p.set_defaults(fn=add_replay)
    p = sub.add_parser("approve")
    p.add_argument("id")
    p.set_defaults(fn=lambda a: set_flag(a, approved=True))
    p = sub.add_parser("retire")
    p.add_argument("id")
    p.set_defaults(fn=lambda a: set_flag(a, status="retired"))
    p = sub.add_parser("show")
    p.set_defaults(fn=show)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
