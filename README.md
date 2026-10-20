# SQE1 Listen

A private podcast feed that turns Zac's checked SQE1 workshop guides into two-presenter episodes (about 13 minutes):
the overall rule, then exam mode, then a four-line recap. This repository holds only scripts, the episode list and
tools. It never holds the guides.

How it works
1. Sunday and Wednesday ~07:00 London, a scheduled Claude task (docs/RUNBOOK.md) reads the app (read only), picks new
   episodes and replays (tools/pick.py), writes each script with a Sonnet helper, checks it twice (tools/check_script.py,
   then an Opus helper), and pushes the scripts and episodes/index.json.
2. A push runs GitHub Actions (.github/workflows/render.yml): tools/run.py renders audio with Gemini TTS, builds
   feed.xml and deploys the site to GitHub Pages. The Gemini key is the repo secret GEMINI_API_KEY.
3. Replays are extra feed items pointing at existing audio (no new writing).
4. From Friday 14:00 to Saturday 20:00 (London) nothing renders or publishes.

Layout: scripts/ (episode scripts), audio/ (rendered MP3s), episodes/index.json (the list), voices.json (chosen voices),
audition/ (voice audition), tools/, prompts/, docs/, reports/, config.json, cover.png.
Test without a key: `python tools/run.py --fake` (makes tone audio).
