"""Neutral participant-facing descriptions for the two Pilot 1 fuzzing tasks.

Do not expose task condition names, vulnerability locations, or assessments of
harness effectiveness in these descriptions. Internal task codes remain in
session and task records for attribution.
"""

from html import escape

PROGRAM_OVERVIEWS = {
    "dense_v2": (
        "The provided C program handles framed messages. It checks message "
        "headers and routes different message kinds to handlers for status, "
        "queries, updates, and archives. Some handlers also process records "
        "inside message payloads."
    ),
    "lowyield_v1": (
        "The provided C program handles binary protocol messages. It checks "
        "frame fields and routes status, data, and administrative messages "
        "to different handlers. Some handlers also process records "
        "inside message payloads."
    ),
}


def pilot1_task_description(task_code, position):
    """Return study-neutral HTML for an assigned task; reject unknown metadata."""
    if task_code not in PROGRAM_OVERVIEWS or type(position) is not int or position not in (1, 2):
        raise ValueError("Invalid Pilot 1 task metadata")

    overview = escape(PROGRAM_OVERVIEWS[task_code])
    return (
        f"<h2>Task {position} — Fuzzing Investigation</h2>"
        "<p><strong>Program overview:</strong> " + overview + "</p>"
        "<p><strong>Your goal:</strong> Investigate the program with "
        "coverage-guided fuzzing. Explore its source, run or adapt available "
        "harnesses, and examine feedback from your experiments. You are not "
        "required to find a crash.</p>"
        "<p><strong>Three harnesses are available:</strong> "
        "<code>fuzz_a</code>, <code>fuzz_b</code>, and <code>fuzz_c</code>. "
        "Each is built from the corresponding file under "
        "<code>harnesses/</code> and passes inputs to the program through "
        "a particular entry point. Open <code>harness_a.c</code>, "
        "<code>harness_b.c</code>, and <code>harness_c.c</code> to see "
        "how each one supplies or transforms input. You may choose or modify "
        "a harness; these are not ranked or recommended.</p>"
        "<p><strong>Input corpus:</strong> A corpus is a directory of saved "
        "test inputs. A fuzzer can reuse those inputs as seeds and mutate "
        "them in later runs. Keep each harness's corpus in a separate "
        "directory, for example <code>../runs/corpus-a</code>. "
        "Reusing the same directory preserves inputs between campaigns.</p>"
        "<p><strong>Getting started:</strong> In the CLI, open the working "
        "directory, inspect <code>Makefile</code>, <code>harnesses/</code>, "
        "<code>src/</code>, and <code>include/</code>, then build the "
        "harnesses. Use the Fuzzing Guide for copyable example commands "
        "and how to start, stop, or continue a campaign. Look at the "
        "terminal output for execution counts, coverage feedback, and "
        "errors. You may use the internal Firefox browser for research "
        "or AI assistance.</p>"
        "<p><strong>Working directory:</strong> "
        "<code>/home/user/fuzz-study/work</code></p>"
    )
