# Accuracy check (for a fresh Opus helper)

You check ONE episode script of "SQE1 Listen" for accuracy against its source. A program has already checked figures
and names; you are the only reader who checks meaning.

Read: the SOURCE {GUIDE_TEXT} and the SCRIPT {SCRIPT}. Read nothing else. Do not look anything up.

Go through EVERY spoken line, jokes and banter included. For each legal statement made (as fact, as an answer, as a
punchline), is it supported by the SOURCE, exactly? A wrong answer from Hannah is fine only if Will corrects it in
the next lines and the correction is supported by the source.

Flag a problem when you find:
- CONTRADICTION: conflicts with the source.
- BEYOND: a legal statement not in the source (an added rule, exception, consequence, "usually" or "generally"),
  including inside jokes and inside the outcome of an invented scenario.
- DISTORTION: stronger, weaker, broader or narrower than the source; a dropped condition ("only if", "unless", a time
  limit, who must do what); a punchline that blurs the rule or could leave a listener with the wrong rule.
- SCENARIO: an invented scenario whose answer is not what the source's rule gives, that lacks a fact needed to reach
  the answer, or contains a fact that would change it.
- NUMBERS: a figure attached to the wrong rule.
- RECAP: the header recap and the spoken recap disagree, or a recap line is inaccurate.
- HEDGE: a legal rule or figure stated with "I think", "kind of", "sort of", "roughly" or similar and not then
  stated exactly; a wrong guess left uncorrected; a rule left half-said by an interruption.
- OMISSION: anything the episode must cover but does not: a TEST element of any section (or whether all elements are
  needed or any one is enough), a starred detail, an exception, condition, limit, time limit or "unless" attached to
  a rule the episode states, a TRAP, a LOOK-ALIKE, a NUMBER, or a "what the exam question turns on" item. List every
  one. For an omission, "line" is the exact spoken line after which it should go, and "fix" starts with "ADD: "
  followed by the new line or lines in the script format.
- SOURCE-ERROR: a statement that agrees with the source but that you are confident is wrong law of England and Wales
  as at 11 September 2026. Report it; do not "fix" it.
Be strict, but invent no problems: a paraphrase that keeps the meaning is fine.
Also note (this does not fail the episode): BANTER, the number of lines that teach nothing if more than about 1 in 10
(quick reactions that keep the conversation moving, such as "Right.", "Hang on." or "Ha, fair.", do not count, and nor
does casual wording of a rule that stays exactly the source's: judge the rule underneath, not the register).

Reply with JSON only:
{"verdict": "pass" or "fail",
 "problems": [{"type": "...", "line": "<the exact spoken line>", "source": "<the exact source text, or 'none'>",
               "why": "<one sentence>", "fix": "<a replacement line, or 'delete'>"}],
 "coverage": [], "banter_lines": 0}
("coverage" stays an empty list: omissions now go in "problems" as OMISSION.)
"pass" only if "problems" is empty.
