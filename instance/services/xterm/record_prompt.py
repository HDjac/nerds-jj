#!/usr/bin/env python3
"""Best-effort capture of one completed interactive Bash history entry.

Runs inside the participant account, so records are NOT tamper-proof.
Never execute, evaluate, or print command text. One JSON object per line.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import sys

TAG_RE = re.compile(r"^20[0-9]{6}T[0-9]{6}Z-[0-9]+$")
MAX_INPUT = 128 * 1024


def main():
    tag = os.environ.get("NERDS_CLI_SESSION_TAG", "")
    if not TAG_RE.fullmatch(tag):
        return 1

    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        return 1
    parts = data.split(b"\x00")
    if len(parts) != 5 or parts[-1] != b"":
        return 1
    try:
        sequence = int(parts[0].decode("ascii"))
        shell_pid = int(parts[1].decode("ascii"))
        exit_status = int(parts[2].decode("ascii"))
        command = parts[3].decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return 1
    if not (1 <= sequence <= 2**31 and 1 <= shell_pid and 0 <= exit_status <= 255):
        return 1

    # Deliberately one history entry per prompt, not a guarantee of each process
    # or pipeline element. Logs may include sensitive command-line arguments.
    record = {
        "schema_version": 1,
        "event_type": "bash_command_completed",
        "capture_method": "bash_history_prompt_command",
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "terminal_session": tag,
        "sequence": sequence,
        "shell_pid": shell_pid,
        "command": command,
        "exit_status": exit_status,
    }

    path = Path.home() / ".nerds-cli-recordings"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        return 1
    output = path / f"{tag}.commands.jsonl"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(output), flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return 1
        row = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
        os.write(fd, row)
        os.fsync(fd)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError):
        # Never emit command text to stderr or disturb the terminal.
        sys.exit(1)
