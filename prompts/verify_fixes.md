# Verify the fixes made to one episode script (for a fresh Opus helper)

Two Opus checks found problems in a script of "SQE1 Listen" and their fixes have been applied. You check ONLY the
changed lines. Read the SOURCE {GUIDE_TEXT} and the CHANGES file {CHANGES}. Read nothing else; look nothing up.

Each entry in CHANGES gives the problem that was found, the line before, the old line (or "(new)"), the new line(s),
and the line after. For each new line:
- is every legal statement in it supported exactly by the SOURCE (no added rule, exception or consequence; no dropped
  condition, "only if", "unless" or time limit; not stronger, weaker, broader or narrower)?
- does it actually fix the stated problem?
- does it fit where it sits (the conversation still makes sense with the lines before and after; no rule now said
  twice in a row; no wrong answer left uncorrected)?

Write JSON only, to {OUT_PATH}:
{"verdict": "pass" or "fail",
 "problems": [{"type": "FIX", "line": "<the exact new line, character for character>", "source": "<exact source
               text, or 'none'>", "why": "<one sentence>", "fix": "<a replacement line in the script format, or
               'delete'>"}]}
"pass" only if "problems" is empty. Then reply with one line: the verdict and the number of problems.
