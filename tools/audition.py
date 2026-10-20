"""Voice audition: render the approved sample's opening in several voice pairs.

audition/candidates.json:
  {"candidates": [
     {"id": "A", "label": "...", "kind": "pair",    "lead": "Achird", "second": "Callirrhoe"},
     {"id": "C", "label": "...", "kind": "library", "lead": {"gender": "male", "pick": 0},
                                                      "second": {"gender": "female", "pick": 0}},
     {"id": "D", "label": "...", "kind": "design",  "lead":   {"gender": "male",   "prompt": "..."},
                                                      "second": {"gender": "female", "prompt": "..."}}]}

kind "pair": two prebuilt voices, one two-speaker request per chunk.
kind "library": British voices found with voices.list(), rendered line by line.
kind "design": voices made from a text description (voices.create), rendered line by line.
A candidate that fails is reported in words on the page; the others still run.
"""
import json
import os
import sys
import traceback
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import render  # noqa: E402
from scriptfmt import parse  # noqa: E402


def list_british(cl, gender, want_conversational=True):
    """Return British English library voices (list of dicts) for a gender, best guess first."""
    found, seen = [], set()
    for kw in ({"language_code": ["en-GB"]}, {"region_code": ["GB"]}, {"accent": ["British"]}):
        token = None
        while True:
            args = dict(kw, gender=[gender], page_size=100)
            if token:
                args["page_token"] = token
            res = cl.voices.list(**args)
            for v in (res.voices or []):
                vid = getattr(v, "id", None)
                if vid and vid not in seen:
                    seen.add(vid)
                    found.append({k: getattr(v, k, None) for k in
                                  ("id", "display_name", "accent", "gender", "language_code", "persona",
                                   "context", "description", "type")})
            token = getattr(res, "next_page_token", None)
            if not token:
                break
        if found:
            break

    def rank(v):
        ctx = (v.get("context") or "").lower()
        return (0 if "conversation" in ctx else 1 if "narrat" in ctx or "audiobook" in ctx else 2)

    return sorted(found, key=rank) if want_conversational else found


def dump_library(cl, out_dir, log=print):
    """Save everything Google says about its British library voices, so a person (or Claude) can choose well."""
    out = {}
    for gender in ("male", "female"):
        rows, seen, token = [], set(), None
        while True:
            args = dict(language_code=["en-GB"], gender=[gender], page_size=100)
            if token:
                args["page_token"] = token
            res = cl.voices.list(**args)
            for v in (res.voices or []):
                if getattr(v, "id", None) in seen:
                    continue
                seen.add(v.id)
                try:
                    rows.append(v.model_dump(mode="json", exclude_none=True))
                except Exception:  # noqa: BLE001
                    rows.append({k: str(getattr(v, k, None)) for k in ("id", "display_name", "persona", "context", "description")})
            token = getattr(res, "next_page_token", None)
            if not token:
                break
        out[gender] = rows
        log("library: %d British %s voices" % (len(rows), gender))
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "library-voices.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")


def design_voice(cl, spec, name):
    v = cl.voices.create(
        store=True,
        voice={"type": "prompted", "display_name": name, "gender": spec.get("gender", "female"),
               "language_code": "en-GB", "region_code": "GB", "accent": "British",
               "prompted": {"input": spec["prompt"]}},
    )
    return v.id


def resolve(cand, cl, log):
    """Return a voices dict for render.render_pcm, plus notes about which voices were used."""
    kind = cand["kind"]
    if kind == "pair":
        return ({"mode": "pair", "lead": {"name": "Will", "voice": cand["lead"]},
                 "second": {"name": "Hannah", "voice": cand["second"]}},
                "prebuilt: Will = %s, Hannah = %s" % (cand["lead"], cand["second"]))
    picked = {}
    for role in ("lead", "second"):
        spec = cand[role]
        if spec.get("id"):  # a voice we already have (a library voice, or one designed earlier)
            picked[role] = (spec["id"], spec.get("name") or spec["id"])
        elif spec.get("prompt"):  # a voice designed from a description
            try:
                vid = design_voice(cl, spec, "SQE1 Listen %s %s" % (cand["id"], role))
            except Exception as e:  # noqa: BLE001
                raise RuntimeError("could not design the %s voice (%s): %s" % (role, spec["gender"], str(e)[:200])) from e
            picked[role] = (vid, spec.get("name") or ("designed: " + spec["prompt"][:80]))
        else:  # the first British library voice for that gender
            vs = list_british(cl, spec["gender"])
            if not vs:
                raise RuntimeError("no British %s voices found in the library" % spec["gender"])
            v = vs[min(spec.get("pick", 0), len(vs) - 1)]
            picked[role] = (v["id"], "%s (%s, %s)" % (v.get("display_name") or v["id"], v.get("accent"),
                                                      v.get("persona")))
    voices = {"mode": "line", "lead": {"name": "Will", "voice": picked["lead"][0]},
              "second": {"name": "Hannah", "voice": picked["second"][0]}}
    note = "Will = %s; Hannah = %s" % (picked["lead"][1], picked["second"][1])
    return voices, note, {"lead": picked["lead"][0], "second": picked["second"][0]}


