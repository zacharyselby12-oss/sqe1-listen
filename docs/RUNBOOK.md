# Runbook: the daily producer run (08:05 London, Sunday to Friday, just after Google's daily speech reset)

For Claude. Since 21 Oct 2026 the run happens in the set-up chat, when a scheduled wake-up booked with Zac's agreement
delivers it there (a fresh scheduled session can attach this repo but can't push to it). Follow this exactly. It runs
unattended, so do not ask questions: decide, write down what you decided in the report, and carry on. If something
blocks you, put it in the report and stop that item.

## Rules that never bend
- **App data is read only.** Use ArtifactData `get`, `list` or `query` only. Never `set`, `update`, `delete` or `batch`.
  App: the artifact address in the wake-up message (it is not stored in this repo). Never send Zac's email address anywhere.
- **Never touch the nightly task** (trig_017R1xLboYnY13nu1KNBg5gY) or the app's code. Create no new scheduled tasks.
- **Shabbat:** if it is Friday after 14:00 or Saturday before 20:00 in London, stop at once and say nothing.
- **Never push guides.** Guide files and their extracts stay under /tmp. Only scripts, the episode list and reports go to GitHub.
- **You never read a guide into your own context.** Only the helpers read the extract text. You may print counts, hashes and
  check results, but never guide text.
- **SRA sample questions** are never used, reworded or imitated (nobody should fetch them).
- Helpers (Agent tool): fresh and short-lived, at most 2 at a time. `model: "sonnet"` writes and revises.
  **`model: "opus"` does every accuracy check** (two per episode, below). Each helper gets only the files it needs.
- **Pause switch:** if `config.json` has `"paused": true`, stop at once and say so (used when Zac's weekly usage is high).
- If the message says **DRY RUN**: do steps 1 to 3 and 8 only. No helpers. The only commit is the dry-run report.

## 1. Set up
1. ToolSearch `select:ArtifactData` to load it. If it will not load, stop and say so.
2. The clone is /home/claude/sqe1-listen: `git pull` there. If the folder is gone (the workspace was reset), attach the
   repo with `add_repo` (owner zacharyselby12-oss, repo sqe1-listen, access `push`), run the clone command it gives into
   /home/claude/sqe1-listen, then `register_repo_root`. Commits use the identity `SQE1 Listen producer`
   <noreply@users.noreply.github.com> (never Zac's own email).
3. `rm -rf /tmp/sqe1 && mkdir -p /tmp/sqe1/data /tmp/sqe1/src /tmp/sqe1/out`. Python 3 with the standard library is enough.
4. Audio first: if `episodes/index.json` has an episode "queued" whose audio is overdue (the half-hourly render runs
   haven't made it), look at the last `gh run list --workflow render.yml --limit 3` and fix what is ours; never start a
   run that would go over Google's daily allowance.

## 2. Read the app (read only, all with out_dir=/tmp/sqe1/data)
The long file lists these calls print are normal; do not copy them anywhere.
- `list` collection `data/users/me/library/units`, query limit 1000.
- `list` collection `data/users/me/library/builds`, limit 1000.
- `list` collection `data/users/me/library/guides`, limit 1000 (the guides are large; they are saved to disk, not shown).
- `get` collection `data/users/me/library/cpoints`, doc_id `cpo-order` (the app's own priority order; if it is missing,
  carry on: pick.py then uses its own rules).
- `query` collection `data/users/me/library/board`, where `["kind","==","class"]`, limit 500.
- `query` collection `data/users/me/library/board`, where `["kind","==","conf"]` and `["missAt",">=","<14 days ago, ISO>"]`.
- `query` collection `data/users/me/mcqrules/entries`, where `["createdAt",">=","<14 days ago, ISO>"]`, limit 1000.
If a call fails, retry once; if it still fails, report it and stop.

## 3. Plan
`python3 tools/pick.py --data /tmp/sqe1/data --out /tmp/sqe1/plan.json` and read plan.json (it holds no guide text).
It lists `newEpisodes`, `replays` and `skipped` with reasons. It already applies: only workshops whose v3 guide is applied
in the live app; the priority order (1. a class in the next 7 days, earliest first; 2. his revision plan: config.json `reviseNext`, then
the app's own study plan for the next 7 days; 3. a class 7 to 14 days ahead; 4. a class held in the last 3 days;
5. studied in the last 14 days; 6. two or more misses; 7. any other applied guide); at most `maxNewPerDay` new episodes a day and
`maxNewPerWeek` a week; at most 10 replays a week.
If `newEpisodes` and `replays` are both empty, skip to step 7 and write a one-line report: nothing new today.
Take the new episodes in the plan's order, as many as fit today: each costs about 25 speech requests (see
reports/speech-requests.json; Google allows 100 a day) and a share of Zac's weekly Claude usage.

## 4. Each new episode, at most 2 at a time
a. Extract: `python3 tools/guide_extract.py /tmp/sqe1/data/data/users/me/library/guides/<unitId>.json /tmp/sqe1/src/<id>.txt`.
   It prints `<hash> <words>`. The hash must equal the plan's `guideHash`; if not, hold the episode (the guide changed mid-run).
b. Parts: up to about 7,500 source words is one episode. Longer: two parts, `<id>-p1` and `<id>-p2`, splitting the
   source's SECTION list into two runs of whole sections with about the same number of words each (from the section
   headings and word counts; never by reading the guide's text yourself). Each part is its own episode below.
c. Writer (Sonnet helper): its brief is prompts/writer.md with {GUIDE_TEXT} = /tmp/sqe1/src/<id>.txt,
   {OUT_PATH} = /tmp/sqe1/out/<id or part id>.txt, {TITLE_PREFIX} and {WORKSHOP} from the plan; then, for a whole
   workshop, "## This episode covers the whole workshop" with "Title: <prefix> · <2 to 4 word topic>. Write the script
   to the path given above."; for a part, prompts/part.md filled in ({N}, {OF}, {SECTIONS} as "- SECTION k: <heading>"
   lines, {OTHERS}, {TITLE_PREFIX}). Save the brief as /tmp/sqe1/brief-<id>.md and tell the helper to read and follow it.
d. Code check: `python3 tools/check_script.py /tmp/sqe1/out/<id>.txt /tmp/sqe1/src/<id>.txt`. On errors, the reviser once
   (Sonnet, prompts/reviser.md, errors in /tmp/sqe1/out/<id>.problems.txt), then check again. Still failing: hold.
e. Two accuracy checks side by side (two **Opus** helpers, started together):
   - prompts/checker.md ({GUIDE_TEXT}, {SCRIPT}, {OUT_PATH} = /tmp/sqe1/out/<id>.check.json);
   - prompts/linebyline.md ({GUIDE_TEXT}, {SCRIPT}, {OUT_PATH} = /tmp/sqe1/out/<id>.lines.md,
     {JSON_PATH} = /tmp/sqe1/out/<id>.lines.json).
   Both "pass": go to g.
f. One fixing round: `python3 tools/fixflow.py <id> /tmp/sqe1 /tmp/sqe1/src/<id>.txt`. It merges the two checks' fixes,
   applies them, runs the code check and writes /tmp/sqe1/verify-<id>.md. If it prints a CONFLICT, keep the fix closer to
   the source's own words. If it prints a SOURCE-ERROR report, the guide itself may be wrong: keep the episode true to
   the guide, and list the report for Zac (the guide is fixed in the app, never here). Then a fresh **Opus** helper
   follows /tmp/sqe1/verify-<id>.md (it checks only the changed lines). "pass" (and the code check OK): go to g. "fail":
   apply its fixes (`python3 tools/apply_fixes.py /tmp/sqe1/out/<id>.txt /tmp/sqe1/out/<id>.verify.json`), run the code
   check, and have one more fresh Opus helper check just those new lines the same way (a short CHANGES file for them,
   as fixflow writes); still failing: hold.
g. Pass: copy the script to `scripts/<id>.txt`, then
   `python3 tools/registry.py add-episode --unit <unitId> --id <id> --script scripts/<id>.txt --guide-hash <hash> --supersedes <old id, if the plan has one> --checks "code ok; opus pass x2 (fix round: yes/no)" --check-json /tmp/sqe1/out/<id>.check.json`.
h. Hold: copy the script to `scripts/held/<id>.txt`, then `python3 tools/registry.py add-episode ... --hold "<one-line reason>"`.
   Held episodes are never rendered. List them with reasons in the report.

## 5. Replays
For each entry in plan.json `replays`: `python3 tools/registry.py add-replay --episode <episodeId> --reason "<reason>" --id <id>`.

## 6. Publish
`git add scripts episodes reports && git commit -m "<date>: new episodes and replays" && git push origin HEAD`.
The push starts GitHub Actions, which makes the audio and updates the feeds (about 10 to 20 minutes per episode; pieces
are kept, and the half-hourly runs carry on if Google's allowance runs out). Check once that the run started.

## 7. Report and message
Write `reports/<yyyy-mm-dd>.md`: new episodes (title), replays (title and why), held episodes (title and why), skipped
counts by reason, helpers used, speech requests used today, anything odd, anything Zac should decide. Commit it with
step 6. Then message Zac only if something is new in his feeds or something needs him: one or two plain lines (which
episode, which feed, roughly when the audio is ready). No message on a day with nothing new.

## 8. Dry run
Stop after step 3. Report what the plan would do (new episodes, replays, skipped with reasons) and whether every step
worked. Write it to `reports/dry-run-<yyyy-mm-dd>.md` (titles, ids, counts and reasons only: no guide text), then
`git add reports/dry-run-*.md && git commit -m "Dry run report" && git push origin HEAD`. Commit nothing else.

## How a workshop reaches the podcast (for answering Zac)
1. Zac adds the workshop's Quizlet set in the app and confirms its workshop.
2. The app (only while it is open: it works every 10 minutes) builds the cards, and asks for the source checks the
   conversion waits for (library/cpoints), in its own priority order (a class this week or next first).
3. The nightly check (01:52) answers them first (up to about 120 points a night); "Check now" in the app can ask sooner.
4. The app (open again) converts the workshop to v3 and applies it by itself (no approval step since 21 Oct). It paces
   conversions from a weekly budget (about 2 a day by default; a class within 2 days goes whatever the limit; none on
   Saturdays or Friday afternoons).
5. The next 08:05 run here makes the episode; the audio follows in the cloud.
