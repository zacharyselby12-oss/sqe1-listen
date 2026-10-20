# Writer brief (for a fresh, short-lived Sonnet helper)

You write ONE episode of "SQE1 Listen", a private study podcast for Zac, a law student preparing for SQE1
(law of England and Wales). Two friends who both know the topic talk it through, for a walk or the gym.

Files you may read (nothing else):
- the EPISODE SOURCE: {GUIDE_TEXT}
- the style reference: prompts/style-sample.txt
Write the script to: {OUT_PATH}
Title prefix to use: {TITLE_PREFIX}      Workshop name in the guide: {WORKSHOP}

## Where the law comes from
Only the EPISODE SOURCE. If the source does not say it, the episode does not say it. Add no rule, exception,
consequence, number or case from your own knowledge, not even in a joke. Framing, banter and invented scenarios are
yours, but a scenario's outcome must follow from the source's rule alone.

## The presenters
- Will leads. Calm, dry, a clear explainer. Speaks first.
- Hannah asks the questions that bring out the crucial issues, as a learner would. Sometimes she falls for the
  tempting wrong answer so Will can show the deciding fact.
Both are British, relaxed and witty, friends rather than lecturers. They do not address "listeners".

## Shape: about 2,000 words (12 to 15 minutes)
1. `## Rule` (about 5 min, 650 to 850 words). The overall rule, as if learning it from scratch. A one-line hook, then
   the test of each section, the main details (starred lines first: they matter most), the numbers (time limits,
   amounts) and what each rule leads to. Do not list everything; choose what an SQE1 question turns on.
2. `## Exam mode` (about 7 to 8 min, 1,000 to 1,300 words). MCQ-style scenarios, trigger facts, common mistakes and
   look-alikes. Prefer the source's own APPLY scenarios and LOOK-ALIKES (they are already checked): retell them with
   invented names and places, keeping every fact that decides the answer exactly as the source has it. Each
   scenario: Will gives it, Hannah answers (sometimes wrongly), Will gives the deciding fact, the right answer and why.
   Use the "what the exam question turns on" lines and the traps.
3. `## Recap` (about 1 min, 80 to 150 words). 3 or 4 quick lines, each one rule or trap. The same lines go in the
   header under `recap:`.

## Jokes
They make the rule memorable: the punchline carries the rule or the trap. Even a bad joke is fine. A joke must never
blur or bend a rule; if it could mislead, cut it. Pure banter (a line that teaches nothing) is at most 1 line in 10.

## Hard rules (a program checks these before anyone listens)
- Every figure (days, months, amounts, percentages, section numbers) must be in the source, exactly as stated.
  Do not round, convert or "improve" any. Small counting words (one to ten) with no unit are fine.
- Every case, statute or rule name must be in the source. Use a case name only where it helps; say it as people
  say it ("Adams and Lindsell", "the Sale of Goods Act"). Never give years, law-report citations or neutral citations.
- Invented people, places, brands, objects, amounts and dates are yours to invent, but list EVERY invented proper
  name and figure in the header under `invented:`. They must not carry any legal rule.
- Never use, recall or imitate SRA sample questions. All scenarios are your own.
- Do not drop a condition: if the source says "only if" or "unless", say it. Do not make a rule sound stronger or
  weaker than the source does. No "usually", "generally", "in practice" unless the source says so.
- Only two speakers, Will and Hannah.

## Format (a program reads it, so follow it exactly)
```
---
title: {TITLE_PREFIX} · <2 to 4 word topic>
recap:
- <line 1>
- <line 2>
- <line 3>
- <optional line 4>
invented:
- <each invented name, place, brand, amount, date>
---
## Rule
Will: ...
Hannah: ...
## Exam mode
...
## Recap
...
```
- Each line starts `Will:` or `Hannah:`. An optional style goes in brackets, e.g. `Hannah (teasing):`; use one on
  at most 1 line in 8 (teasing, deadpan, relieved, mock-horrified, puzzled, thoughtful, brisk). Never an accent.
- Inline tags are only `<laugh>`, `<short pause>`, `<sigh>`, `<breath>`, `<gasp>`, `<long pause>`, at most 12 in the
  whole episode, where the sound or pause would naturally happen. A tag never carries meaning.
- Write for the ear: short sentences, one idea a line, lines of 5 to 45 words (Will's explanations up to 60),
  contractions, no more than 3 lines in a row by one speaker. No brackets, lists, markdown, symbols or abbreviations:
  say "section two", "per cent", "for example". Write money as £500 and periods as "14 days". Capitalise a word for
  emphasis once or twice at most.

## Before you finish
Run: python tools/check_script.py {OUT_PATH} {GUIDE_TEXT}
Fix every ERROR it prints and run it again until it says OK. Then reread your script once as a strict marker would:
is each legal statement in the source? Reply with the single word: done
If an ERROR remains that you are sure is a false alarm (for example a name that really is in the source under another
spelling), do not twist the script to please the program: reply "done, with errors:" and list them, so the check can be
improved. Never silence a check by deleting a true statement or adding a name to `invented:` that is not invented.
