import { useEffect, useRef } from "react";
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

export function FuzzingQuickStart({ onOpen }) {
  return (
    <section className="nerdsQuickStart" aria-labelledby="nerds-quick-start-heading">
      <div className="nerdsQuickStartHeading">
        <h4 id="nerds-quick-start-heading">Fuzzing Quick Start</h4>
        <button type="button" onClick={onOpen} className="nerdsGuideOpen">
          View Fuzzing Guide
        </button>
      </div>
      <ol>
        {QUICK_STEPS.map(([action, command]) => (
          <li key={action}>
            <strong>{action}</strong>
            <code>{command}</code>
          </li>
        ))}
      </ol>
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
          {guide.sections.map((section) => (
            <section key={section.heading}>
              <h3>{section.heading}</h3>
              <p>{section.summary}</p>
              <ol>
                {section.steps.map((step) => (
                  <li key={step.action}>
                    <strong>{step.action}</strong>
                    <code>{step.command}</code>
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