def run(root, out_dir, fake=False, log=print, only=None, dump=False, fresh=False):
    """only: list of candidate ids to (re)run; the others keep their result from the earlier report.json."""
    root, out_dir = Path(root), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfile = json.load(open(root / "audition" / "candidates.json", encoding="utf-8"))
    cands, intro = cfile["candidates"], cfile.get("intro")
    sample = parse((root / "audition" / "sample.txt").read_text(encoding="utf-8"))
    cl = None if fake else render.client()
    earlier = {}
    if fresh:  # a new round: the old clips and results are dropped from the page
        for f in out_dir.glob("pair-*.mp3"):
            f.unlink()
    elif only and (out_dir / "report.json").exists():
        earlier = {r["id"]: r for r in json.load(open(out_dir / "report.json", encoding="utf-8"))}
    if dump and cl is not None:
        try:
            dump_library(cl, out_dir, log)
        except Exception as e:  # noqa: BLE001
            log("  library list failed: %s: %s" % (type(e).__name__, str(e)[:200]))
    results = []
    quota_msg = None
    for cand in cands:
        if only and cand["id"] not in only:
            if cand["id"] in earlier:
                results.append(earlier[cand["id"]])
            continue
        r = {"id": cand["id"], "label": cand["label"], "ok": False}
        if quota_msg:   # Google's daily limit is used up: do not even try the rest
            r["error"] = "not tried: Google's daily limit for speech requests was used up (it resets at 08:00 London)"
            r["quota"] = quota_msg
            results.append(r)
            continue
        try:
            log("candidate %s: %s" % (cand["id"], cand["label"]))
            res = resolve(cand, cl, log)
            voices, note = res[0], res[1]
            if len(res) > 2:
                r["voiceIds"] = res[2]
            pcm = render.render_pcm(sample["turns"], voices, fake=fake, log=log)
            render.encode_mp3(pcm, out_dir / ("pair-%s.mp3" % cand["id"]), "Voice audition " + cand["id"])
            r.update(ok=True, note=note, voices=voices, audio="pair-%s.mp3" % cand["id"])
        except render.QuotaExhausted as e:
            quota_msg = str(e)
            r["error"] = "Google's daily limit for speech requests was used up (it resets at 08:00 London)"
            r["quota"] = quota_msg
            log("  STOPPED: " + quota_msg)
        except Exception as e:  # noqa: BLE001
            r["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            log("  FAILED: " + r["error"])
            traceback.print_exc()
        results.append(r)
    (out_dir / "report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    page(out_dir, results, intro)
    return results


def page(out_dir, results, intro=None):
    rows = []
    for r in results:
        if r["ok"]:
            rows.append("<section><h2>Pair %s</h2><p>%s</p><p><small>%s</small></p>"
                        "<audio controls preload=\"none\" src=\"%s\"></audio></section>"
                        % (escape(r["id"]), escape(r["label"]), escape(r["note"]), escape(r["audio"])))
        else:
            rows.append("<section><h2>Pair %s</h2><p>%s</p><p><strong>Did not work:</strong> %s</p></section>"
                        % (escape(r["id"]), escape(r["label"]), escape(r.get("error", ""))))
    html = ("<!doctype html><html lang=\"en-GB\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\"><title>Voice audition</title>"
            "<style>body{font:18px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}"
            "section{border:2px solid #333;border-radius:8px;padding:1rem;margin:1rem 0}"
            "audio{width:100%}</style></head><body><h1>Voice audition</h1>"
            "<p>" + escape(intro or "Same opening, different voices. Listen to each, then tell Claude the letter you like best "
            "(and say if you want a different man or woman from the same group).") + "</p>"
            + "".join(rows) + "</body></html>")
    (Path(out_dir) / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    fake = "--fake" in sys.argv
    out = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "_site/audition"
    run(".", out, fake=fake)
