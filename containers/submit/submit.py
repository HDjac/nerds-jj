#! Copyright (C) 2017 Christian Stransky
#!
#! This software may be modified and distributed under the terms
#! of the MIT license.  See the LICENSE file for details.

from flask import Flask
from flask import request
from flask import make_response
from flask import jsonify
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON
import datetime
import json
from functools import wraps
from urllib.parse import urlencode
from flask import redirect, current_app


app = Flask(__name__)
app.config.from_object('configSubmit')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

MAX_LENGTH = 1000000  # max length for json size
NUM_RETRY = 5  # retry to fetch

db = SQLAlchemy(app)


# Jupyter Notebook model
class Jupyter(db.Model):
    __tablename__ = 'jupyter'

    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    code = db.Column(JSON)
    time = db.Column(JSON)
    status = db.Column(db.String(1))
    # B: "Ok, got it!" button was hit
    # R: running button was hit
    # N: skip button was hit
    # S: next task
    # F: final submission
    date = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )

    def __init__(self, userid, token, code, time, status):
        self.userid = userid
        self.code = code
        self.time = time
        self.status = status
        self.token = token

    def __repr__(self):
        return '<User %s>' % self.userid


class Invites(db.Model):
    """Model for invited email addresses."""

    __tablename__ = "invites"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    token = db.Column(db.String, nullable=False)
    invited = db.Column(db.DateTime, nullable=True)
    blacklisted = db.Column(db.DateTime, nullable=True)
    bounced = db.Column(db.Boolean, nullable=True)
    pinged = db.Column(db.Integer, default=0)

    def __init__(
        self,
        emailid,
        email,
        token,
        invited,
        blacklisted,
        bounced,
        pinged
    ):
        self.id = emailid
        self.email = email
        self.token = token
        self.invited = invited
        self.blacklisted = blacklisted
        self.bounced = bounced
        self.pinged = pinged


class CreatedInstances(db.Model):
    """Model for created study instances."""

    __tablename__ = "createdInstances"

    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    ip = db.Column(db.String())
    origin = db.Column(db.Integer)
    time = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )
    ec2instance = db.Column(db.String())
    category = db.Column(db.Integer)
    condition = db.Column(db.Integer)
    instanceid = db.Column(db.String())
    finished = db.Column(db.Boolean)
    heartbeat = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )
    instanceTerminated = db.Column(db.Boolean)

    # Explicit recruitment metadata.
    recruitment_source = db.Column(db.String(32))
    prolific_study_id = db.Column(db.String(128))


class Conditions(db.Model):
    """Model for conditions."""

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
    """Model for storage of copy and pasted code."""

    __tableName__ = "copyPastedCode"

    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    tasknum = db.Column(db.String())
    cellid = db.Column(db.String())
    code = db.Column(db.String())
    time = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )

    def __init__(self, userid, token, tasknum, cellid, code):
        self.userid = userid
        self.token = token
        self.tasknum = tasknum
        self.cellid = cellid
        self.code = code


class LlmPrompts(db.Model):
    """Model for LLM prompts logged by the in-instance browser extension."""

    __tablename__ = "llm_prompts"

    id = db.Column(db.Integer, primary_key=True)
    userid = db.Column(db.String())
    token = db.Column(db.String())
    service = db.Column(db.String())
    model = db.Column(db.String())
    prompt = db.Column(db.String())
    url = db.Column(db.String())
    client_timestamp = db.Column(db.String())
    time = db.Column(
        db.DateTime,
        default=db.func.current_timestamp()
    )

    def __init__(
        self,
        userid,
        token,
        service,
        model,
        prompt,
        url,
        client_timestamp
    ):
        self.userid = userid
        self.token = token
        self.service = service
        self.model = model
        self.prompt = prompt
        self.url = url
        self.client_timestamp = client_timestamp


@app.errorhandler(404)
def not_found(error):
    return make_response(
        jsonify({'error': 'Not found'}),
        404
    )


@app.route('/getcode/<string:userid>/<string:token>')
def getcode(userid, token):
    from pygments import highlight
    from pygments.lexers import PythonLexer
    from pygments.formatters import HtmlFormatter

    row = (
        Jupyter.query
        .filter_by(userid=userid)
        .filter_by(token=token)
        .filter_by(status='f')
        .first()
    )

    if row is None:
        return "NotFound"

    code = {}

    for cell in row.code['cells']:
        if cell['cell_type'] == 'code':
            tasknum = cell['metadata'].get('tasknum')

            if tasknum is None:
                continue

            plain_code = cell['source']

            highlighted_code = highlight(
                plain_code,
                PythonLexer(),
                HtmlFormatter()
            )

            code['code' + tasknum] = highlighted_code

    callback = request.args.get('callback', False)

    if callback:
        content = (
            str(callback)
            + '('
            + str(json.dumps(code))
            + ')'
        )

        return current_app.response_class(
            content,
            mimetype='application/json'
        )

    return json.dumps(code)


