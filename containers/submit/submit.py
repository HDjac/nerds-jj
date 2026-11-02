#! Copyright (C) 2017 Christian Stransky
#!
#! This software may be modified and distributed under the terms
#! of the MIT license.  See the LICENSE file for details.

import os
import logging
from flask import Flask
from flask import request
from flask import make_response
from flask import jsonify
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from pilot1_ai_payload import normalize_prompt
from pilot1_ai_auth import authenticate_ai_request
from pilot1_ai_db import store_ai_prompt
from pilot1_browser_db import store_browser_event
from pilot1_browser_payload import normalize_browser_observation
from pilot1_clipboard_payload import normalize_clipboard_observation
from pilot1_clipboard_db import store_clipboard_event
from sqlalchemy.dialects.postgresql import JSON
import datetime
import json
from functools import wraps
from urllib.parse import urlencode
from flask import redirect, request, current_app


app = Flask(__name__)
app.config.from_object('configSubmit')
app.config['PILOT1_AI_INGEST_ENABLED'] = (
    os.environ.get('PILOT1_AI_INGEST_ENABLED', '0') == '1'
)
app.config['PILOT1_BROWSER_INGEST_ENABLED'] = (
    os.environ.get('PILOT1_BROWSER_INGEST_ENABLED', '0') == '1'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['PILOT1_AI_REGISTRY_PATH'] = os.environ.get(
    'PILOT1_AI_REGISTRY_PATH',
    '/run/nerds/registry/participants.json'
)


MAX_LENGTH = 1000000 #max length for json size
NUM_RETRY = 5 # retry to fetch

db = SQLAlchemy(app)

# Jupyter Notebook model
class Jupyter(db.Model):
    __tablename__ = 'jupyter'
    
    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    code = db.Column(JSON)
    time = db.Column(JSON)
    status = db.Column(db.String(1)) # B: "Ok, got it!" button was hit, R: runing btn is hit, N: the skip btn is hit, S: next task, F: final submission
    date = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __init__(self, userid, token, code, time, status):
        self.userid = userid
        self.code = code
        self.time = time
        self.status = status
        self.token = token
    
    def __repr__(self):
        return '<User %s>' %{self.userid}

class Invites(db.Model):
    """ Model for invited email addresses """
    __tablename__ = "invites"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    token = db.Column(db.String, nullable=False)
    invited = db.Column(db.DateTime, nullable=True)
    blacklisted = db.Column(db.DateTime, nullable=True)
    bounced = db.Column(db.Boolean, nullable=True)
    pinged = db.Column(db.Integer, default=0)

    def __init__(self, emailid, email, token, invited, blacklisted, bounced, pinged):
        self.id = emailid
        self.email = email
        self.token = token
        invited = invited
        blacklisted = blacklisted
        bounced = bounced
        pinged = pinged

class CreatedInstances(db.Model):
    """ Model for created AWS instances """
    __tablename__ = "createdInstances"
    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    ip = db.Column(db.String())
    origin = db.Column(db.Integer)
    time = db.Column(db.DateTime, default=db.func.current_timestamp())
    ec2instance = db.Column(db.String())
    category = db.Column(db.Integer)
    condition = db.Column(db.Integer)
    instanceid = db.Column(db.String())
    finished = db.Column(db.Boolean)
    heartbeat = db.Column(db.DateTime, default=db.func.current_timestamp())
    instanceTerminated = db.Column(db.Boolean)

class Conditions(db.Model):
    """ Model for conditions """
    __tablename__ = "conditions"
    category = db.Column(db.Integer, primary_key=True)
    condition = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String())
    hash = db.Column(db.String())
    
    def __init__(self, id, name, description):
        self.id = id
        self.name = name
        self.description = description

    
class CopyPastedCode(db.Model):
    """ Model for storage of copy and pasted code """
    __tableName__ = "copyPastedCode"
    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    tasknum = db.Column(db.String())
    cellid = db.Column(db.String())
    code = db.Column(db.String())
    time = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __init__(self, userid, token, tasknum, cellid, code):
        self.userid = userid
        self.token = token
        self.tasknum = tasknum
        self.cellid = cellid
        self.code = code

class LlmPrompts(db.Model):
    """ Model for LLM prompts logged by the in-instance browser extension """
    __tablename__ = "llm_prompts"
    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    service = db.Column(db.String())
    model = db.Column(db.String())
    prompt = db.Column(db.String())
    url = db.Column(db.String())
    client_timestamp = db.Column(db.String())
    time = db.Column(db.DateTime, default=db.func.current_timestamp())

    def __init__(self, userid, token, service, model, prompt, url, client_timestamp):
        self.userid = userid
        self.token = token
        self.service = service
        self.model = model
        self.prompt = prompt
        self.url = url
        self.client_timestamp = client_timestamp


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)


