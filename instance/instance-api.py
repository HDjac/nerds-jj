import os.path
import logging
import os
import json
import tempfile
import urllib.request as url_request
from flask import Flask, request, redirect, make_response, jsonify, abort
from subprocess import run, PIPE, STDOUT, CalledProcessError, TimeoutExpired
from datetime import datetime


import config as CONFIG
from firefox import get_firefox_history

app = Flask(__name__)

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
    # Welcome to the study
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
            # The extension supplies `service` and `model`; default sensibly
            # for older clients that only send the ChatGPT prompt fields.
            "service": data.get("service") or "chatgpt",
            "model": data.get("model") or "unknown",
            "prompt": data.get("prompt"),
            "url": data.get("url"),
            # Stored as character varying
            "client_timestamp": str(client_timestamp) if client_timestamp is not None else None,
        }
        send_recv_data(payload)

        response = jsonify({"ok": True})
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response, 200

    except Exception as e:
        response = jsonify({"ok": False, "error": str(e)})
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response, 500

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

@app.route("/api/tasks")
def get_tasks():
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

