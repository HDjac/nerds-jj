import { useEffect, useRef } from "react";
import "./FuzzingGuide.css";
import "./TaskController.css";

/** Participant reference only. No clipboard reads, writes, or telemetry. */
export default function ClipboardGuideModal({ open, onClose }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const previousFocusRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    previousFocusRef.current = document.activeElement;
    closeRef.current?.focus();
    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      } else if (event.key === "Tab") {
        const nodes = dialogRef.current?.querySelectorAll(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (!nodes?.length) return;
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
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return (
    <div className="nerdsGuideBackdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={dialogRef} role="dialog" aria-modal="true"
        aria-labelledby="nerds-copy-paste-title"
        className="nerdsGuideDialog">
        <header className="nerdsGuideDialogHeader">
          <h2 id="nerds-copy-paste-title">Copy and paste inside NERDs</h2>
          <button type="button" ref={closeRef} onClick={onClose}
            aria-label="Close copy and paste guide" className="nerdsGuideClose">
            Close
          </button>
        </header>
        <div className="nerdsGuideBody pilotClipboardModalBody">
          <p>Copy and paste text between the task description, CLI terminal,
            and internal Firefox browser without leaving the NERDs workspace.</p>

          <section>
            <h3>Copy text from the task description</h3>
            <p>Select the text you need in the task description, then click
              <strong> Copy selected text</strong> below it. To copy the entire task,
              click <strong>Copy task description</strong>. Both buttons use the
              internal NERDs clipboard.</p>
            <p>While task-description text is selected, pressing
              <span className="pilotKeyboardShortcut"> Ctrl + C</span> on Windows/Linux
              or <span className="pilotKeyboardShortcut">Command + C</span> on macOS
              also copies it internally.</p>
          </section>

          <section>
            <h3>Use the CLI terminal</h3>
            <p>To copy terminal output, select the text with your mouse.
              To paste inside the terminal, first click the CLI area and use
              <span className="pilotKeyboardShortcut"> Shift + Insert</span> or
              middle-click if your mouse supports it.</p>
            <p><strong>Important:</strong> <span className="pilotKeyboardShortcut">Ctrl + C</span>
              stops a running terminal command. It is not the terminal Copy shortcut.</p>
          </section>

          <section>
            <h3>Use the internal Firefox browser</h3>
            <p>Switch to the <strong>BROWSER</strong> tab and click inside Firefox.
              Use <span className="pilotKeyboardShortcut">Ctrl + C</span> to copy
              selected text and <span className="pilotKeyboardShortcut">Ctrl + V</span>
              to paste it into a text field.</p>
            <p>On macOS, use <span className="pilotKeyboardShortcut">Command + C</span>
              and <span className="pilotKeyboardShortcut">Command + V</span> if
              your workspace maps those keys. If a shortcut does not work,
              focus the destination field and retry.</p>
          </section>

          <section>
            <h3>Moving between the three areas</h3>
            <p>Task description to CLI: copy from the sidebar, switch to CLI,
              then paste into the terminal. CLI to Firefox: select text in the
              terminal, switch to BROWSER, then paste into Firefox. Firefox to
              CLI: copy inside Firefox, switch to CLI, then paste.</p>
          </section>

          <section className="pilotBoundaryNote">
            <h3>Privacy boundary</h3>
            <p>Copy/paste is intended to stay inside NERDs. Copying between
              your personal computer and the NERDs workspace is intentionally
              restricted. Do not enter personal passwords, private credentials,
              or other sensitive information into the study environment.</p>
          </section>
        </div>
        <footer className="nerdsGuideFooter">
          <button type="button" onClick={onClose}>Return to Task</button>
        </footer>
      </section>
    </div>
  );
}