@app.route('/getcode/<string:userid>/<string:token>')
def getcode(userid, token):
    from pygments import highlight
    from pygments.lexers import PythonLexer
    from pygments.formatters import HtmlFormatter

    row = Jupyter.query.filter_by(userid = userid).filter_by(token = token).filter_by(status = 'f').first()
    if row == None:
        return "NotFound"
    code = {}
    for cell in row.code['cells']:
        if cell['cell_type'] == 'code':
            tasknum =  cell['metadata'].get('tasknum')
            if tasknum == None:
                continue
            plain_code = cell['source']
            highlighted_code = highlight(plain_code, PythonLexer(), HtmlFormatter())
            code['code'+tasknum] = highlighted_code
    callback = request.args.get('callback', False)
    if callback:
        content = str(callback) + '(' + str(json.dumps(code)) + ')'
        return current_app.response_class(content, mimetype='application/json')

    return json.dumps(code)

    
# Retrieve latest ipynb for the user from the DB.
# Or if new user, then return default task file.
@app.route('/get_ipynb/<string:userid>/<string:token>')
def get_ipynb(userid, token):
    print("Hello debug!")
    row = Jupyter.query.filter_by(userid = userid).filter_by(token = token).order_by(Jupyter.id.desc()).first()
    if row == None:
        user_row = CreatedInstances.query.filter_by(userid = userid).first()
        condition_row = Conditions.query.filter_by(condition = user_row.condition).first()
        with open(app.config["TASKFILES_BASE_PATH"]+condition_row.filename) as file:
            return file.read()
        
    return json.dumps(row.code)


@app.route('/survey/<string:userid>/<string:token>')
def redirectToSurvey(userid, token):
    row = CreatedInstances.query.filter_by(userid=userid).first()
    if row == None:
        return 'userid ' + userid + ' does not exist!'

    row.finished = True
    db.session.commit()

    # Use PID parity to recover condition:
    # even PID = AI, odd PID = NON_AI
    try:
        participant_num = int(userid)
        condition = "AI" if participant_num % 2 == 0 else "NON_AI"
    except (TypeError, ValueError):
        condition = "UNKNOWN"

    query_params = {
        "participant_id": userid,
        "ext_ref": userid,
        "condition": condition,
        "custom1": row.origin
    }

    base_url = app.config["FINAL_SURVEY_URL"]

    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        base_url = "https://" + base_url

    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}{urlencode(query_params)}"

    print(url)
    return redirect(url, code=302)



@app.route('/pilot1/ai-prompt', methods=['POST'])
def pilot1_ai_prompt():
    """Authenticated Pilot 1 prompt ingestion."""
    if not app.config.get('PILOT1_AI_INGEST_ENABLED', False):
        return jsonify({'error': 'AI ingestion disabled'}), 503

    try:
        trusted_instance_id = authenticate_ai_request(
            remote_addr=request.remote_addr,
            headers=request.headers,
            registry_path=app.config.get(
                'PILOT1_AI_REGISTRY_PATH',
                '/run/nerds/registry/participants.json'
            ),
            secret_path=app.config.get(
                'PILOT1_AI_GATEWAY_SECRET_PATH',
                '/run/secrets/pilot1_ai_gateway_token'
            )
        )
    except PermissionError:
        return jsonify({'error': 'Unauthorized AI ingestion request'}), 403

    try:
        observation = normalize_prompt(request.get_json(silent=True))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid AI observation'}), 400

    try:
        stored = store_ai_prompt(trusted_instance_id, observation)
    except Exception as exc:
        # Duplicate UUID with different content raises a database exception.
        # All other failures fail closed; never falsely acknowledge capture.
        if 'Conflicting interaction UUID' in str(exc):
            return jsonify({'error': 'Conflicting interaction UUID'}), 409
        app.logger.exception('Pilot 1 AI ingestion failed')
        return jsonify({'error': 'AI ingestion temporarily unavailable'}), 503

    return jsonify({'ok': True, 'event_id': stored['event_id'],
                    'inserted': stored['inserted']}), 200




