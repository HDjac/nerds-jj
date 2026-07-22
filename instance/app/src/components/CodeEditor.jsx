import { useState, useEffect } from 'react';
import OutputBox from "./OutputBox";
import WasmRunner from "./WasmRunner";
import ControlButton from "./ControlButton";
import useTaskState from "../hooks/useTaskState";
import useSavedState from "../hooks/useSavedState";
import {isUndefined} from "../util";
import "./CodeEditor.css";

import Editor from "@monaco-editor/react";

export default function CodeEditor(props) {
  // state that we have from props:
  // suggestions  <array>     snippet suggestions
  // real_taskno  <int>       task number in the original ordering
  // output       <string>    the code output
  // editorRef    <ref>       Reference to the editor instance
  const [output, setOutput] = props.output;
  const taskno = props.taskno
  const editorValue = props.editor_value;
  const setEditorValueBackend = props.set_editor_value;

  /* Used to store if we've loaded the saved state into the monaco model */
  const [loadedArr, setLoadedArr] = useState([]);
  const loaded = isUndefined(loadedArr[taskno]) ? false : loadedArr[taskno];
  const setLoaded = (v) => setLoadedArr(loadedArr => {
    loadedArr[props.taskno] = v;
    return loadedArr;
  });

  if (props.taskno == undefined) {
    console.error("real_taskno is undefined");
  }

//monaco editor changes to prevent copy and paste from external browser but internal is allowed

function handleEditorDidMount(editor, monaco) {
  console.debug("handleEditorDidMount");
  props.editorRef.current = editor;

  let internalClipboard = "";
  let allowNextPaste = false;

  function getAllowedText() {
    return (
      window.__NERDS_INTERNAL_CLIPBOARD__ ||
      localStorage.getItem("NERDS_INTERNAL_CLIPBOARD") ||
      internalClipboard ||
      ""
    );
  }

  function setInternalClipboard(text, source) {
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

  // Catch DOM/browser paste paths, including Mac Cmd+V, right-click paste, and Edit → Paste.
  const editorDomNode = editor.getDomNode();

  if (editorDomNode) {
    editorDomNode.addEventListener(
      "paste",
      (e) => {
        const pastedText = e.clipboardData.getData("text/plain");
        const allowedText = getAllowedText();

        if (pastedText && pastedText === allowedText) {
          console.log("DOM internal paste allowed");
          allowNextPaste = true;
          return;
        }

        e.preventDefault();
        e.stopPropagation();

        logEvent("external_dom_paste_blocked", true, {
          source: "monaco_dom"
        });

        console.log("External DOM paste blocked");
      },
      true
    );
  }

  // Copy from code editor marks clipboard as internal.
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyC, () => {
    const selection = editor.getSelection();
    const selectedText = editor.getModel().getValueInRange(selection);

    setInternalClipboard(selectedText, "code_editor");

    logEvent("internal_code_copy", false);
    console.log("Internal code copy saved");
  });

    // Cut from code editor marks clipboard as internal.
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyX, () => {
    const selection = editor.getSelection();
    const selectedText = editor.getModel().getValueInRange(selection);

    setInternalClipboard(selectedText, "code_editor");

    editor.executeEdits("cut", [
      {
        range: selection,
        text: ""
      }
    ]);

    logEvent("internal_code_cut", false);
    console.log("Internal code cut saved");
  });

    // Keyboard paste: Ctrl+V on Windows/Linux, Cmd+V on Mac.
  editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyV, async () => {
    const allowedText = getAllowedText();

    if (allowedText) {
      allowNextPaste = true;

      const selection = editor.getSelection();

      editor.executeEdits("internal-paste", [
        {
          range: selection,
          text: allowedText
        }
      ]);

      logEvent("internal_paste_allowed", false, {
        source: "nerds_internal_clipboard"
      });

      console.log("Internal paste allowed from NERDS clipboard");
      return;
    }

    logEvent("external_keyboard_paste_blocked", true);
    console.log("External keyboard paste blocked");
  });

  // Final backup: if anything still pastes, undo it unless it was internal.
  editor.onDidPaste(async () => {
    if (allowNextPaste) {
      allowNextPaste = false;
      console.log("Allowed internal paste was not undone");
      return;
    }

    let clipText = "";

    try {
      clipText = await navigator.clipboard.readText();
    } catch (err) {
      console.log("Could not read clipboard after paste", err);
    }

    const allowedText = getAllowedText();

    if (clipText && clipText === allowedText) {
      console.log("Internal paste allowed by onDidPaste");
      return;
    }

    logEvent("external_paste_undone", true);

    console.log("External paste undone");
    editor.trigger("keyboard", "undo", null);
  });
}

  function handleBeforeUnload(e) {
    e.preventDefault();
  }
  

  function handleKeyDown(e) {
    if (e.key === "Tab") {
      //if (e.shiftKey) {
      //  handlePrev();
      //} else {
      //  handleNext();
      //}
      e.preventDefault();
    }
  }

  function handleEditorDidChange(value, e) {
    console.debug(`Handling editor did change on task ${props.taskno}`);
    setEditorValueBackend(value);
  }

  // Setup listeners
  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("beforeunload", handleBeforeUnload);

    return (() => {
      window.removeEventListener("keydown", handleKeyDown)
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
          taskno={props.taskno} />
      </div>
      <Editor
        language={"c"}
        options={{domReadOnly: false, readOnly: false}}
        path={`task${props.taskno}`}
        defaultValue={editorValue}
        theme="vs-dark"
        onMount={handleEditorDidMount}
        onChange={handleEditorDidChange}
        wrapperProps={{"style":{"flex":"2 1 400px", "minHeight":"200px", "padding": "0.5em"}}}
        keepCurrentModel={true}
        className="editorBox" />
      <OutputBox output={output}/>
    </div>
  )
}
