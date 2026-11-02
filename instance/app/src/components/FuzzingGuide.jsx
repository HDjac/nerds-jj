import { useEffect, useRef, useState } from "react";
import { setNerdsInternalClipboard } from "../internalClipboard";
import guide from "../data/fuzzingGuideData.json";
import "./FuzzingGuide.css";

const QUICK_STEPS = [
  ["Open task files", "cd ~/fuzz-study/work"],
  ["Compile", "make CC=/usr/bin/clang-19"],
  ["Save inputs", "mkdir -p ../runs/corpus-a"],
  ["Start", "./fuzz_a ../runs/corpus-a -max_total_time=120"],
  ["Stop", "Ctrl+C"],
  ["Continue", "./fuzz_a ../runs/corpus-a -max_total_time=120"],
];

/** Only a running CLI command is copyable. Ctrl+C is a keystroke, not text to paste. */
function isStopShortcut(command) {
  return command.replace(/\s/g, "").toLowerCase() === "ctrl+c";
}

/** Shares the existing internal noVNC clipboard; never accesses the host clipboard. */
function useGuideCommandCopy() {
  const [copiedId, setCopiedId] = useState(null);
  const [notice, setNotice] = useState("");

  function copy(commandId, command) {
    if (isStopShortcut(command)) return;
    if (!setNerdsInternalClipboard(command, "fuzzing_guide_command")) {
      setNotice("Unable to copy command. Please type it in the CLI.");
      return;
    }
    setCopiedId(commandId);
    setNotice("Command copied inside NERDs. Switch to CLI and paste with Shift + Insert.");
  }

  return { copiedId, notice, copy, reset: () => { setCopiedId(null); setNotice(""); } };
}

function GuideCommand({ command, commandId, copiedId, onCopy }) {
  if (isStopShortcut(command)) {
    return (
      <div className="nerdsGuideShortcutRow">
        <span className="nerdsGuideShortcut">Ctrl + C</span>
        <span>Press these keys in the CLI to stop a running command. Do not paste them.</span>
      </div>
    );
  }

  return (
    <div className="nerdsGuideCommandRow">
      <code>{command}</code>
      <button type="button" className="nerdsGuideCopyCommand"
        aria-label={`Copy command into NERDs internal clipboard: ${command}`}
        onClick={() => onCopy(commandId, command)}>
        {copiedId === commandId ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function FuzzingQuickStart({ onOpen, showGuideButton = true }) {
  const clipboard = useGuideCommandCopy();

  return (
    <section className="nerdsQuickStart" aria-labelledby="nerds-quick-start-heading">
      <div className="nerdsQuickStartHeading">
        <h4 id="nerds-quick-start-heading">Fuzzing Quick Start</h4>
        {showGuideButton && (
          <button type="button" onClick={onOpen} className="nerdsGuideOpen">
            View Fuzzing Guide
          </button>
        )}
      </div>
      <p className="nerdsGuideCopyHelp">
        Click <strong>Copy</strong> beside a command, switch to the CLI tab,
        and paste using <strong>Shift + Insert</strong>. Copy does not run the command.
      </p>
      <ol>
        {QUICK_STEPS.map(([action, command], index) => (
          <li key={`${action}-${index}`}>
            <strong>{action}</strong>
            <GuideCommand command={command} commandId={`quick-${index}`}
              copiedId={clipboard.copiedId} onCopy={clipboard.copy} />
          </li>
        ))}
      </ol>
      <p className="nerdsGuideCopyStatus" role="status" aria-live="polite">{clipboard.notice}</p>
      <p className="nerdsGuideHelp">
        The example uses fuzz_a. Choose the harness relevant to your task.
        Keep the same corpus directory when continuing a run.
      </p>
    </section>
  );
}

export function FuzzingGuideModal({ open, onClose }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const previousFocus = useRef(null);
  const onCloseRef = useRef(onClose);
  const clipboard = useGuideCommandCopy();
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    previousFocus.current = document.activeElement;
    closeRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      } else if (event.key === "Tab") {
        const nodes = dialogRef.current?.querySelectorAll(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (!nodes || nodes.length === 0) return;
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus.current?.focus?.();
    };
  }, [open]);

  // Reset the guide's success label when reopening, without clearing the clipboard itself.
  useEffect(() => {
    if (!open) clipboard.reset();
  }, [open]);

  if (!open) return null;
  return (
    <div className="nerdsGuideBackdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={dialogRef} role="dialog" aria-modal="true"
        aria-labelledby="nerds-fuzzing-guide-title" className="nerdsGuideDialog">
        <header className="nerdsGuideDialogHeader">
          <h2 id="nerds-fuzzing-guide-title">{guide.title}</h2>
          <button ref={closeRef} type="button" onClick={onClose}
            aria-label="Close fuzzing guide" className="nerdsGuideClose">Close ×</button>
        </header>
        <div className="nerdsGuideBody">
          <p>{guide.intro}</p>
          <p className="nerdsGuideCopyHelp">To use a listed command, click its
            <strong> Copy</strong> button, return to CLI, and paste using
            <strong> Shift + Insert</strong>.</p>
          <p className="nerdsGuideCopyStatus" role="status" aria-live="polite">{clipboard.notice}</p>
          {guide.sections.map((section, sectionIndex) => (
            <section key={section.heading}>
              <h3>{section.heading}</h3>
              <p>{section.summary}</p>
              <ol>
                {section.steps.map((step, stepIndex) => (
                  <li key={`${step.action}-${stepIndex}`}>
                    <strong>{step.action}</strong>
                    <GuideCommand command={step.command}
                      commandId={`modal-${sectionIndex}-${stepIndex}`}
                      copiedId={clipboard.copiedId} onCopy={clipboard.copy} />
                    <p>{step.detail}</p>
                  </li>
                ))}
              </ol>
            </section>
          ))}
          <section>
            <h3>Key terms</h3>
            <dl>
              {guide.terms.map(({ term, definition }) => (
                <div key={term}><dt>{term}</dt><dd>{definition}</dd></div>
              ))}
            </dl>
          </section>
          <section>
            <h3>During the study</h3>
            <ul>{guide.notes.map((note) => <li key={note}>{note}</li>)}</ul>
          </section>
        </div>
        <footer className="nerdsGuideFooter">
          <button type="button" onClick={onClose}>Return to Task</button>
        </footer>
      </section>
    </div>
  );
}
