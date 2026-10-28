#!/usr/bin/env python3
"""Guard for sessions that must never publish to this public repository.

The SQE1 pipeline (it works in /tmp/pipe) and the nightly check and weekly
verify (they create /tmp/sqe1-no-push first) have this repository attached
only so its allow rules for law websites apply. Guides, cards and app data
must never reach it. In those sessions this hook refuses:
  - any git commit, push, add, tag, merge, rebase, cherry-pick, stash or
    remote change, and any use of the gh tool;
  - any file write or edit inside the repository (including .claude/).
The publisher and the build chat don't create those markers, so they are
unaffected.
"""
import json
import os
import re
import sys

MARKERS = ("/tmp/pipe", "/tmp/sqe1-no-push")
GIT = re.compile(
    r"\bgit\b[^\n;|&]*?\b(commit|push|add|tag|merge|rebase|cherry-pick|am|stash|remote|"
    r"update-ref|write-tree|commit-tree|config)\b|\bgh\b\s|\bhub\b\s"
)


def main():
    if not any(os.path.exists(m) for m in MARKERS):
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}
    if tool == "Bash":
        cmd = inp.get("command", "")
        if GIT.search(cmd):
            print("Blocked: this run must never commit, push or change git settings "
                  "in the public podcast repository. Keep all work under /tmp.",
                  file=sys.stderr)
            return 2
        return 0
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(os.getcwd(), path))
        if full == root or full.startswith(root + os.sep):
            print("Blocked: this run must never write inside the public podcast "
                  "repository. Write under /tmp instead.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