@app.route('/pilot1/clipboard-event', methods=['POST'])
def pilot1_clipboard_event():
    """Trusted-gateway clipboard observation; disabled by default."""
    if os.environ.get('PILOT1_CLIPBOARD_INGEST_ENABLED', '0') != '1':
        return jsonify({'error':'Clipboard ingestion disabled'}),503
    if request.content_length is None or request.content_length > 8192:
        return jsonify({'error':'Clipboard request too large'}),413
    try:
        trusted_instance_id = authenticate_ai_request(
            remote_addr=request.remote_addr, headers=request.headers,
            registry_path=app.config.get('PILOT1_AI_REGISTRY_PATH', '/run/nerds/registry/participants.json'),
            secret_path=app.config.get('PILOT1_AI_GATEWAY_SECRET_PATH', '/run/secrets/pilot1_ai_gateway_token'))
    except PermissionError:
        return jsonify({'error':'Unauthorized clipboard ingestion'}),403
    try:
        normalized = normalize_clipboard_observation(
            request.get_json(silent=True),
            allow_text=os.environ.get('PILOT1_CLIPBOARD_TEXT_ENABLED', '0') == '1')
    except (TypeError, ValueError):
        return jsonify({'error':'Invalid clipboard observation'}),400
    try:
        saved=store_clipboard_event(trusted_instance_id, normalized)
    except Exception as exc:
        reason=str(exc)
        if ('Stale task clipboard observation' in reason or
            'Conflicting clipboard event UUID' in reason):
            return jsonify({'error':'Stale or conflicting clipboard event'}),409
        if 'No eligible study session' in reason:
            return jsonify({'error':'No eligible session'}),403
        # Never log exception or request payload: may contain clipboard text.
        return jsonify({'error':'Clipboard ingestion unavailable'}),503
    return jsonify({'ok':True,'event_id':saved['event_id'],'inserted':saved['inserted']}),200

@app.route('/pilot1/browser-event', methods=['POST'])
def pilot1_browser_event():
    """Browser events via the same authenticated instance gateway as AI prompts."""
    if not app.config.get('PILOT1_BROWSER_INGEST_ENABLED', False):
        return jsonify({'error': 'Browser ingestion disabled'}), 503

    # Reject large requests before parsing JSON (and enforce a bound for
    # chunked requests using Werkzeug's maximum content length).
    if request.content_length is not None and request.content_length > 16384:
        return jsonify({'error': 'Browser observation too large'}), 413

    try:
        trusted_instance_id = authenticate_ai_request(
            remote_addr=request.remote_addr,
            headers=request.headers,
            registry_path=app.config.get(
                'PILOT1_AI_REGISTRY_PATH',
                '/run/nerds/registry/participants.json'
            ),
            secret_path=app.config.get(
                'PILOT1_AI_GATEWAY_SECRET_PATH',
                '/run/secrets/pilot1_ai_gateway_token'
            )
        )
    except PermissionError:
        return jsonify({'error': 'Unauthorized browser ingestion'}), 403

    try:
        normalized = normalize_browser_observation(request.get_json(silent=True))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid browser observation'}), 400

    try:
        stored = store_browser_event(trusted_instance_id, normalized)
    except Exception as exc:
        # Stale task observations are terminally rejected, not rebound to
        # whichever task is now active; duplicate UUID conflicts also 409.
        reason = str(exc)
        if ('Stale task browser observation' in reason or
                'Conflicting browser event UUID' in reason or
                'No released task' in reason):
            return jsonify({'error': 'Stale or conflicting browser event'}), 409
        if 'No eligible study session' in reason:
            return jsonify({'error': 'No eligible active session'}), 403
        app.logger.exception('Pilot 1 browser ingestion failed')
        return jsonify({'error': 'Browser ingestion unavailable'}), 503

    return jsonify({'ok': True, 'event_id': stored['event_id'],
                    'inserted': stored['inserted']}), 200


@app.route('/submit', methods=['POST'])
def submit():
    data = json.loads(request.data)
    if data['auth-token'] == app.config["SUBMIT_SECRET"]:
        try:
            jsonPayload = json.loads(data['json-payload'])
            if(len(jsonPayload) <= MAX_LENGTH):
                if (jsonPayload['type'] == 'pasted'):
                    row = CopyPastedCode(jsonPayload['user_id'], jsonPayload['token'], jsonPayload['tasknum'], jsonPayload['cellid'], jsonPayload['code'])
                    db.session.add(row)
                    db.session.commit()
                elif (jsonPayload['type'] == 'code'):
                    row = Jupyter(jsonPayload['user_id'], jsonPayload['token'], jsonPayload['code'], jsonPayload['time'], jsonPayload['status'])
                    db.session.add(row)
                    db.session.commit()
                elif (jsonPayload['type'] == 'llm_prompt'):
                    row = LlmPrompts(jsonPayload['user_id'], jsonPayload['token'], jsonPayload.get('service'), jsonPayload.get('model'), jsonPayload.get('prompt'), jsonPayload.get('url'), jsonPayload.get('client_timestamp'))
                    db.session.add(row)
                    db.session.commit()
            else:
                return "Input exceeded max length", 400
        except Exception as e:
            print(e)
            db.session.rollback()
            return "Error inserting json payload into database.", 500
            
        return "Successfully inserted json payload into database."
    else:
        abort(401)

if __name__ == '__main__':
    #app.debug = True
    app.run(host='0.0.0.0', port=8000)
