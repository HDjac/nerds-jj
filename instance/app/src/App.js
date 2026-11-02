import './App.css';
import {useState, useEffect, useRef} from 'react';

import BrowserView from "./views/BrowserView";
import StatusDot from "./components/StatusDot";
import TaskController from "./components/PilotTaskController";
import TabNav from "./components/TabNav";

import Header from "./components/Header";
import useFocusTime from "./hooks/useFocusTime";
import useSavedState from "./hooks/useSavedState";
import useTaskState from "./hooks/useTaskState";
import {submit, compile, activateWorkspace, setWorkspaceLayout, getWorkspaceFocus} from "./services";

const SPLIT_WORKSPACE = process.env.REACT_APP_NERDS_SPLIT_WORKSPACE === "1";

function App() {
  const [tab, setTab] = useSavedState("tab", "cli");
  const [workspaceMode, setWorkspaceMode] = useSavedState("r2d-workspace-mode", "split");
  const [cliWidth, setCliWidth] = useSavedState("r2d-cli-width", 50);
  const [dragWidth, setDragWidth] = useState(null);
  const [focusedApp, setFocusedApp] = useState("unknown");
  const [layoutError, setLayoutError] = useState("");
  const surfaceRef = useRef(null);
  const draggingRef = useRef(false);
  const activeWidth = dragWidth ?? cliWidth;
  const mode = ["split", "cli", "browser"].includes(workspaceMode) ? workspaceMode : "split";
  const safeWidth = Number.isInteger(cliWidth) && cliWidth >= 30 && cliWidth <= 70 ? cliWidth : 50;

  function applyLayout(nextMode, nextWidth = safeWidth) {
    setLayoutError("");
    setWorkspaceLayout(nextMode, nextWidth).then(result => {
      if (result.focus === "cli" || result.focus === "browser") setFocusedApp(result.focus);
    }).catch(error => setLayoutError(error.message));
  }

  function chooseMode(nextMode) {
    setWorkspaceMode(nextMode);
    if (nextMode === "cli" || nextMode === "browser") {
      setFocusedApp(nextMode);
    }
    applyLayout(nextMode);
  }

  function updateDrag(clientX) {
    const bounds = surfaceRef.current?.getBoundingClientRect();
    if (!bounds?.width) return;
    const next = Math.round((clientX - bounds.left) / bounds.width * 100);
    setDragWidth(Math.max(30, Math.min(70, next)));
  }

  function startDivider(event) {
    if (event.button !== 0) return;
    draggingRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    updateDrag(event.clientX);
    event.preventDefault();
  }

  function moveDivider(event) {
    if (draggingRef.current) updateDrag(event.clientX);
  }

  function finishDivider(event) {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    const bounds = surfaceRef.current?.getBoundingClientRect();
    const next = bounds?.width
      ? Math.max(30, Math.min(70, Math.round((event.clientX - bounds.left) / bounds.width * 100)))
      : safeWidth;
    setDragWidth(null);
    setCliWidth(next);
    applyLayout("split", next);
  }

  const [connStatus, setConnStatus] = useState(false);
  const [taskno, set_taskno] = useSavedState("taskno", 0);
  const [task_list, set_task_list] = useSavedState("task_list", [
    {
    title: "Loading...",
    desc: "Loading task...",
    placeholder_code: "",
    fixed: true,
    task_no: 0
    }
  ]);

    //Default tasks to put into array if array is empty it should pull from tasks.json
    //{placeholder_code:"pub fn print(&self) {\n\n}",desc:"<h1 id=\"add-item\">Print List</h1>",task_no:1},
    //{placeholder_code:"pub fn insert_at(&mut self, item: I, position: usize) -> Result<String, ()> {\n\n}",desc:"<h1 id=\"update-item\">Update item</h1>",task_no:2},
    //{placeholder_code:"pub fn remove(&mut self, position: usize) -> Result<String, Box<LinkedListNode<I>>> {\n\n}",desc:"<h1 id=\"remove-item\">Remove item</h1>",task_no:3},
    //{placeholder_code:"pub fn swap(&mut self, a: usize, b: usize) -> Result<String, ()> {\n\n}",desc:"<h1>Swap Items</h1>",task_no:4},
    //{placeholder_code:"","fixed":true,desc:"You have finished all of the tasks. Click finish below to take a quick exit survey.",task_no:5}

  const [outputs, set_outputs] = useSavedState("output", ["", "", "", "", "", ""])
  //const [output, set_output] = useTaskState("output", taskno, "");
  const [editorValues, setEditorValues] = useSavedState("editorValue", task_list.map(t => t.placeholder_code));


  const task = task_list[taskno] || {
    title: "Loading...",
    desc: "Loading task...",
    placeholder_code: "",
    fixed: true,
    task_no: taskno
  };

  //pseudo state for value in state array
  const editor_value = editorValues[taskno] || "";



  const set_editor_value = new_value => {
    setEditorValues(
      editorValues.map((item, i) => (i===taskno) ? new_value: item)
    )
  }


  useEffect(() => {
    if (task.placeholder_code !== "" && (editor_value == null || editor_value === "")) {
      set_editor_value(task.placeholder_code);
    }
  }, [taskno, task_list]);

  
  useEffect(() => {
    if (task_list.length > 0 && editorValues.length !== task_list.length) {
      setEditorValues(task_list.map(t => t.placeholder_code || ""));
    }
  }, [task_list]);

  useEffect(() => {
    if (task_list.length > 0 && outputs.length !== task_list.length) {
      set_outputs(task_list.map(() => ""));
    }
  }, [task_list]);




  const output = outputs[taskno];
  const set_output = new_value => {
    // Supports both plain values and functional updates (WasmRunner passes
    // updater functions), and updates against the latest outputs array so
    // rapid successive prints append instead of clobbering each other.
    set_outputs(outputs =>
      outputs.map((item, i) => {
        if (i !== taskno) return item;
        const resolved = typeof new_value === "function" ? new_value(item ?? "") : new_value;
        return resolved ?? "";
      })
    )
  }

  

  const editorRef = useRef(null);
  const focus_time = useFocusTime();

  // Migrate previously saved CODE tabs to CLI.
  useEffect(() => {
    if (tab !== "cli" && tab !== "browser") {
      setTab("cli");
    }
  }, [tab, setTab]);

  // Task transitions must retile the new xterm without losing Firefox.
  useEffect(() => {
    const onReleasedTask = () => {
      if (SPLIT_WORKSPACE) {
        setFocusedApp("unknown");
        window.setTimeout(() => applyLayout(mode, safeWidth), 1300);
      } else {
        setTab("cli");
        activateWorkspace("cli").catch(() => {
          window.setTimeout(() => activateWorkspace("cli").catch(() => {}), 1500);
        });
      }
    };
    window.addEventListener("nerds:pilot-task-released", onReleasedTask);
    return () => window.removeEventListener("nerds:pilot-task-released", onReleasedTask);
  });

  // Keep the original tabbed behavior when the split feature is disabled.
  useEffect(() => {
    if (!connStatus || SPLIT_WORKSPACE) return;
    if (tab === "cli" || tab === "browser") {
      activateWorkspace(tab).catch(error => console.error("Workspace switching failed:", error));
    }
  }, [tab, connStatus]);

  // Get the focused remote X11 window. Never assume that an HTML toolbar
  // selection proves where clipboard data originated.
  useEffect(() => {
    if (!SPLIT_WORKSPACE || !connStatus) return undefined;
    let mounted = true;
    const update = () => getWorkspaceFocus().then(value => {
      if (mounted) setFocusedApp(value);
    });
    update();
    const interval = window.setInterval(update, 500);
    return () => { mounted = false; window.clearInterval(interval); };
  }, [connStatus]);

  // Reapply split layout once on VNC connect and on fresh page load.
  useEffect(() => {
    if (!SPLIT_WORKSPACE || !connStatus) return undefined;
    applyLayout(mode, safeWidth);
    return undefined;
  }, [connStatus]);

  function submit_code(statusCode, extraData) {
    // Do some submitting
    /* Submit format
     * {
     *  type: [code]
     *  code: custom code format
     *  time: {focusTime: focusTime}
     *  status: <status code, one letter>
     * }
     */
    /* Code format
     * {
     *  editor: <str> Whatever is in the editor, either a suggestion or a code snippet
     *  taskno: <int> What task number the user is on
     *  output: <str, optional> Any code output
     *  hist: <object> Firefox history, added by backend before being sent to database
     * }
     */
    /* Status Codes
     *  n   next task
     *  s   skip task
     *  p   previous task
     *  a   previous suggestion
     *  b   next suggestion
     *  c   pick suggestion
     *  r   run code
     *  t   back to suggestions (quit editor)
     *  e   browser error
     */
    let data = {
      "type": "code",
      "code": {"taskno": taskno},
      "time": {"focus_time": focus_time},
      "status": statusCode
    }

    console.debug(`submit ${statusCode}`);
    if (editorRef.current) {
      data.code.editor = editorRef.current.getValue();
    }
    if (output) {
      data.code.output = output;
    }
    if (extraData) {
      data.code.extra_data = extraData;
    }
    submit(data);
  }

  function compile_code(code) {
    submit_code("r");
    // Send the task's stable task_no, not its position in the shuffled
    // task list, so the backend compiles against the right task's tests
    return compile({code: code, taskno: task.task_no});
  }

  /* Setup error handlers */
  function handleError(e) { 
    let data = {};
    if (e instanceof PromiseRejectionEvent) {
      // Quietly ignore this error, we'll see it in other data
      if (e.reason instanceof WebAssembly.RuntimeError) return;

      data = {reason: e.reason};
    } else {
      data = {
        message: e.message,
        source: e.filename,
        lineno: e.lineno,
        colno: e.colno,
      }
    }
    submit_code("e", data);
  }

  useEffect(() => {
    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleError);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleError)
    };
  });

  return (
    <>
      <Header />
      <div className="container-fluid main">
        <TaskController
          taskno={[taskno, set_taskno]}
          task_list={[task_list, set_task_list]}
          submit={submit_code}
        />
        <div className="views-container">
          <div className="navBar">
            {SPLIT_WORKSPACE ? (
              <div className="workspaceModeControls" role="group" aria-label="Workspace layout">
                {["split", "cli", "browser"].map(choice => (
                  <button key={choice} type="button" aria-pressed={mode === choice}
                    onClick={() => chooseMode(choice)}>
                    {choice === "split" ? "Split view" : choice === "cli" ? "CLI only" : "Firefox only"}
                  </button>
                ))}
              </div>
            ) : <TabNav tab={tab} setTab={setTab}/>}
            <div className="statusBar">
              {SPLIT_WORKSPACE && <span className="focusedAppIndicator">
                Focus: {focusedApp === "cli" ? "CLI" : focusedApp === "browser" ? "Firefox" : "unknown"}
              </span>}
              <StatusDot label="Connection" status={connStatus}/>
            </div>
          </div>
          {SPLIT_WORKSPACE && layoutError && (
            <p className="workspaceLayoutError" role="alert">{layoutError}.
              Use CLI only or Firefox only if the window manager cannot tile both applications.</p>
          )}
          <div className="tab-views">
            <div className="tabView workspaceSurface" ref={surfaceRef}>
              <BrowserView
                setConnStatus={setConnStatus}
                currentTab={SPLIT_WORKSPACE ? focusedApp : tab}
                splitMode={SPLIT_WORKSPACE}
                splitPercent={mode === "split" ? activeWidth : null}
                onFocusedWorkspace={setFocusedApp}
              />
              {SPLIT_WORKSPACE && mode === "split" && (
                <div className="workspaceDivider" role="separator"
                  aria-label="Resize CLI and Firefox panes"
                  aria-orientation="vertical" aria-valuenow={activeWidth}
                  aria-valuemin={30} aria-valuemax={70} tabIndex={0}
                  style={{left: `${activeWidth}%`}}
                  onPointerDown={startDivider}
                  onPointerMove={moveDivider}
                  onPointerUp={finishDivider}
                  onPointerCancel={() => { draggingRef.current = false; setDragWidth(null); }}
                  onKeyDown={event => {
                    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                    event.preventDefault();
                    const next = Math.max(30, Math.min(70,
                      safeWidth + (event.key === "ArrowLeft" ? -5 : 5)));
                    setCliWidth(next);
                    applyLayout("split", next);
                  }}>
                  <span className="workspaceDividerGrip">⋮</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

    </>
  );
}

export default App;
