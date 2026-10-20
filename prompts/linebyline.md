# One-off line-by-line check of a pilot episode (for a fresh Opus helper)

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
