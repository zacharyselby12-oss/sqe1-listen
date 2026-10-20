# Reviser (for a fresh Sonnet helper; the one fix allowed per episode)

An episode script of "SQE1 Listen" failed a check. Fix ONLY what the problems list names, changing as few lines as
possible, and keep the format, the three sections and the voice. For an OMISSION, add what is missing in natural
dialogue where it belongs (the problem says after which line); the episode may get longer, never padded.

Read: the EPISODE SOURCE {GUIDE_TEXT}, the SCRIPT {SCRIPT} and the PROBLEMS {PROBLEMS} (a text or JSON file).
Rules are the same as in prompts/writer.md: every legal statement must come from the source alone; no years or
citations; list new invented names and figures under `invented:`; the header recap must match the spoken recap.
Write the corrected script to {SCRIPT} (overwrite), then run:
python tools/check_script.py {SCRIPT} {GUIDE_TEXT}
and fix every ERROR. Reply with the single word: done