# Retrieve latest ipynb for the user from the DB.
# If this is a new user, return the default task file.
@app.route('/get_ipynb/<string:userid>/<string:token>')
def get_ipynb(userid, token):
    print("Hello debug!")

    row = (
        Jupyter.query
        .filter_by(userid=userid)
        .filter_by(token=token)
        .order_by(Jupyter.id.desc())
        .first()
    )

    if row is None:
        user_row = (
            CreatedInstances.query
            .filter_by(userid=userid)
            .first()
        )

        condition_row = (
            Conditions.query
            .filter_by(condition=user_row.condition)
            .first()
        )

        with open(
            app.config["TASKFILES_BASE_PATH"]
            + condition_row.filename
        ) as file:
            return file.read()

    return json.dumps(row.code)


@app.route('/survey/<string:userid>/<string:token>')
def redirectToSurvey(userid, token):
    row = (
        CreatedInstances.query
        .filter_by(userid=userid)
        .first()
    )

    if row is None:
        return 'userid ' + userid + ' does not exist!'

    # Mark the NERDs portion of the study as finished
    # before redirecting the participant to QuestionPro.
    row.finished = True
    db.session.commit()

    # Recover the AI condition from participant ID parity:
    # even PID = AI
    # odd PID = NON_AI
    try:
        participant_num = int(userid)

        condition = (
            "AI"
            if participant_num % 2 == 0
            else "NON_AI"
        )

    except (TypeError, ValueError):
        condition = "UNKNOWN"

    # Prefer the explicit recruitment source that was saved
    # during the landing flow.
    #
    # Fall back to the legacy integer origin field so older
    # participants continue to work.
    if (
        row.recruitment_source is not None
        and str(row.recruitment_source).strip() != ""
    ):
        recruitment_source = (
            str(row.recruitment_source).strip()
        )

    elif row.origin == 1:
        recruitment_source = "prolific"

    else:
        recruitment_source = (
            str(row.origin)
            if row.origin is not None
            else "0"
        )

    # This is the actual Prolific study ID.
    # It will be empty for non-Prolific participants.
    prolific_study_id = (
        str(row.prolific_study_id).strip()
        if row.prolific_study_id is not None
        else ""
    )

    # Final QuestionPro system-variable mapping:
    #
    # custom1 = NERDs participant ID
    # custom2 = AI / NON_AI
    # custom3 = recruitment source
    # custom4 = Prolific study ID
    query_params = {
        "custom1": userid,
        "custom2": condition,
        "custom3": recruitment_source,
        "custom4": prolific_study_id
    }

    base_url = app.config["FINAL_SURVEY_URL"]

    if not (
        base_url.startswith("http://")
        or base_url.startswith("https://")
    ):
        base_url = "https://" + base_url

    separator = "&" if "?" in base_url else "?"

    url = (
        f"{base_url}"
        f"{separator}"
        f"{urlencode(query_params)}"
    )

    print(url)

    return redirect(
        url,
        code=302
    )


@app.route('/submit', methods=['POST'])
def submit():
    data = json.loads(request.data)

    if data['auth-token'] == app.config["SUBMIT_SECRET"]:
        try:
            jsonPayload = json.loads(
                data['json-payload']
            )

            if len(jsonPayload) <= MAX_LENGTH:

                if jsonPayload['type'] == 'pasted':
                    row = CopyPastedCode(
                        jsonPayload['user_id'],
                        jsonPayload['token'],
                        jsonPayload['tasknum'],
                        jsonPayload['cellid'],
                        jsonPayload['code']
                    )

                    db.session.add(row)
                    db.session.commit()

                elif jsonPayload['type'] == 'code':
                    row = Jupyter(
                        jsonPayload['user_id'],
                        jsonPayload['token'],
                        jsonPayload['code'],
                        jsonPayload['time'],
                        jsonPayload['status']
                    )

                    db.session.add(row)
                    db.session.commit()

                elif jsonPayload['type'] == 'llm_prompt':
                    row = LlmPrompts(
                        jsonPayload['user_id'],
                        jsonPayload['token'],
                        jsonPayload.get('service'),
                        jsonPayload.get('model'),
                        jsonPayload.get('prompt'),
                        jsonPayload.get('url'),
                        jsonPayload.get(
                            'client_timestamp'
                        )
                    )

                    db.session.add(row)
                    db.session.commit()

            else:
                return "Input exceeded max length", 400

        except Exception as e:
            print(e)

            db.session.rollback()

            return (
                "Error inserting json payload into database.",
                500
            )

        return (
            "Successfully inserted json payload into database."
        )

    else:
        abort(401)


if __name__ == '__main__':
    # app.debug = True

    app.run(
        host='0.0.0.0',
        port=8000
    )
