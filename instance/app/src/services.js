import {DEV_MODE, BACKEND_PRESENT} from "./util";

let API_BASE_PATH = "../api";
if (DEV_MODE) {
  API_BASE_PATH = "http://192.168.1.35:60000/api";
}
//const DEV_MODE = process.env.NODE_ENV === "development";
//const DEV_MODE = true;

function compile(data) {
  if (BACKEND_PRESENT) {
    return fetch(`${API_BASE_PATH}/compile`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(data)
    }).then((res) => {
      console.log("Received json back from server!")
      return res.json();
    });
  } else {
    return new Promise((resolve) => resolve({
      "result": "error", // No compiler available in dev mode, so nothing to run
      "js": "",
      "compiler_output": "DEV MODE TEST OUTPUT\nTHIS SHOULD NEVER BE SEEN IN PRODUCTION"
    }));
  }
}


function submit(nb_data) {
  // Submit the JSON object given by nb_data to the server
  if (BACKEND_PRESENT) {
    fetch(`${API_BASE_PATH}/submit`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(nb_data)
    }).catch(reason => {
      console.debug(`Submit error: ${reason}`);
    });
  } else {
    console.debug("Submitting data:");
    console.debug(nb_data);
  }
}


function get_tasks() {
  /* get_tasks: Get a list of tasks from the server
   * Returns a promise that resolves with task data*/

  /* Task format:
   * [
   *    {
   *      "suggestions": ["...", "...", ...]
   *      "desc": "..."
   *    }
   * ]
   */

  if (BACKEND_PRESENT) {
    return fetch(`${API_BASE_PATH}/tasks`, {cache: "no-store"}).then(async (res) => {
      const type = res.headers.get("content-type") || "";
      if (!type.includes("application/json")) {
        throw new Error("Your NERDs session may have expired. Please open a fresh invitation to continue.");
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Task service error: ${res.status}`);
      return data;
    });
  } else {
    console.debug("Sending debug response to get_tasks call");
    // Mirrors the shape served by the backend /api/tasks endpoint, which
    // reads the real starting code from read.c, write.c, and fix.c.
    const placeholder = `#include "username.h"\n\nint process_username(const char *input, char **username)\n{\n    /* TODO: Implement the function. */\n}`;
    return new Promise((resolve) => resolve({
      "tasks": [
        {
          "task_no": 1,
          "desc": "<h1>Review the code (dev mode)</h1><p>Add inline comments explaining what is wrong with the provided implementation of <code>process_username</code>. No test suite runs for this task.</p>",
          "placeholder_code": placeholder
        },
        {
          "task_no": 2,
          "desc": "<h1>Write the function (dev mode)</h1><p>Implement <code>process_username</code> from scratch.</p>",
          "placeholder_code": placeholder
        },
        {
          "task_no": 3,
          "desc": "<h1>Fix the code (dev mode)</h1><p>Find and fix the problems in the provided implementation.</p>",
          "placeholder_code": placeholder
        },
        {
          "task_no": 4,
          "fixed": true,
          "placeholder_code": "",
          "desc": "<p>You have finished all of the tasks. Click finish below to take a quick exit survey.</p>"
        }
      ]
    }));
  }
}

function requestPilotTaskOutcome(task, outcome) {
  if (!["completed", "skipped"].includes(outcome)) {
    return Promise.reject(new Error("Invalid task outcome"));
  }
  return fetch(`${API_BASE_PATH}/pilot1/request-task-outcome`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({task_code: task.task_code, position: task.position, outcome})
  }).then(async response => {
    if (!(response.headers.get("content-type") || "").includes("application/json")) {
      throw new Error("Your NERDs session may have expired. Please open a fresh invitation to continue.");
    }
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `Task outcome request failed: ${response.status}`);
    return payload;
  });
}

function set_resolution(width, height) {
  return fetch(`${API_BASE_PATH}/resolution`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({"width": width, "height": height})
  });
}

function activateWorkspace(target) {
  if (!["cli", "browser"].includes(target)) {
    return Promise.reject(new Error("Invalid workspace"));
  }

  if (!BACKEND_PRESENT) {
    return Promise.resolve({active: target});
  }

  return fetch(`${API_BASE_PATH}/workspace/activate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({target})
  }).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Workspace activation failed: ${response.status}`);
    }

    return response.json();
  });
}

export {
  submit,
  get_tasks,
  set_resolution,
  compile,
  activateWorkspace,
  requestPilotTaskOutcome
};
