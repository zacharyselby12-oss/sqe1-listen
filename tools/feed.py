"""Build the podcast feeds (RSS with Apple Podcasts tags) from episodes/index.json.

feed.xml has everything. feeds/<area>.xml has one area of law (for example feeds/PP.xml for Property Practice),
in workshop order, so each area shows up as its own show in Apple Podcasts. subscribe/index.html lists them all.
Only episodes with status "published" appear. Replays are extra items that point at the same audio
file as the episode they repeat (new guid, new date, title "Replay · ...").
"""
import json
import re
import sys
from html import escape
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


AREA_RE = re.compile(r"^u-[a-z]+-([A-Za-z0-9]+)-(\d+)$")


def area_of(ep):
    """("PP", 6) for unit u-bpp-PP-06; (None, None) if the unit id has another shape."""
    m = AREA_RE.match(ep.get("unitId") or "")
    return (m.group(1), int(m.group(2))) if m else (None, None)


def items_for(index):
    eps = {e["id"]: e for e in index.get("episodes", [])}
    items = []
    for e in eps.values():
        if e.get("status") == "published" and e.get("pubDate"):
            items.append({"guid": "sqe1listen-" + e["id"], "title": e["title"], "ep": e,
                          "pub": parse_dt(e["pubDate"]), "notes": _notes(e), "replay": False})
    for r in index.get("replays", []):
        e = eps.get(r["episodeId"])
        hops = 0
        while e and e.get("status") == "superseded" and hops < 10:  # follow the remake, so the audio never goes missing
            e = eps.get(e.get("supersededBy"))
            hops += 1
        if not e or e.get("status") != "published":
            continue
        items.append({"guid": "sqe1listen-" + r["id"], "title": "Replay · " + e["title"], "ep": e,
                      "pub": parse_dt(r["pubDate"]), "notes": _notes(e, r.get("reason")), "replay": True})
    items.sort(key=lambda i: i["pub"], reverse=True)
    return items


def build(index, config, base_url, out_path, area=None):
    """Write one feed: everything (area=None) or one area of law. Returns the number of items."""
    show = config["show"]
    names = config.get("areaNames", {})
    base_url = base_url.rstrip("/")
    if area:
        area_name = names.get(area, area)
        title, desc = "%s · %s" % (show["title"], area_name), "%s. %s" % (area_name, show["description"])
        self_path, image, kind = "feeds/%s.xml" % area, "%s/covers/%s.png" % (base_url, area), "serial"
    else:
        title, desc, self_path, image, kind = show["title"], show["description"], "feed.xml", base_url + "/cover.png", "episodic"
    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    _text(ch, "title", title)
    _text(ch, "link", base_url + "/")
    _text(ch, "description", desc)
    _text(ch, "language", show.get("language", "en-gb"))
    ET.SubElement(ch, q("atom", "link"), {"href": "%s/%s" % (base_url, self_path), "rel": "self",
                                          "type": "application/rss+xml"})
    _text(ch, q("itunes", "author"), show.get("author", show["title"]))
    _text(ch, q("itunes", "summary"), desc)
    ET.SubElement(ch, q("itunes", "image"), {"href": image})
    cat = ET.SubElement(ch, q("itunes", "category"), {"text": "Education"})
    ET.SubElement(cat, q("itunes", "category"), {"text": "Courses"})
    _text(ch, q("itunes", "explicit"), "false")
    _text(ch, q("itunes", "type"), kind)   # an area is "serial": Apple Podcasts lists it in workshop order
    _text(ch, q("itunes", "block"), "Yes")  # private: never listed in Apple's directory
    items = [it for it in items_for(index) if area is None or area_of(it["ep"])[0] == area]
    if items:
        _text(ch, "lastBuildDate", format_datetime(items[0]["pub"]))
    for it in items:
        e = it["ep"]
        item = ET.SubElement(ch, "item")
        _text(item, "title", it["title"])
        _text(item, "description", it["notes"])
        _text(item, q("itunes", "summary"), it["notes"])
        ET.SubElement(item, "enclosure", {"url": e.get("audioUrl") or "%s/%s" % (base_url, e["audio"]),
                                          "length": str(e.get("bytes", 0)), "type": "audio/mpeg"})
        _text(item, "guid", it["guid"], isPermaLink="false")
        _text(item, "pubDate", format_datetime(it["pub"]))
        _text(item, q("itunes", "duration"), hms(e.get("seconds")))
        if it["replay"]:
            _text(item, q("itunes", "episodeType"), "bonus")
        else:
            _text(item, q("itunes", "episodeType"), "full")
            ws = area_of(e)[1]
            if area and ws:
                _text(item, q("itunes", "episode"), str(ws))   # workshop number, so the area is in course order
        _text(item, q("itunes", "explicit"), "false")
    ET.indent(rss, space="  ")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(rss).write(out_path, encoding="utf-8", xml_declaration=True)
    return len(items)


