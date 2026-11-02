#!/usr/bin/env python3
"""In-place R2D.2 local participant activation. No session/container recreation.

Build: docker build --build-arg REACT_APP_NERDS_CLIPBOARD_INGEST=1
       --build-arg REACT_APP_NERDS_CLIPBOARD_TEXT=1
       --build-arg REACT_APP_NERDS_SPLIT_WORKSPACE=1
       -t devob_instance:r2d2-split -f instance/Dockerfile ./instance

Usage: python3 scripts/r2d2_live.py apply|rollback|status
The R2D.1 sidebar footer and R2C clipboard collection are retained.
"""
import argparse
import json
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

LIVE = "nerds-pilot1-browser-r1-test"
IMAGE = "devob_instance:r2d2-split"
PREFIX = "/home/user/.r2d2-split"
API = "/home/user/instance-api.py"
HELPER = "/home/user/workspace_layout.py"
WWW = "/home/user/www"
RUN = "/home/user/services/api/run"
NOVNC = "/home/user/services/novnc"


def call(*argv, output=False):
    p = subprocess.run(argv, check=True, text=True,
                       stdout=subprocess.PIPE if output else None)
    return p.stdout.strip() if output else None


def sh(script, output=False):
    return call("docker", "exec", LIVE, "sh", "-ec", script, output=output)


def read_file(path):
    return call("docker", "exec", LIVE, "cat", path, output=True)


def ensure_running():
    assert call("docker", "inspect", "-f", "{{.State.Running}}", LIVE, output=True) == "true"
    sh(f"test -f {API} && test -d {WWW} && test -f {RUN}")
    sh("test -f /home/user/pilot1_task_descriptions.py")
    sh("command -v wmctrl >/dev/null")


def bundle_name(root):
    html = (root / "index.html").read_text()
    m = re.search(r"static/js/main\.[a-zA-Z0-9_-]+\.js", html)
    if not m:
        raise RuntimeError("React staging index has no bundle")
    js = (root / m.group()).read_text()
    checks = [
        "Split view", "Resize CLI and Firefox panes",
        "Clipboard privacy and study recording",
        "Skipping saves your work and ends this task.",
    ]
    for val in checks:
        if val not in js:
            raise RuntimeError("Staged React missing: " + val)
    if "Current assignment:" in js:
        raise RuntimeError("Redundant sidebar text returned in build")
    return m.group()


def stage():
    with tempfile.TemporaryDirectory(prefix="nerds-r2d2-") as tmp:
        local = Path(tmp)
        (local / "www").mkdir()
        created = call("docker", "create", "--network", "none",
                       "--entrypoint", "/bin/true", IMAGE, output=True)
        try:
            for src, dest in [
                ("/home/user/www/.", local / "www"),
                (API, local / "instance-api.py"),
                (HELPER, local / "workspace_layout.py"),
            ]:
                call("docker", "cp", f"{created}:{src}", str(dest))
        finally:
            call("docker", "rm", created)
        bundle = bundle_name(local / "www")
        api = (local / "instance-api.py").read_text()
        helper = (local / "workspace_layout.py").read_text()
        if "/api/workspace/layout" not in api or "def set_layout" not in helper:
            raise RuntimeError("Staged API or helper is incomplete")
        old_run = read_file(RUN)
        if "PILOT1_CLIPBOARD_TEXT_ENABLED=1" not in old_run or (
            "PILOT1_CLIPBOARD_INGEST_ENABLED=1" not in old_run
        ):
            raise RuntimeError("Expected R2C clipboard flags missing in current API run script")
        if not old_run.startswith("#!"):
            raise RuntimeError("Unrecognized API run script")

        new_run = old_run.split("\n", 1)
        new_run = (new_run[0] + "\n"
                   + "export PILOT1_SPLIT_WORKSPACE_ENABLED=1\n"
                   + (new_run[1] if len(new_run) > 1 else ""))
        (local / "api-run").write_text(new_run)
        for src, dest in [
            (local / "www", PREFIX + "-next-www"),
            (local / "instance-api.py", PREFIX + "-next-api.py"),
            (local / "workspace_layout.py", PREFIX + "-next-layout.py"),
            (local / "api-run", PREFIX + "-next-run"),
        ]:
            call("docker", "cp", str(src), f"{LIVE}:{dest}")
        return bundle


def restore():
    # Existing pre-split files are moved back; never delete participant data.
    sh(f"""
        if [ -d {PREFIX}-old-www ]; then
          if [ -d {WWW} ]; then mv {WWW} {PREFIX}-failed-www; fi
          mv {PREFIX}-old-www {WWW}
        fi
        if [ -f {PREFIX}-old-api.py ]; then
          if [ -f {API} ]; then mv {API} {PREFIX}-failed-api.py; fi
          mv {PREFIX}-old-api.py {API}
        fi
        if [ -f {PREFIX}-old-run ]; then
          if [ -f {RUN} ]; then mv {RUN} {PREFIX}-failed-run; fi
          mv {PREFIX}-old-run {RUN}
          chmod 755 {RUN}
        fi
        if [ -f {HELPER} ]; then mv {HELPER} {PREFIX}-failed-layout.py; fi
        sv restart /home/user/services/api
        sv restart {NOVNC}
    """)


