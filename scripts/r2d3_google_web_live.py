#!/usr/bin/env python3
"""R2D.3 local Pilot 1: stage a Google Web-only policy and source-built addon.

This script deliberately does not restart Firefox. It leaves the participant
container, VNC, task, CLI, open tabs, and database unchanged. Changes become
active after Firefox is gracefully restarted (not after a NERDs page refresh).

Usage: python3 scripts/r2d3_google_web_live.py apply|rollback|status
"""
import argparse
import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
XPI = "/opt/chatgpt-prompt-logger.xpi"
POLICY = "/usr/lib/firefox-esr/distribution/policies.json"
MARKER = ".r2d3-google-web"
SRC_NAMES = [
    "manifest.json", "background.js", "browser-events.js",
    "content.js", "google-web-only.js", "google-web-ux.js",
]


def call(*args, output=False):
    result = subprocess.run(args, check=True, text=True,
                            stdout=subprocess.PIPE if output else None)
    return result.stdout.strip() if output else None


def sh(command, output=False):
    return call("docker", "exec", "-u", "root", LIVE,
                "sh", "-ec", command, output=output)


def working_checkout():
    root = Path(__file__).resolve().parents[1] / "instance"
    extension = root / "firefox-extension/chatgpt-prompt-logger"
    policy_path = root / "firefox-policies/policies.json"
    policy = json.loads(policy_path.read_text())
    manifest = json.loads((extension / "manifest.json").read_text())
    if manifest.get("version") != "0.9.0":
        raise RuntimeError("Checkout is missing the R2D.3 Firefox extension")
    if manifest.get("background", {}).get("scripts", [])[-1] != "google-web-only.js":
        raise RuntimeError("Google request guard missing from extension")
    if not any("google-web-ux.js" in item.get("js", []) for item in manifest["content_scripts"]):
        raise RuntimeError("Google UI filter missing from extension")
    if policy.get("policies", {}).get("SearchEngines", {}).get("Default") != "NERDs Google Web":
        raise RuntimeError("Google Web-only managed search policy missing")
    for name in SRC_NAMES:
        if not (extension / name).is_file():
            raise RuntimeError("Missing Firefox addon source: " + name)
    return extension, policy_path


def apply():
    if call("docker", "inspect", "-f", "{{.State.Running}}", LIVE, output=True) != "true":
        raise RuntimeError("Participant is not running")
    source, policy = working_checkout()
    sh("test -f " + XPI + " && test -f " + POLICY)
    sh("test ! -e " + XPI + MARKER + "-before && "
       "test ! -e " + POLICY + MARKER + "-before")
    with tempfile.TemporaryDirectory(prefix="nerds-r2d3-google-") as directory:
        archive = Path(directory) / "nerds-google-web.xpi"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in SRC_NAMES:
                z.write(source / name, arcname=name)
        with zipfile.ZipFile(archive) as z:
            assert sorted(z.namelist()) == sorted(SRC_NAMES)
        call("docker", "cp", str(archive), LIVE + ":" + XPI + MARKER + "-next")
        call("docker", "cp", str(policy), LIVE + ":" + POLICY + MARKER + "-next")
    try:
        sh("cp -p " + XPI + " " + XPI + MARKER + "-before && "
           "cp -p " + POLICY + " " + POLICY + MARKER + "-before && "
           "mv " + XPI + MARKER + "-next " + XPI + " && "
           "mv " + POLICY + MARKER + "-next " + POLICY + " && "
           "chmod 0644 " + XPI + " " + POLICY)
    except Exception:
        sh("if [ -f " + XPI + MARKER + "-before ]; then "
           "cp -p " + XPI + MARKER + "-before " + XPI + "; fi; "
           "if [ -f " + POLICY + MARKER + "-before ]; then "
           "cp -p " + POLICY + MARKER + "-before " + POLICY + "; fi")
        raise
    print("PASS: Google Web-only Firefox policy and addon v0.9.0 staged.")
    print("PASS: No participant task, Firefox process, CLI, VNC, or DB changes.")
    print("PENDING: Gracefully restart INTERNAL Firefox to activate new policy/addon.")
    print("After restart, inspect about:policies and about:addons; then test Google Search.")
    print("Rollback: python3 scripts/r2d3_google_web_live.py rollback")


def rollback():
    state = sh(
        "test -f " + XPI + MARKER + "-before && "
        "test -f " + POLICY + MARKER + "-before && echo yes || echo no",
        output=True
    )
    if state != "yes":
        print("No active R2D.3 policy/addon backup; nothing changed.")
        return
    sh("mv " + XPI + MARKER + "-before " + XPI + " && "
       "mv " + POLICY + MARKER + "-before " + POLICY + " && "
       "chmod 0644 " + XPI + " " + POLICY)
    print("PASS: Prior Firefox policy and extension restored.")
    print("A graceful Firefox restart is required to activate the restoration.")


def status():
    script = (
        "import json,zipfile;"
        "m=json.load(zipfile.ZipFile('" + XPI + "').open('manifest.json'));"
        "p=json.load(open('" + POLICY + "'));"
        "print('Installed addon version:',m.get('version'));"
        "print('Managed default search:',p.get('policies',{}).get('SearchEngines',{}).get('Default'))"
    )
    call("docker", "exec", LIVE, "python3", "-c", script)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["apply", "rollback", "status"])
    args = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback, "status": status}[args.action]()
    except (OSError, subprocess.CalledProcessError, RuntimeError, AssertionError) as e:
        parser.exit(1, "STOP: " + str(e) + "\n")