def build_all(index, config, base_url, site):
    """feed.xml, one feed per area of law that has episodes, and the page that lists them. Returns item counts."""
    site = Path(site)
    counts = {"all": build(index, config, base_url, site / "feed.xml")}
    areas = sorted({area_of(it["ep"])[0] for it in items_for(index)} - {None})
    for a in areas:
        counts[a] = build(index, config, base_url, site / "feeds" / ("%s.xml" % a), area=a)
    subscribe_page(config, base_url, counts, site / "subscribe" / "index.html")
    return counts


def subscribe_page(config, base_url, counts, out):
    names = config.get("areaNames", {})
    base_url = base_url.rstrip("/")
    host_path = re.sub(r"^https?://", "", base_url)

    def block(label, path, n, note=""):
        url = "%s/%s" % (base_url, path)
        return ("<section><h2>%s</h2><p>%s</p>"
                "<p><a class=\"btn\" href=\"podcast://%s/%s\">Open in Apple Podcasts</a></p>"
                "<p><input readonly value=\"%s\" aria-label=\"Feed address\"> "
                "<button onclick=\"navigator.clipboard.writeText('%s');this.textContent='Copied'\">Copy link</button></p>"
                "</section>" % (escape(label), escape("%d episode%s%s" % (n, "" if n == 1 else "s", note)),
                                host_path, path, escape(url), escape(url)))

    rows = [block("Everything in one show", "feed.xml", counts.get("all", 0),
                  " (every area together; follow this OR the areas below, not both)")]
    for code, name in names.items():
        if code in counts:
            rows.append(block(name, "feeds/%s.xml" % code, counts[code]))
    waiting = [name for code, name in names.items() if code not in counts]
    html = ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><meta name=\"robots\" content=\"noindex\">"
            "<title>Add SQE1 Listen</title><style>body{font:18px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;"
            "padding:0 1rem}section{border:2px solid #333;border-radius:8px;padding:1rem;margin:1rem 0}"
            "input{width:100%;font-size:14px;padding:.4rem}.btn{display:inline-block;border:2px solid #333;border-radius:8px;"
            "padding:.5rem 1rem;text-decoration:none;font-weight:bold}button{font-size:16px;margin-top:.4rem}</style></head>"
            "<body><h1>Add SQE1 Listen to Apple Podcasts</h1>"
            "<p><strong>The sure way, on your iPhone:</strong> tap <strong>Copy link</strong> under the show you want. "
            "Open Apple Podcasts, go to <strong>Library</strong>, tap the <strong>three dots</strong> at the top right, "
            "choose <strong>Follow a Show by URL</strong>, paste, and tap <strong>Follow</strong>. "
            "On a Mac: in the Podcasts app, <strong>File</strong>, then <strong>Follow a Show by URL</strong>.</p>"
            "<p>The quick way: tap <strong>Open in Apple Podcasts</strong>, then <strong>Follow</strong>. "
            "If it says it cannot connect, use the sure way.</p>"
            + "".join(rows)
            + ("<p>Areas with no episodes yet (each appears here once its first episode is out): %s.</p>"
               % escape(", ".join(waiting)) if waiting else "")
            + "</body></html>")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    idx = json.load(open(sys.argv[1], encoding="utf-8"))
    cfg = json.load(open(sys.argv[2], encoding="utf-8"))
    print(build(idx, cfg, sys.argv[3], sys.argv[4]), "items")
