import os.path
import logging
import os
import json
import re
from browser_extension_origin import active_nerds_extension_origin
import tempfile
import urllib.request as url_request
from flask import Flask, request, redirect, make_response, jsonify, abort
from subprocess import run, PIPE, STDOUT, CalledProcessError, TimeoutExpired
from datetime import datetime


import config as CONFIG
from firefox import get_firefox_history

app = Flask(__name__)

@app.route("/api/workspace/activate", methods=["POST"])
def activate_workspace():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request"}), 400

    target = data.get("target")

    if target not in ("cli", "browser"):
        return jsonify({"error": "Invalid workspace"}), 400

    env = os.environ.copy()
    env["DISPLAY"] = ":1"
    env["XAUTHORITY"] = "/home/user/.Xauthority"

    try:
        result = run(
            ["wmctrl", "-lx"],
            stdout=PIPE,
            stderr=PIPE,
            text=True,
            env=env,
            timeout=5,
            check=True
        )

        window_id = None

        for line in result.stdout.splitlines():
            parts = line.split(None, 4)

            if len(parts) < 3:
                continue

            current_id = parts[0]
            window_class = parts[2].lower()

            if target == "cli" and window_class == "xterm.xterm":
                window_id = current_id
                break

            if target == "browser" and window_class.endswith(".firefox-esr"):
                window_id = current_id
                break

        if window_id is None:
            return jsonify({
                "error": f"{target} window not available"
            }), 503

        run(
            ["wmctrl", "-ia", window_id],
            stdout=PIPE,
            stderr=PIPE,
            env=env,
            timeout=5,
            check=True
        )

        return jsonify({
            "status": "success",
            "active": target
        })

    except (CalledProcessError, TimeoutExpired, OSError):
        app.logger.exception("Workspace activation failed")
        return jsonify({
            "error": "Unable to activate workspace"
        }), 500

def send_recv_data(data: dict, endpoint:str="/submit") -> bytes:
    """Send and receive data with authorization information"""
    #Ensure we have the correct data for this user
    if os.path.isfile(CONFIG.USER_DATA_FILE):
        with open(CONFIG.USER_DATA_FILE) as data_file:
            user_data = json.load(data_file)
            data["user_id"] = user_data["user_id"]
            data["token"] = user_data["token"]
    else:
        data["user_id"] = "notfound"
        data["token"] = "notfound"


    dataRaw = {}
    dataRaw['auth-token'] = CONFIG.SUBMIT_SECRET
    dataRaw['json-payload'] = json.dumps(data)
    encoded_body = json.dumps(dataRaw).encode('utf-8')
    req = url_request.Request(CONFIG.DB_URL + endpoint, data=encoded_body, headers={"Content-Type": "application/json"})
    res = url_request.urlopen(req)
    return res.read()

@app.route("/")
def setup():
    # Pilot 1 uses PostgreSQL-backed sessions and
    # Nginx authorization instead of legacy URL tokens.
    if getattr(CONFIG, "PILOT1_MODE", False):
        return redirect("nb/")

    # Legacy
    user_id = request.args.get('userId')
    token = request.args.get('token')

    if (user_id is not None) and (token is not None):
        user_data = {"user_id": user_id, "token": token}

        if not os.path.isfile(CONFIG.USER_DATA_FILE):
            with open(CONFIG.USER_DATA_FILE, "w") as f:
                #writing the data allows us to retrieve it anytime, if the user has cookies disabled for example.
                json.dump(user_data, f)

        task_file = os.path.join(CONFIG.TASKFILES_BASE_PATH, "tasks.json")
        if not os.path.isfile(task_file):
            req = url_request.Request(f"{CONFIG.DB_URL}/get_ipynb/{user_id}/{token}")
            res = url_request.urlopen(req)
            with open(task_file, "wb") as f:
                f.write(res.read())

        response = make_response(redirect("nb/"))
        response.set_cookie('userId', user_id)
        response.set_cookie('token', token)
        return response
    else:
        abort(400)