def http_get(path):
    code = (
        "import urllib.request;"
        "r=urllib.request.urlopen("
        f"'http://127.0.0.1:60000{path}', timeout=10);"
        "print(r.status);print(r.read().decode())"
    )
    return call("docker", "exec", LIVE, "python3", "-c", code, output=True)


def verify_split():
    # Test the actual participant desktop, not just the API route. A fullscreen
    # window manager may silently ignore geometry requests.
    probe = (
        "import urllib.request,json;"
        "body=json.dumps({'mode':'split','cli_percent':50}).encode();"
        "req=urllib.request.Request('http://127.0.0.1:60000/api/workspace/layout',"
        "data=body,headers={'Content-Type':'application/json'},method='POST');"
        "res=urllib.request.urlopen(req,timeout=15);"
        "data=json.load(res);"
        "assert data.get('mode')=='split' and data.get('focus')=='cli',data;"
        "print('SPLIT_OK',data.get('windows'))"
    )
    return call("docker", "exec", LIVE, "python3", "-c", probe, output=True)


def served_bundle():
    code = (
        "import urllib.request,re;"
        "html=urllib.request.urlopen('http://127.0.0.1:8888/',"
        "timeout=10).read().decode();"
        "match=re.search(r'static/js/main\\.[a-zA-Z0-9_-]+\\.js',html);"
        "print(match.group(0) if match else 'MISSING')"
    )
    return call("docker", "exec", LIVE, "python3", "-c", code, output=True)


def apply():
    ensure_running()
    sh(f"""test ! -e {PREFIX}-old-www &&
             test ! -e {PREFIX}-old-api.py &&
             test ! -e {PREFIX}-old-run &&
             test ! -e {PREFIX}-next-www &&
             test ! -e {HELPER}""")
    call("docker", "image", "inspect", IMAGE, output=True)
    expected = stage()
    try:
        sh(f"""
            test -d {PREFIX}-next-www
            test -f {PREFIX}-next-api.py
            test -f {PREFIX}-next-layout.py
            test -f {PREFIX}-next-run
            mv {WWW} {PREFIX}-old-www
            mv {API} {PREFIX}-old-api.py
            mv {RUN} {PREFIX}-old-run
            mv {PREFIX}-next-www {WWW}
            mv {PREFIX}-next-api.py {API}
            mv {PREFIX}-next-layout.py {HELPER}
            mv {PREFIX}-next-run {RUN}
            chmod 755 {RUN}
            sv restart /home/user/services/api
            sv restart {NOVNC}
        """)
        focus_response = http_get("/api/workspace/focus")
        if not focus_response.startswith("200\n"):
            raise RuntimeError("Focus endpoint not serving")
        actual = served_bundle()
        if actual != expected:
            raise RuntimeError(f"noVNC served {actual}, expected {expected}")
        print(verify_split())
        print("PASS: R2D.2 split UI and focus-aware API activated")
        print("PASS: noVNC serves", actual)
        print("Focus endpoint:", focus_response.replace("\n", " "))
        print("Existing participant, Task 2 and recorded data preserved")
        print("Refresh participant Edge tab (Ctrl+Shift+R); test Split view.")
        print("Rollback: python3 scripts/r2d2_live.py rollback")
    except Exception:
        print("Activation unverified; restoring prior R2D.1 assets and API.")
        restore()
        raise


def rollback():
    ensure_running()
    has_backup = sh(
        f"test -d {PREFIX}-old-www && test -f {PREFIX}-old-run && "
        f"test -f {PREFIX}-old-api.py && echo yes || echo no",
        output=True)
    if has_backup != "yes":
        failed = sh(
            f"test -d {PREFIX}-failed-www && "
            f"test -f {PREFIX}-failed-run && echo yes || echo no",
            output=True)
        if failed == "yes":
            print("ALREADY RESTORED: Automatic activation rollback returned "
                  "the original R2D.1 frontend and API.")
            print("No changes made. Existing task and data retained.")
            return
        raise RuntimeError("R2D.2 backup not found; no changes made")
    # Return the native desktop to the original CLI-first single-window view.
    # Ignore failure: rollback must work even if the split backend is broken.
    script = (
        "import urllib.request,json;"
        "body=json.dumps({'mode':'cli','cli_percent':50}).encode();"
        "req=urllib.request.Request('http://127.0.0.1:60000/api/workspace/layout',"
        "data=body,headers={'Content-Type':'application/json'});"
        "urllib.request.urlopen(req,timeout=5)"
    )
    subprocess.run(["docker", "exec", LIVE, "python3", "-c", script],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    restore()
    print("PASS: R2D.1 frontend and API restored; task/data unchanged.")
    print("Browser hard-refresh recommended.")


def status():
    ensure_running()
    print("Participant running:", LIVE)
    print("Current frontend bundle:", served_bundle())
    print("API service:", sh("sv status /home/user/services/api", output=True))
    print("noVNC service:", sh(f"sv status {NOVNC}", output=True))
    print("Pre-split backup:",
          sh(f"test -d {PREFIX}-old-www && echo PRESENT || echo NOT_FOUND", output=True))
    print("API run:", read_file(RUN).strip())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["apply", "rollback", "status"])
    args = parser.parse_args()
    try:
        {"apply": apply, "rollback": rollback, "status": status}[args.action]()
    except (RuntimeError, AssertionError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"STOP: {exc}\n")
