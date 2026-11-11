#!/usr/bin/env python3
"""(b199) Check the website's episode addresses after a deployment (read only).

  python tools/check_site_audio.py <feed file, e.g. _site/feed.xml> [site address; default: the feed's own <link>]

For every enclosure in the feed that is on the site (not the release), it asks for the first two bytes, without following
redirects, and needs: 206 Partial Content, Content-Type audio/mpeg or audio/mp3 (GitHub Pages serves .mp3 as audio/mp3), and a Content-Range total equal to the enclosure's length.
A failure is tried once more after 20 seconds (a just-deployed site can lag). Prints one line per problem (a GitHub warning in
Actions) and a summary; exits 1 if any address failed.
"""
import sys
import time
import urllib.error
import urllib.request
from xml.etree import ElementTree as ET


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None   # a redirect is itself the fault being checked for


def probe(url, length, opener=None, timeout=20):
    """None if the address is right, else what is wrong."""
    opener = opener or urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"Range": "bytes=0-1", "User-Agent": "sqe1-listen-check"})
    try:
        with opener.open(req, timeout=timeout) as r:
            status, ctype, crange = r.status, r.headers.get("Content-Type", ""), r.headers.get("Content-Range", "")
    except urllib.error.HTTPError as e:
        where = e.headers.get("Location") if e.headers else None
        return "answered %d%s" % (e.code, " (redirect to %s)" % where if where else "")
    except Exception as e:  # noqa: BLE001
        return "no answer: %s" % e
    problems = []
    if status != 206:
        problems.append("answered %d, not 206" % status)
    if ctype.split(";")[0].strip().lower() not in ("audio/mpeg", "audio/mp3"):   # Pages sends audio/mp3 for .mp3 (measured live, r29)
        problems.append("Content-Type %r, not audio/mpeg or audio/mp3" % ctype)
    total = crange.rsplit("/", 1)[-1] if "/" in crange else ""
    if total != str(length):
        problems.append("file is %s bytes, the feed says %s" % (total or "?", length))
    return "; ".join(problems) or None


def enclosures(feed_path, site):
    site = site.rstrip("/") + "/"
    out = []
    for enc in ET.parse(feed_path).getroot().iter("enclosure"):
        url = enc.get("url") or ""
        if url.startswith(site) and (url, enc.get("length")) not in out:
            out.append((url, enc.get("length")))
    return out


def main(argv, opener=None, wait=20):
    feed_path = argv[1]
    site = argv[2] if len(argv) > 2 else ET.parse(feed_path).getroot().findtext("channel/link")   # the feed's own site address
    todo = enclosures(feed_path, site)
    bad = {u: probe(u, n, opener) for u, n in todo}
    if any(bad.values()) and wait:
        time.sleep(wait)
        bad = {u: (probe(u, n, opener) if bad[u] else None) for u, n in todo}
    for u, why in bad.items():
        if why:
            print("::warning::website episode address failed: %s: %s" % (u, why), flush=True)
    failed = sum(1 for w in bad.values() if w)
    print("website episode addresses: %d checked, %d failed" % (len(todo), failed), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