# logging route for LLM prompts (ChatGPT, Claude, Gemini)
@app.route("/log-llm-prompt", methods=["POST", "OPTIONS"])
def log_llm_prompt():
    if request.method == "OPTIONS":
        response = make_response("", 204)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    try:
        data = request.get_json(force=True)

        # The instance network can't reach postgres directly, so route the
        # prompt through nginx to the submit service like every other
        # submission; send_recv_data fills in user_id and token.
        client_timestamp = data.get("timestamp")
        payload = {
            "type": "llm_prompt",
            "interaction_id": data.get("interaction_id"),
            # The extension supplies `service` and `model`; default sensibly
            # for older clients that only send the ChatGPT prompt fields.
            "service": data.get("service") or "chatgpt",
            "model": data.get("model") or "unknown",
            "prompt": data.get("prompt"),
            "url": data.get("url"),
            # Stored as character varying
            "client_timestamp": str(client_timestamp) if client_timestamp is not None else None,
        }
        if getattr(CONFIG, "PILOT1_MODE", False):
            # The private Nginx gateway authenticates container attribution.
            # Do not forward legacy user_id/token to the Pilot 1 database.
            pilot_payload = {
                "interaction_id": payload.get("interaction_id"),
                "service": payload["service"],
                "model": payload["model"],
                "prompt": payload["prompt"],
                "url": payload["url"],
                "client_timestamp": payload["client_timestamp"],
            }
            req = url_request.Request(
                CONFIG.DB_URL.rstrip("/") + "/pilot1/ai-prompt",
                data=json.dumps(pilot_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with url_request.urlopen(req, timeout=10) as upstream:
                if upstream.status != 200:
                    raise RuntimeError("AI ingestion not acknowledged")
        else:
            send_recv_data(payload)

        response = jsonify({"ok": True})
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response, 200

    except Exception as e:
        response = jsonify({"ok": False, "error": str(e)})
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response, 500

# CORS access is limited to Firefox extension pages and these two
# browser-observation endpoints; this is not an authentication boundary.
@app.after_request
def nerds_browser_extension_cors(response):
    if not getattr(CONFIG, "PILOT1_MODE", False):
        return response
    if request.path not in (
        "/api/pilot1/browser-context", "/log-browser-event"
    ):
        return response

    origin = request.headers.get("Origin", "")
    response.vary.add("Origin")
    trusted_origin = active_nerds_extension_origin()
    if trusted_origin is not None and origin == trusted_origin:
        response.headers["Access-Control-Allow-Origin"] = trusted_origin
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, OPTIONS" if request.path == "/api/pilot1/browser-context"
            else "POST, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "600"
    return response


# Browser observations are intentionally distinct from AI prompt transcripts.
# The trusted gateway must authenticate container identity and call the dedicated
# browser ingestion DB function; never reuse /pilot1/ai-prompt for this data.
@app.route("/api/pilot1/browser-context", methods=["GET"])
def pilot1_browser_context():
    if not getattr(CONFIG, "PILOT1_MODE", False):
        abort(404)
    try:
        import uuid
        with open("/opt/nerds/released-reference/active-task.json") as handle:
            meta = json.load(handle)
        task = str(uuid.UUID(str(meta["task_run_id"])))
        if meta.get("status") not in ("ready", "active"):
            raise ValueError("Task not released")
    except (KeyError, ValueError, OSError, TypeError):
        return jsonify({"error": "Active task unavailable"}), 503
    response = jsonify({"task_run_id": task})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/log-browser-event", methods=["POST"])
def pilot1_browser_event():
    if not getattr(CONFIG, "PILOT1_MODE", False):
        abort(404)
    from browser_observation import InvalidObservation, normalize_event
    try:
        with open("/opt/nerds/released-reference/active-task.json") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return jsonify({"error": "Task metadata unavailable"}), 503
    try:
        payload = normalize_event(request.get_json(silent=True), meta)
    except InvalidObservation as exc:
        status = 409 if str(exc) in ('Stale task context', 'Task not released') else 400
        return jsonify({"error": str(exc)}), status
    try:
        request_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        upstream = url_request.Request(
            CONFIG.DB_URL.rstrip("/") + "/pilot1/browser-event",
            data=request_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with url_request.urlopen(upstream, timeout=10) as result:
            if result.status != 200:
                raise RuntimeError("Browser observation not acknowledged")
    except url_request.HTTPError as exc:
        # 409 is a stale task on the backend; never reassign it to the next task.
        if exc.code == 409:
            return jsonify({"error": "Task changed before ingestion"}), 409
        app.logger.warning("Browser ingest HTTP error: %d", exc.code)
        return jsonify({"error": "Browser ingestion unavailable"}), 503
    except Exception:
        app.logger.exception("Browser observation ingestion unavailable")
        return jsonify({"error": "Browser ingestion unavailable"}), 503
    return jsonify({"ok": True}), 200


TESTING_DIR = "/home/user/testing"
COMPILE_TIMEOUT = 120  # seconds

# Flags verified against the frontend WasmRunner: the output is a single
# self-contained js file (wasm embedded) that runs in the browser via
# Function("m", `var Module = m; ${js}`)(module).
EMCC_FLAGS = [
    "-std=c11", "-Wall", "-Wextra",
    "-fsanitize=undefined", "-fsanitize-minimal-runtime",
    "-sSINGLE_FILE=1",
    "-sEXIT_RUNTIME=1",
    "-sSAFE_HEAP=1",
    "-sASSERTIONS=1",
    "-sENVIRONMENT=web",
    "-sINCOMING_MODULE_JS_API=print,printErr,onExit,onAbort",
]

@app.route("/api/compile", methods=["POST"])
def compile():
    req = request.get_json()
    taskno = int(req["taskno"])
    code = req.get("code", "")

    # The frontend shuffles the display order of tasks, so it identifies the
    # task by its stable task_no. Look up which test harness that task uses;
    # tasks with test_file None (the read/review task) are only compile-checked
    # and return no runnable js.
    definition = next((d for d in TASK_DEFINITIONS if d["task_no"] == taskno), None)
    if definition is None:
        return {"result": "error",
                "compiler_output": f"Unknown task number {taskno}",
                "taskno": taskno, "js": ""}
    test_file = definition["test_file"]

    # Build in a per-request temp dir so concurrent compiles can't clobber
    # each other's username.c.
    with tempfile.TemporaryDirectory(prefix="build-") as build_dir:
        src_file = os.path.join(build_dir, "username.c")
        with open(src_file, "w") as f:
            f.write(code)

        out_file = os.path.join(build_dir, "test_output.js")
        if test_file is None:
            cmd = ["emcc", "-I", TESTING_DIR, "-std=c11", "-Wall", "-Wextra",
                   "-fsyntax-only", src_file]
        else:
            cmd = ["emcc", "-I", TESTING_DIR,
                   src_file, os.path.join(TESTING_DIR, test_file),
                   "-o", out_file] + EMCC_FLAGS

        try:
            completed = run(cmd, stdout=PIPE, stderr=STDOUT, check=True,
                            cwd=build_dir, timeout=COMPILE_TIMEOUT)
            compiler_output = completed.stdout.decode()
            logging.debug("successfully compiled project")
        except CalledProcessError as cpe:
            logging.debug("Failed to compile project")
            return {"result": "error", "compiler_output": cpe.stdout.decode(),
                    "taskno": taskno, "js": ""}
        except TimeoutExpired:
            return {"result": "error", "compiler_output": "Compilation timed out",
                    "taskno": taskno, "js": ""}

        if test_file is None:
            return {"result": "success", "compiler_output": compiler_output,
                    "taskno": taskno, "js": ""}

        with open(out_file) as f:
            js = f.read()

    return {"result": "success", "compiler_output": compiler_output,
            "taskno": taskno, "js": js}

# CURRENTLY UNUSED IN FRONTEND CODE
@app.route("/api/resolution", methods=["POST"])
def change_resolution():
    json = request.get_json()
    width = int(json["width"])
    height = int(json["height"])
    # Bit of a bad solution here, we first set the mode of the display to be as
    # large as possible (1920x1200) then we clamp it by setting the framebuffer
    # size. This avoids having to add a new mode for every single user
    # resolution. If the resolution requested is greater than 1920x1200, then
    # it will be set to 1920x1200.

    # Also, sometimes the first command will fail but the second command will
    # work, so we only return 500 when both commands fail

    CMD1 = ["xrandr", "-d", ":1", "-s", "1920x1200"]
    CMD1_success = True
    try:
        completedCMD = run(" ".join(CMD1), shell=True, stdout=PIPE, stderr=STDOUT, check=True)
    except CalledProcessError as cpe:
        CMD1_success = False

    width = min([width, 1920])
    height = min([height, 1200])
    CMD2 = ["xrandr", "-d", ":1", "--fb", f"{width}x{height}"]
    CMD2_success = True
    try:
        completedCMD = run(" ".join(CMD2), shell=True, stdout=PIPE, stderr=STDOUT, check=True)
    except CalledProcessError as cpe:
        CMD2_success = False
        #res = {"result":"error", "output": cpe.stdout.decode()}
        #return res, 500

    if not CMD1_success or CMD2_success:
        return "", 500
    else:
        return "", 200


@app.route("/api/submit", methods=['POST'])
def send_notebook():
    '''
    This function sends the participant code to the landing server.
    It also verifies that the JSON data is less than 1 MB to avoid unnecessary traffic by malicious users who could let the JSON file grow.
    '''
    if request.method == 'POST' and request.json:
        # check json size
        # only send, if size is less than 1 MB
        if len(request.json) < 1*1024*1024:
            r = request.json
            hist = get_firefox_history()
            r["code"]["hist"] = hist
            send_recv_data(request.json)
            return "Data sent"
        abort(400)
    else:
        abort(400)

TASKS_DIR = "/home/user/tasks"

SPEC_HTML = """
<p><code>process_username</code> must:</p>
<ul>
<li>Accept a username provided by the caller.</li>
<li>Accept only alphanumeric usernames.</li>
<li>Reject usernames that are too long for the destination buffer.</li>
<li>Correctly handle arbitrary user input and behave securely for unexpected or invalid input.</li>
<li>Return 1 and store the username via the <code>username</code> out-parameter if it is accepted.</li>
<li>Return 0 if the username is rejected.</li>
</ul>
"""

RUN_TESTS_HTML = ("<p>Use the <em>Run</em> button to compile your code and "
                  "run it against the test suite.</p>")

# The three C coding tasks shown in the editor. The starting code for each is
# read from TASKS_DIR at request time so the snippets can be tweaked without
# touching this file.
TASK_DEFINITIONS = [
    {
        "task_no": 1,
        "file": "read.c",
        "test_file": None,
        "desc": "<h1>Review the code</h1>"
                "<p>The editor contains an existing implementation of "
                "<code>process_username</code>. Read it carefully and add "
                "inline comments (<code>//</code> or <code>/* */</code>) "
                "explaining what is wrong with the code. Do not change the "
                "code itself.</p>"
                "<p>This task has no test suite; the <em>Run</em> button only "
                "checks that the file still compiles.</p>" + SPEC_HTML,
    },
    {
        "task_no": 2,
        "file": "write.c",
        "test_file": "test_username.c",
        "desc": "<h1>Write the function</h1>"
                "<p>Implement <code>process_username</code> from scratch so "
                "that it meets the specification below.</p>"
                + SPEC_HTML + RUN_TESTS_HTML,
    },
    {
        "task_no": 3,
        "file": "fix.c",
        "test_file": "test_username.c",
        "desc": "<h1>Fix the code</h1>"
                "<p>The editor contains an implementation of "
                "<code>process_username</code> that does not fully meet the "
                "specification below. Find and fix the problems.</p>"
                + SPEC_HTML + RUN_TESTS_HTML,
    },
]

@app.route("/api/pilot1/request-task-outcome", methods=["POST"])
@app.route("/api/pilot1/request-finish", methods=["POST"])
def pilot1_request_finish():
    """Record participant choice only. The trusted host advances the task.

    The legacy request-finish route defaults to completed for existing clients.
    A recorded choice is immutable until the host processes it.
    """
    if not getattr(CONFIG, "PILOT1_MODE", False):
        abort(404)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Expected JSON request"}), 400
    outcome = data.get("outcome", "completed")
    if outcome not in ("completed", "skipped"):
        return jsonify({"error": "Invalid task outcome"}), 400
    meta_path = "/opt/nerds/released-reference/active-task.json"
    try:
        with open(meta_path) as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return jsonify({"error": "Task metadata unavailable"}), 503
    code, pos = meta.get("task_code"), meta.get("position")
    if (code not in ("dense_v2", "lowyield_v1") or
        type(pos) is not int or pos not in (1, 2) or
        code != data.get("task_code") or pos != data.get("position") or
        meta.get("status") in ("completed", "skipped")):
        return jsonify({"error": "Task request does not match current task"}), 409

    marker = "/home/user/fuzz-study/.finish-request.json"
    import secrets
    import stat
    from datetime import timezone

    def read_existing():
        st = os.lstat(marker)
        if not stat.S_ISREG(st.st_mode) or st.st_size >= 2048:
            raise ValueError("Unsafe outcome request marker")
        with open(marker) as handle:
            recorded = json.load(handle)
        recorded_outcome = recorded.get("outcome", "completed")
        if (recorded.get("task_code") != code or
            recorded.get("position") != pos or
            recorded_outcome not in ("completed", "skipped")):
            raise ValueError("Pending request belongs to another task")
        token = recorded.get("completion_receipt")
        if pos == 2 and (not isinstance(token, str) or
                         __import__("re").fullmatch(r"[0-9a-f]{64}", token) is None):
            raise ValueError("Final outcome receipt is missing or invalid")
        return recorded_outcome, token

    def acknowledged(result):
        previous_outcome, token = result
        response = {"ok": True, "outcome": previous_outcome,
                    "state": "awaiting_operator"}
        if pos == 2:
            response["completion_receipt"] = token
        final = jsonify(response)
        final.headers["Cache-Control"] = "no-store"
        return final, 202

    if os.path.lexists(marker):
        try:
            pending = read_existing()
        except (ValueError, OSError):
            return jsonify({"error": "Existing task request needs operator review"}), 409
        if pending[0] != outcome:
            return jsonify({"error": "A different task outcome is already pending"}), 409
        return acknowledged(pending)

    entry = {"task_code": code, "position": pos, "outcome": outcome,
             "requested_at": datetime.now(timezone.utc).isoformat(),
             "request_id": secrets.token_hex(16)}
    if pos == 2:
        entry["completion_receipt"] = secrets.token_hex(32)
    tmp = marker + "." + secrets.token_hex(8) + ".tmp"
    try:
        with open(tmp, "x") as handle:
            json.dump(entry, handle)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic no-overwrite creation; cannot silently change Finish into Skip
        # (or vice versa) if requests arrive close together.
        os.link(tmp, marker)
    except FileExistsError:
        try:
            pending = read_existing()
        except (ValueError, OSError):
            return jsonify({"error": "Existing task request needs operator review"}), 409
        if pending[0] != outcome:
            return jsonify({"error": "A different task outcome is already pending"}), 409
        return acknowledged(pending)
    except OSError:
        return jsonify({"error": "Unable to record task outcome"}), 503
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return acknowledged((outcome, entry.get("completion_receipt")))


@app.route("/api/tasks")
def get_tasks():
    if getattr(CONFIG, "PILOT1_MODE", False):
        metadata_path = (
            "/opt/nerds/released-reference/active-task.json"
        )

        try:
            with open(metadata_path, "r") as f:
                active_task = json.load(f)
        except (OSError, ValueError):
            return jsonify({
                "error": "Active task has not been provisioned"
            }), 503

        if active_task.get("status") in ("completed", "skipped"):
            response = jsonify({"mode": "pilot1", "completed": True,
                                "final_outcome": active_task["status"],
                                "tasks": []})
            response.headers["Cache-Control"] = "no-store"
            return response

        task_code = active_task.get("task_code")
        position = active_task.get("position")

        descriptions = {
            "dense_v2": (
                "<h2>Dense v2 — Fuzzing Investigation</h2>"
                "<p>Investigate the provided C program using "
                "coverage-guided fuzzing.</p>"
                "<p>Examine the target source, available harnesses, "
                "and seed inputs. Select or adapt a harness, execute "
                "fuzzing campaigns, and investigate the feedback.</p>"
                "<p><strong>Working directory:</strong><br>"
                "<code>/home/user/fuzz-study/work</code></p>"
                "<p>You may modify your working files, experiment "
                "with different approaches, and use the internal "
                "browser as needed.</p>"
            ),
            "lowyield_v1": (
                "<h2>Low-Yield v1 — Fuzzing Investigation</h2>"
                "<p>Investigate the provided C program using "
                "coverage-guided fuzzing.</p>"
                "<p>Examine the available harnesses, run fuzzing "
                "campaigns, and analyze their results.</p>"
                "<p><strong>Working directory:</strong><br>"
                "<code>/home/user/fuzz-study/work</code></p>"
            ),
        }

        if (
            task_code not in descriptions
            or type(position) is not int
            or position not in (1, 2)
        ):
            return jsonify({
                "error": "Invalid active task metadata"
            }), 503

        if not os.path.isfile(
            "/home/user/fuzz-study/work/Makefile"
        ):
            return jsonify({
                "error": "Task workspace is unavailable"
            }), 503

        pending_outcome = None
        completion_receipt = None
        marker = "/home/user/fuzz-study/.finish-request.json"
        try:
            import stat
            st = os.lstat(marker)
            if stat.S_ISREG(st.st_mode) and 0 < st.st_size < 2048:
                with open(marker) as handle:
                    pending = json.load(handle)
                if (pending.get("task_code") == task_code and
                    pending.get("position") == position):
                    value = pending.get("outcome", "completed")
                    if value in ("completed", "skipped"):
                        pending_outcome = value
                        receipt = pending.get("completion_receipt")
                        if (position == 2 and isinstance(receipt, str) and
                            __import__("re").fullmatch(r"[0-9a-f]{64}", receipt)):
                            completion_receipt = receipt
        except (OSError, ValueError):
            pass

        response = jsonify({
            "mode": "pilot1",
            "pending_outcome": pending_outcome,
            "completion_receipt": completion_receipt,
            "tasks": [{
                "task_no": position,
                "position": position,
                "task_code": task_code,
                "title": task_code,
                "desc": descriptions[task_code],
            }],
        })

        response.headers["Cache-Control"] = "no-store"
        return response
    tasks = []
    for definition in TASK_DEFINITIONS:
        with open(os.path.join(TASKS_DIR, definition["file"])) as f:
            placeholder_code = f.read()
        tasks.append({
            "task_no": definition["task_no"],
            "desc": definition["desc"],
            "placeholder_code": placeholder_code,
        })

    # The frontend places the single task with fixed == true at the end and
    # shows the Finish button on it.
    tasks.append({
        "task_no": len(tasks) + 1,
        "fixed": True,
        "placeholder_code": "",
        "desc": "<p>You have finished all of the tasks. "
                "Click finish below to take a quick exit survey.</p>",
    })

    return jsonify({"tasks": tasks})


@app.route("/survey", methods=['GET'])
def forward_to_survey():
    '''
    User has finished, now redirect to the exit survey.
    '''
    try:
        with open(CONFIG.USER_DATA_FILE) as data_file:
            user_data = json.load(data_file)
            user_id = user_data["user_id"]
            token = user_data["token"]
            return redirect("/survey/"+user_id+"/"+token)
    except Exception:
        pass


@app.errorhandler(404)
def not_found(error):
    return 'Error: not found', 404



if __name__ == "__main__":
    os.chdir("/home/user")
    app.run(host='0.0.0.0', port=60000, debug=CONFIG.APP_MODE == "DEBUG")

