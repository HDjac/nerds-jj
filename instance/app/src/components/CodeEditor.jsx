import { useState, useEffect } from 'react';
import OutputBox from "./OutputBox";
import WasmRunner from "./WasmRunner";
import { isUndefined } from "../util";
import "./CodeEditor.css";

import Editor from "@monaco-editor/react";

export default function CodeEditor(props) {
  const [output, setOutput] = props.output;
  const taskno = props.taskno;
  const editorValue = props.editor_value;
  const setEditorValueBackend = props.set_editor_value;

  const [loadedArr, setLoadedArr] = useState([]);
  const loaded = isUndefined(loadedArr[taskno]) ? false : loadedArr[taskno];
  const setLoaded = (v) => setLoadedArr(loadedArr => {
    loadedArr[props.taskno] = v;
    return loadedArr;
  });

  if (props.taskno == undefined) {
    console.error("real_taskno is undefined");
  }

  function handleEditorDidMount(editor, monaco) {
    console.debug("handleEditorDidMount");
    props.editorRef.current = editor;

    let internalClipboard = "";

    function getAllowedText() {
      return (
        window.__NERDS_INTERNAL_CLIPBOARD__ ||
        localStorage.getItem("NERDS_INTERNAL_CLIPBOARD") ||
        internalClipboard ||
        ""
      );
    }

    function setInternalClipboard(text, source) {
      if (!text || text.length === 0) {
        return;
      }

      internalClipboard = text;
      window.__NERDS_INTERNAL_CLIPBOARD__ = text;
      localStorage.setItem("NERDS_INTERNAL_CLIPBOARD", text);
      localStorage.setItem("NERDS_INTERNAL_CLIPBOARD_SOURCE", source);
      localStorage.setItem("NERDS_INTERNAL_CLIPBOARD_TS", String(Date.now()));

      window.dispatchEvent(
        new CustomEvent("nerds-internal-clipboard", {
          detail: { text, source }
        })
      );
    }

    function logEvent(event_type, blocked, extra = {}) {
      props.submit("x", {
        event_type,
        source: "monaco_editor",
        blocked,
        timestamp: Date.now(),
        platform: navigator.platform,
        user_agent: navigator.userAgent,
        ...extra
      });
    }

    function getSelectedText() {
      const selection = editor.getSelection();
      const model = editor.getModel();

      if (!selection || !model) {
        return "";
      }

      return model.getValueInRange(selection);
    }

    function saveSelectionToInternal(action, source) {
      const selection = editor.getSelection();
      const model = editor.getModel();

      if (!selection || !model) {
        return false;
      }

      const selectedText = model.getValueInRange(selection);

      if (!selectedText || selectedText.length === 0) {
        return false;
      }

      setInternalClipboard(selectedText, "code_editor");

      logEvent(
        action === "cut" ? "internal_code_cut" : "internal_code_copy",
        false,
        { source }
      );

      console.log(`Internal code ${action} saved from ${source}`);

      if (action === "cut") {
        editor.executeEdits("internal-cut", [
          {
            range: selection,
            text: ""
          }
        ]);
      }

      return true;
    }

    function pasteTextIntoEditor(text, source) {
      if (!text || text.length === 0) {
        return false;
      }

      const selection = editor.getSelection();

      editor.executeEdits("internal-paste", [
        {
          range: selection,
          text
        }
      ]);

      logEvent("internal_paste_allowed", false, {
        source
      });

      console.log(`Internal paste allowed from ${source}`);
      return true;
    }

    const editorDomNode = editor.getDomNode();

    if (editorDomNode) {
      editorDomNode.addEventListener(
        "copy",
        (e) => {
          e.preventDefault();
          e.stopPropagation();

          saveSelectionToInternal("copy", "dom_copy");
        },
        true
      );

      editorDomNode.addEventListener(
        "cut",
        (e) => {
          e.preventDefault();
          e.stopPropagation();

          saveSelectionToInternal("cut", "dom_cut");
        },
        true
      );

      editorDomNode.addEventListener(
        "paste",
        (e) => {
          e.preventDefault();
          e.stopPropagation();

          const pastedText = e.clipboardData
            ? e.clipboardData.getData("text/plain")
            : "";

          const allowedText = getAllowedText();

          if (allowedText && pastedText === allowedText) {
            pasteTextIntoEditor(allowedText, "dom_internal_clipboard");
            return;
          }

          logEvent("external_dom_paste_blocked", true, {
            source: "monaco_dom"
          });

          console.log("External DOM paste blocked");
        },
        true
      );
    }

    // Handles Ctrl+C/Ctrl+X/Ctrl+V and Cmd+C/Cmd+X/Cmd+V.
    // We do not use navigator.clipboard here because that would touch the user's real clipboard.
    editor.onKeyDown((e) => {
      const browserEvent = e.browserEvent;

      if (!browserEvent) {
        return;
      }

      const key = (browserEvent.key || "").toLowerCase();
      const isClipboardShortcut =
        (browserEvent.ctrlKey || browserEvent.metaKey) &&
        !browserEvent.altKey &&
        (key === "c" || key === "x" || key === "v");

      if (!isClipboardShortcut) {
        return;
      }

      browserEvent.preventDefault();
      browserEvent.stopPropagation();

      if (typeof browserEvent.stopImmediatePropagation === "function") {
        browserEvent.stopImmediatePropagation();
      }

      e.preventDefault();

      if (key === "c") {
        saveSelectionToInternal("copy", browserEvent.metaKey ? "cmd_c" : "ctrl_c");
        return;
      }

      if (key === "x") {
        saveSelectionToInternal("cut", browserEvent.metaKey ? "cmd_x" : "ctrl_x");
        return;
      }

      if (key === "v") {
        const allowedText = getAllowedText();

        if (allowedText) {
          pasteTextIntoEditor(
            allowedText,
            browserEvent.metaKey ? "cmd_v_internal_clipboard" : "ctrl_v_internal_clipboard"
          );
          return;
        }

        logEvent("external_keyboard_paste_blocked", true, {
          source: browserEvent.metaKey ? "cmd_v" : "ctrl_v"
        });

        console.log("External keyboard paste blocked");
      }
    });

    // Backup protection: if a native paste somehow gets through Monaco,
    // immediately undo it.
    editor.onDidPaste(() => {
      logEvent("external_paste_undone", true, {
        source: "monaco_onDidPaste_backup"
      });

      console.log("Unexpected paste detected and undone");
      editor.trigger("keyboard", "undo", null);
    });
  }

  function handleBeforeUnload(e) {
    e.preventDefault();
  }

  function handleKeyDown(e) {
    if (e.key === "Tab") {
      e.preventDefault();
    }
  }

  function handleEditorDidChange(value, e) {
    console.debug(`Handling editor did change on task ${props.taskno}`);
    setEditorValueBackend(value);
  }

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("beforeunload", handleBeforeUnload);

    return (() => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    });
  });

  return (
    <div id="editorContainer">
      <div id="controlsBox">
        <WasmRunner
          editor={props.editorRef}
          output={output}
          setOutput={setOutput}
          compile_code={props.compile_code}
          taskno={props.taskno}
        />
      </div>
      <Editor
        language={"c"}
        options={{ domReadOnly: false, readOnly: false }}
        path={`task${props.taskno}`}
        defaultValue={editorValue}
        theme="vs-dark"
        onMount={handleEditorDidMount}
        onChange={handleEditorDidChange}
        wrapperProps={{ "style": { "flex": "2 1 400px", "minHeight": "200px", "padding": "0.5em" } }}
        keepCurrentModel={true}
        className="editorBox"
      />
      <OutputBox output={output} />
    </div>
  );
}