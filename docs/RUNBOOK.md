# Runbook: the Sunday and Wednesday producer run

For Claude, in a fresh scheduled session. Follow it exactly. It runs unattended, so do not ask questions: decide, write
down what you decided in the report, and carry on. If something blocks you, put it in the report and stop that item.

## Rules that never bend
- **App data is read only.** Use ArtifactData `get`, `list` or `query` only. Never `set`, `update`, `delete` or `batch`.
  App: the artifact address in your prompt (it is not stored in this repo). Never send Zac's email address anywhere.
- **Never touch the nightly task** (trig_017R1xLboYnY13nu1KNBg5gY), and do not create or change other scheduled tasks.
- **Shabbat:** if it is Friday after 14:00 or Saturday before 20:00 in London, stop at once and say so.
- **Never push guides.** Guide files and their extracts stay under /tmp. Only scripts, the episode list and reports go to GitHub.
- **You never read a guide into your own context.** Only the helpers read the extract text. You may print counts, hashes and
  check results, but never guide text.
- **SRA sample questions** are never used, reworded or imitated (nobody should fetch them).
- Helpers (Agent tool): fresh and short-lived, at most 3 at a time. `model: "sonnet"` writes and revises.
  **`model: "opus"` does every accuracy check.** Each helper gets only the files it needs and nothing else.
- **Pause switch:** if `config.json` in the repo has `"paused": true`, stop at once and say so (Zac or the set-up chat uses
  this when his weekly usage is high). Check it right after cloning.
- If the extra message at the end of the prompt says **DRY RUN**: do steps 1 to 3 and 8 only. No helpers, no commit, no push.

## 1. Set up
1. ToolSearch `select:ArtifactData` to load it. If it will not load, stop and say so.
2. Find the repo with `list_repos` (query `sqe1-listen`), attach it with `add_repo` (access `push`), run the clone command it
   gives, then `register_repo_root`. Work inside the clone and `git pull` first. If there is no such repo, stop and say so.
   Before committing, set a plain identity in the clone: `git config user.name "SQE1 Listen producer"` and
   `git config user.email "noreply@users.noreply.github.com"` (never Zac's own email).
3. `mkdir -p /tmp/sqe1/data /tmp/sqe1/src /tmp/sqe1/out`. Python 3 with the standard library is enough for every tool.

## 2. Read the app (read only, all with out_dir=/tmp/sqe1/data)
The long file lists these calls print are normal; do not copy them anywhere.
- `list` collection `data/users/me/library/units`, query limit 1000.
- `list` collection `data/users/me/library/builds`, limit 1000.
- `list` collection `data/users/me/library/guides`, limit 1000 (the guides are large; they are saved to disk, not shown).
- `query` collection `data/users/me/library/board`, where `["kind","==","class"]`, limit 500.
- `query` collection `data/users/me/library/board`, where `["kind","==","conf"]` and `["missAt",">=","<14 days ago, ISO>"]`.
- `query` collection `data/users/me/mcqrules/entries`, where `["createdAt",">=","<14 days ago, ISO>"]`, limit 1000.
If a call fails, retry once; if it still fails, report it and stop.

## 3. Plan
`python tools/pick.py --data /tmp/sqe1/data --out /tmp/sqe1/plan.json` and read plan.json (it holds no guide text).
It lists `newEpisodes`, `replays` and `skipped` with reasons. It already applies: only workshops whose v3 guide is applied
in the live app; at most 8 new episodes a week; at most 10 replays a week.

## 4. Each new episode (steps a to g), at most 3 at a time
a. Extract: `python tools/guide_extract.py /tmp/sqe1/data/data/users/me/library/guides/<unitId>.json /tmp/sqe1/src/<id>.txt`.
   It prints `<hash> <words>`. The hash must equal the plan's `guideHash`; if not, hold the episode (the guide changed mid-run).
b. Writer (Sonnet helper): give it prompts/writer.md with the placeholders filled ({GUIDE_TEXT} = /tmp/sqe1/src/<id>.txt,
   {OUT_PATH} = /tmp/sqe1/out/<id>.txt, {TITLE_PREFIX}, {WORKSHOP} from the plan). It reads only those files and the style sample.
c. Code check: `python tools/check_script.py /tmp/sqe1/out/<id>.txt /tmp/sqe1/src/<id>.txt`.
   On errors, run the reviser once (Sonnet, prompts/reviser.md, errors written to /tmp/sqe1/out/<id>.problems.txt) and check again.
   Still failing: hold (step g).
d. Accuracy check (**Opus helper**, prompts/checker.md): it writes JSON to /tmp/sqe1/out/<id>.check.json.
e. If the verdict is "fail": first `python tools/apply_fixes.py /tmp/sqe1/out/<id>.txt /tmp/sqe1/out/<id>.check.json`
   (it swaps in the checker's exact replacement lines; keep a copy of the script first). If it applied every fix, run the
   code check and the Opus check again. If some were not applied (it exits 1), use the reviser once (Sonnet) with those
   problems, then the code check and the Opus check again. Only one fixing round is allowed: still failing means hold.
f. Pass (code OK and Opus "pass"): copy the script to `scripts/<id>.txt`, then
   `python tools/registry.py add-episode --unit <unitId> --id <id> --script scripts/<id>.txt --guide-hash <hash> --supersedes <old id, if the plan has one> --checks "code ok; opus pass (round N)" --check-json /tmp/sqe1/out/<id>.check.json`.
g. Hold: copy the script to `scripts/held/<id>.txt`, then `python tools/registry.py add-episode ... --hold "<one-line reason>"`.
   Held episodes are never rendered. List them with reasons in the report.

## 5. Replays
For each entry in plan.json `replays`: `python tools/registry.py add-replay --episode <episodeId> --reason "<reason>" --id <id>`.
No new writing is needed: the feed item points at the existing audio.

## 6. Publish
`git add scripts episodes reports && git commit -m "<date>: new episodes and replays" && git push origin HEAD`.
The push starts GitHub Actions, which makes the audio and updates the feed (about 10 minutes). Do not wait for it.

## 7. Report
Write `reports/<yyyy-mm-dd>.md` and print the same text as your final message, in plain British English:
- New episodes (title), replays (title and why), held episodes (title and why), skipped counts by reason.
- What you used: number of helpers (Sonnet / Opus), rounds of fixing, and the tools you called (rough count).
- Anything odd, and anything Zac should decide.
- Starred details left out of an episode to keep it near 14 minutes: put only the COUNT per episode in the report file.
  The checker's sentences about them are guide content: show them in your final message only, never in a file in the repo.
Commit the report with step 6 (write it before committing).

## 8. Dry run
Stop after step 3. Report what the plan would do (new episodes, replays, skipped) and what you used. Nothing is committed.
