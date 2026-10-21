# Line-by-line check of an episode (for a fresh Opus helper)

Read the SOURCE {GUIDE_TEXT} and the SCRIPT {SCRIPT}. For EVERY spoken line, in order, write one row:
number | speaker | first 8 words | verdict (OK or PROBLEM) | the source text that supports it (or why it fails).
Check each legal statement, joke, question, wrong-but-corrected answer and the recap against the source. A hedged
rule ("I think", "kind of"), a wrong guess left uncorrected, or a rule left half-said is a PROBLEM.
Then a COVERAGE table: for every TEST element of every section, every starred detail, every exception or condition
attached to a rule the script states, every TRAP, LOOK-ALIKE, NUMBER and "what the exam question turns on" item in
the source, one row: item (first 10 words) | covered at line number(s) | or MISSING. Each MISSING item is a problem.
Then check the whole thing against the law of England and Wales as at 11 September 2026: note anything the source
states that you are confident is wrong (SOURCE-ERROR). Finish with a JSON line:
{"lines": N, "problems": M, "missing": X, "source_errors": K, "verdict": "pass" or "fail"}
"pass" only if problems and missing are both 0.
Save the table to {OUT_PATH}. Read nothing else.

This check runs at the same time as a separate accuracy check, so also write a JSON file to {JSON_PATH} in exactly
this format (valid JSON, nothing else in the file), with one entry for every PROBLEM row and every MISSING item:
{"verdict": "pass" or "fail",
 "problems": [{"type": "PROBLEM" or "OMISSION" or "SOURCE-ERROR", "line": "<the exact spoken line, copied character
               for character from the script>", "source": "<the exact source text, or 'none'>", "why": "<one sentence>",
               "fix": "<a replacement line in the script format (Name (mood): text), or 'delete', or for an omission
               'ADD: ' followed by the new line or lines in the script format>"}]}
For an omission, "line" is the exact spoken line after which the new line(s) should go. For a SOURCE-ERROR the fix is
'none' (report it; do not change the script). The script's header map: and summary: lines count as lines to check.
