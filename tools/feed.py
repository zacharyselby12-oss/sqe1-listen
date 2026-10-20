"""Build the podcast feed (RSS with Apple Podcasts tags) from episodes/index.json.

Only episodes with status "published" appear. Replays are extra items that point at the same audio
file as the episode they repeat (new guid, new date, title "Replay · ...").
"""
import json
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}
for _k, _v in NS.items():
    ET.register_namespace(_k, _v)


def q(ns, tag):
    return "{%s}%s" % (NS[ns], tag)


def parse_dt(s):
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def hms(sec):
    sec = int(sec or 0)
    return "%d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def _text(parent, tag, text, **attrs):
    el = ET.SubElement(parent, tag, attrs)
    el.text = text
    return el


def _notes(ep, replay_reason=None):
    lines = list(ep.get("recap") or [])
    body = "\n".join("• " + l for l in lines) if lines else ep["title"]
    if replay_reason:
        body = "Replay (%s).\n%s" % (replay_reason, body)
    return body


def items_for(index):
    eps = {e["id"]: e for e in index.get("episodes", [])}
    items = []
    for e in eps.values():
        if e.get("status") == "published" and e.get("pubDate"):
            items.append({"guid": "sqe1listen-" + e["id"], "title": e["title"], "ep": e,
                          "pub": parse_dt(e["pubDate"]), "notes": _notes(e)})
    for r in index.get("replays", []):
        e = eps.get(r["episodeId"])
        hops = 0
        while e and e.get("status") == "superseded" and hops < 10:  # follow the remake, so the audio never goes missing
            e = eps.get(e.get("supersededBy"))
            hops += 1
        if not e or e.get("status") != "published":
            continue
        items.append({"guid": "sqe1listen-" + r["id"], "title": "Replay · " + e["title"], "ep": e,
                      "pub": parse_dt(r["pubDate"]), "notes": _notes(e, r.get("reason"))})
    items.sort(key=lambda i: i["pub"], reverse=True)
    return items


def build(index, config, base_url, out_path):
    show = config["show"]
    base_url = base_url.rstrip("/")
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    _text(ch, "title", show["title"])
    _text(ch, "link", base_url + "/")
    _text(ch, "description", show["description"])
    _text(ch, "language", show.get("language", "en-gb"))
    ET.SubElement(ch, q("atom", "link"), {"href": base_url + "/feed.xml", "rel": "self",
                                          "type": "application/rss+xml"})
    _text(ch, q("itunes", "author"), show.get("author", show["title"]))
    _text(ch, q("itunes", "summary"), show["description"])
    ET.SubElement(ch, q("itunes", "image"), {"href": base_url + "/cover.png"})
    cat = ET.SubElement(ch, q("itunes", "category"), {"text": "Education"})
    ET.SubElement(cat, q("itunes", "category"), {"text": "Courses"})
    _text(ch, q("itunes", "explicit"), "false")
    _text(ch, q("itunes", "type"), "episodic")
    items = items_for(index)
    if items:
        _text(ch, "lastBuildDate", format_datetime(items[0]["pub"]))
    for it in items:
        e = it["ep"]
        item = ET.SubElement(ch, "item")
        _text(item, "title", it["title"])
        _text(item, "description", it["notes"])
        _text(item, q("itunes", "summary"), it["notes"])
        ET.SubElement(item, "enclosure", {"url": "%s/%s" % (base_url, e["audio"]),
                                          "length": str(e.get("bytes", 0)), "type": "audio/mpeg"})
        _text(item, "guid", it["guid"], isPermaLink="false")
        _text(item, "pubDate", format_datetime(it["pub"]))
        _text(item, q("itunes", "duration"), hms(e.get("seconds")))
        _text(item, q("itunes", "episodeType"), "full")
        _text(item, q("itunes", "explicit"), "false")
    ET.indent(rss, space="  ")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(rss).write(out_path, encoding="utf-8", xml_declaration=True)
    return len(items)


if __name__ == "__main__":
    idx = json.load(open(sys.argv[1], encoding="utf-8"))
    cfg = json.load(open(sys.argv[2], encoding="utf-8"))
    print(build(idx, cfg, sys.argv[3], sys.argv[4]), "items")
