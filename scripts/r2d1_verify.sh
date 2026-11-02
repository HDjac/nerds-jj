#!/usr/bin/env bash
# Run source-level Release 2D.1 checks without touching a running participant.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m unittest discover -s instance -p 'test_pilot1_task_descriptions.py' -v
python3 -m py_compile instance/pilot1_task_descriptions.py instance/instance-api.py
python3 -m json.tool instance/app/src/data/fuzzingGuideData.json >/dev/null

python3 - <<'PY'
from pathlib import Path
import json

api = Path("instance/instance-api.py").read_text()
react = Path("instance/app/src/components/PilotTaskController.jsx").read_text()
docker = Path("instance/Dockerfile").read_text()
guide = json.loads(Path("instance/app/src/data/fuzzingGuideData.json").read_text())

checks = {
    "api serves neutral descriptions": "pilot1_task_description(task_code, position)" in api,
    "api uses Task N titles": '"title": f"Task {position}"' in api,
    "old condition headings absent": "<h2>Dense v2" not in api and "<h2>Low-Yield" not in api,
    "React sidebar avoids condition labels": "TASK_NAMES" not in react and "Current assignment:" in react,
    "React retains code-based validation": "TASK_CODES.has(active.task_code)" in react,
    "new module is installed into Docker image": "COPY --chown=user:user ./pilot1_task_descriptions.py ." in docker,
    "guide shows the three harnesses": any(
        item["heading"] == "Understand and choose a harness" and
        len(item["steps"]) == 3
        for item in guide["sections"]
    ),
}
for name, ok in checks.items():
    print(("PASS" if ok else "FAIL") + ": " + name)
if not all(checks.values()):
    raise SystemExit(1)
PY

echo 'PASS: R2D.1 source checks. Browser rendering and live-session acceptance remain pending.'
