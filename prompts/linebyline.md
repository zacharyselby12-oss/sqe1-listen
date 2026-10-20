# One-off line-by-line check of a pilot episode (for a fresh Opus helper)

Read the SOURCE {GUIDE_TEXT} and the SCRIPT {SCRIPT}. For EVERY spoken line, in order, write one row:
number | speaker | first 8 words | verdict (OK or PROBLEM) | the source text that supports it (or why it fails).
Check each legal statement, joke, question, wrong-but-corrected answer and the recap against the source. Then check
the whole thing against the law of England and Wales as at 11 September 2026: note anything the source states that
you are confident is wrong (SOURCE-ERROR). Finish with a JSON line:
{"lines": N, "problems": M, "source_errors": K, "verdict": "pass" or "fail"}
Save the table to {OUT_PATH}. Read nothing else.
