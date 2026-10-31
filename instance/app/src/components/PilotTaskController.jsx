import { useEffect, useRef, useState } from "react";
import "./TaskController.css";
import { FuzzingQuickStart, FuzzingGuideModal } from "./FuzzingGuide";
import { get_tasks, requestPilotTaskOutcome } from "../services";

const TASK_NAMES = {
  dense_v2: "Dense v2",
  lowyield_v1: "Low-Yield v1",
};

export default function PilotTaskController() {
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [completed, setCompleted] = useState(false);
  const [finalOutcome, setFinalOutcome] = useState(null);
  const [pendingOutcome, setPendingOutcome] = useState(null);
  const [sending, setSending] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const lastPosition = useRef(null);

  function openReceiptPage(receipt) {
    if (typeof receipt !== "string" || !/^[a-f0-9]{64}$/.test(receipt)) return false;
    // Keep the bearer receipt out of request URLs, referrers, and server logs.
    window.sessionStorage.setItem("nerds-pilot1-completion-receipt", receipt);
    window.location.replace(`/study-complete#receipt=${receipt}`);
    return true;
  }

  useEffect(() => {
    let mounted = true;
    const refresh = () => get_tasks().then(data => {
      if (!mounted) return;
      if (data?.mode !== "pilot1") throw new Error("Invalid Pilot 1 task response");
      if (data.completed === true) {
        // Only a successful authenticated response can confirm completion here.
        const receipt = window.sessionStorage.getItem("nerds-pilot1-completion-receipt");
        if (openReceiptPage(receipt)) return;
        setTask(null);
        setPendingOutcome(null);
        setFinalOutcome(data.final_outcome === "skipped" ? "skipped" : "completed");
        setCompleted(true);
        setError(null);
        setLoading(false);
        return;
      }
      if (!Array.isArray(data.tasks) || data.tasks.length !== 1) {
        throw new Error("Invalid Pilot 1 task response");
      }
      const active = data.tasks[0];
      if (active.position === 2 && ["completed", "skipped"].includes(data.pending_outcome)
          && openReceiptPage(data.completion_receipt)) return;
      if (!TASK_NAMES[active.task_code] || ![1, 2].includes(active.position)
          || typeof active.desc !== "string") {
        throw new Error("Invalid active task");
      }
      // Never reuse an older participant's receipt when a task is available.
      window.sessionStorage.removeItem("nerds-pilot1-completion-receipt");
      // sessionStorage covers a browser refresh during the workspace swap.
      const previous = lastPosition.current ?? Number(
        window.sessionStorage.getItem("nerds-pilot1-task-position") || 0
      );
      if (previous > 0 && previous !== active.position) {
        setPendingOutcome(null);
        window.dispatchEvent(new CustomEvent("nerds:pilot-task-released", {
          detail: { position: active.position, task_code: active.task_code }
        }));
      }
      lastPosition.current = active.position;
      window.sessionStorage.setItem("nerds-pilot1-task-position", String(active.position));
      setPendingOutcome(["completed", "skipped"].includes(data.pending_outcome)
        ? data.pending_outcome : null);
      setTask(active);
      setLoading(false);
      setError(null);
    }).catch(err => {
      if (mounted) {
        setError(err.message);
        setLoading(false);
      }
    });
    refresh();
    const poll = window.setInterval(refresh, 5000);
    return () => { mounted = false; window.clearInterval(poll); };
  }, []);

  async function requestOutcome(outcome) {
    if (!task || sending || pendingOutcome) return;
    if (!["completed", "skipped"].includes(outcome)) return;
    const message = outcome === "skipped"
      ? "Skip this task and move on without finishing? Your work so far will be saved, and your choice to skip will be recorded. You cannot return to this task."
      : "Mark this task finished and move on? Your work will be saved. You cannot return to this task.";
    if (!window.confirm(message)) return;
    setSending(true);
    try {
      const result = await requestPilotTaskOutcome(task, outcome);
      if (task.position === 2 && openReceiptPage(result.completion_receipt)) return;
      setPendingOutcome(result.outcome || outcome);
      if (task.position === 2) {
        setError("Completion receipt unavailable. Your decision was submitted; do not submit it again.");
      }
      setError(null);
    } catch (err) { setError(err.message); }
    finally { setSending(false); }
  }

  return (
    <div id="taskWindow">
      <div id="task">
        {loading && <p>Loading assigned task...</p>}
        {error && !completed && !pendingOutcome && (
          <p role="alert">Unable to load the assigned task: {error}</p>
        )}
        {completed && (
          <div role="status" className="pilotTransitionStatus">
            <h3>Study Complete</h3>
            <p>Thank you for participating. Your assigned tasks are resolved,
              and your work and task decisions have been saved.</p>
            {finalOutcome === "skipped" && (
              <p>Your decision to skip the final task was recorded.</p>
            )}
            <p>You may now close this browser window.</p>
          </div>
        )}
        {task && pendingOutcome && (
          <div role="status" className="pilotTransitionStatus">
            <h3>{task.position === 2 ? "Finalizing your study" : "Preparing your next step"}</h3>
            <p>Your choice to {pendingOutcome === "skipped" ? "skip" : "finish"} this task
              has been recorded. Your work is being archived.</p>
            {task.position === 2 ? (
              <p>We are recording your final task outcome. A Study Complete
                confirmation will appear when the server verifies finalization.</p>
            ) : (
              <p>The study will automatically load the next task with a fresh CLI
                window. The connection may briefly pause during the transition.</p>
            )}
            {error && (
              <p role="alert">The completion-status check was interrupted: {error}
                Your task choice was already submitted. Do not submit it again;
                if prompted, renew access for the same participant.</p>
            )}
          </div>
        )}
        {task && !pendingOutcome && (
          <>
            <h3>Task {task.position} of 2</h3>
            <div dangerouslySetInnerHTML={{ __html: task.desc }} />
            <hr />
            <p><strong>Current task:</strong> {TASK_NAMES[task.task_code]}</p>
            <p><strong>Working directory:</strong></p>
            <p><code>/home/user/fuzz-study/work</code></p>
            <p>You may use the CLI and internal browser throughout this task.</p>
            <FuzzingQuickStart onOpen={() => setGuideOpen(true)} />
            <div className="pilotFinishControls">
              <div className="pilotOutcomeButtons">
                <button type="button" disabled={sending || !!pendingOutcome}
                  onClick={() => requestOutcome("completed")}>
                  {sending ? "Submitting..." : "Finish Task"}
                </button>
                <button type="button" className="pilotSkipButton"
                  disabled={sending || !!pendingOutcome}
                  onClick={() => requestOutcome("skipped")}>
                  Skip Task
                </button>
              </div>
              <p className="pilotSkipExplanation">
                Choose <strong>Skip Task</strong> if you want to stop working on this task
                before finishing. Your choice will be recorded, and you will move on.
              </p>
            </div>
            <div className="macClipboardNotice" role="note">
              <strong>Mac users:</strong> In the Browser tab, use Control+C and Control+V
              rather than Command+C and Command+V.
            </div>
          </>
        )}
        {task && <FuzzingGuideModal open={guideOpen} onClose={() => setGuideOpen(false)} />}
      </div>
    </div>
  );
}
