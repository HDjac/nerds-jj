import { useRef, useEffect, useState } from "react";
import RFB from "@novnc/novnc";
import "./BrowserView.css";
import AudioPlugin from "../lib/novnc-audio";
import { DEV_MODE } from "../util";
import { getNerdsInternalClipboard, getNerdsInternalClipboardSource, getNerdsObservedClipboardText, setNerdsInternalClipboard } from "../internalClipboard";
import { recordClipboardActivity, recordConfirmedExternalPasteBlock } from "../clipboardActivity";

/* Completely disables the VNC session to enable testing without backend */
const NO_VNC = false;

export default function BrowserView(props) {
  const rfbElement = useRef(null);
  const containerElement = useRef(null);
  const rfbObj = useRef(null);

  // Can be null, connecting, connected, disconnected, or failed.
  const [rfbStatus, setRfbStatus] = useState(null);
  const [alerted, setAlerted] = useState(false);
  const audioPlugin = useRef(null);
  const macPasteTimer = useRef(null);
  const browserToCliPasteTimer = useRef(null);
  const pendingMacPaste = useRef(false);
  const browserCopyPending = useRef(false);
  const browserCopyTimer = useRef(null);
  const browserSelectionCandidate = useRef("");

  // The RFB clipboard listener is installed once, when noVNC connects.
  // A render-time ref avoids trapping the *initial* CLI/BROWSER tab inside
  // that listener and misclassifying future CLI selections as Firefox copies.
  const activeTabRef = useRef(props.currentTab);
  activeTabRef.current = props.currentTab;

  const SHOW_DEBUG = DEV_MODE;

  function debug(msg) {
    if (SHOW_DEBUG) {
      console.debug(msg);
    }
  }

  function getInternalClipboard() {
    return getNerdsInternalClipboard();
  }
  function setInternalClipboard(text, source, options) {
    setNerdsInternalClipboard(text, source, options);
  }
  function observedTextCandidate(source, text) {
    // Never record content from a pending Firefox copy or cached fallback.
    if (browserCopyPending.current) return undefined;
    return getNerdsObservedClipboardText(source, text);
  }
  function handleConfirmedHostPaste(event) {
    // A trusted native DOM paste into the VNC view is blocked here. Never
    // inspect event.clipboardData, navigator.clipboard, or host contents.
    // This does NOT detect blocked host pastes invisible to the DOM.
    if (!event.isTrusted || !rfbElement.current ||
        !rfbElement.current.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") {
      event.stopImmediatePropagation();
    }
    recordConfirmedExternalPasteBlock(
      activeTabRef.current === "cli" ? "internal_cli" : "internal_browser",
      "other_internal"
    );
  }
  function syncInternalClipboardToVnc() {
    if (!rfbObj.current) {
      return;
    }

  /*
   * Firefox has copied something, but noVNC has not returned the new
   * clipboard value yet. Do not overwrite it with older editor text.
   */
    if (browserCopyPending.current) {
      console.log(
        "VNC clipboard sync skipped while browser copy is pending"
      );
      return;
    }

    const text = getInternalClipboard();

    rfbObj.current.clipboardPasteFrom(text || "");

    if (text) {
      console.log("NERDS internal clipboard sent to VNC");
    } else {
      console.log(
        "NERDS internal clipboard is empty; VNC clipboard cleared"
      );
    }
  }

  function syncUiClipboardOnVncFocus() {
    // Xterm and Firefox own the actual X11 clipboard after copying. Sending
    // the last React clipboard value on every mouse/focus or tab switch can
    // overwrite a *newer CLI selection* with stale Firefox content.
    // Explicit sidebar/guide Copy actions still need to be sent to VNC.
    const source = getNerdsInternalClipboardSource();
    if (source === "task_sidebar" || source === "fuzzing_guide" ||
        source === "other_internal") {
      syncInternalClipboardToVnc();
    }
  }

  function releaseVncModifiers() {
    const rfb = rfbObj.current;

    if (!rfb) {
      return;
    }

  /*
   * Release all possible remote modifiers. noVNC can translate the
   * macOS Cmd/Super key into Alt, so Alt must also be released.
   */
    const modifiers = [
      0xffe1, // Shift_L
      0xffe2, // Shift_R
      0xffe3, // Control_L
      0xffe4, // Control_R
      0xffe7, // Meta_L
      0xffe8, // Meta_R
      0xffe9, // Alt_L
      0xffea, // Alt_R
      0xffeb, // Super_L
      0xffec  // Super_R
    ];

    rfb.blur();

    modifiers.forEach((keysym) => {
      rfb.sendKey(keysym, null, false);
    });

    rfb.focus();
  }

  function sendVncCtrlShortcut(key) {
    const rfb = rfbObj.current;

    if (!rfb) {
      return;
    }

    const keyInfo = {
      c: { keysym: 0x0063 },
      v: { keysym: 0x0076 },
      x: { keysym: 0x0078 }
    }[key.toLowerCase()];

    if (!keyInfo) {
      return;
    }

    releaseVncModifiers();

    const ctrlKeysym = 0xffe3;

    // Use null codes to send standard VNC keysym events.
    rfb.sendKey(ctrlKeysym, null, true);

    setTimeout(() => {
      rfb.sendKey(keyInfo.keysym, null, true);

      setTimeout(() => {
        rfb.sendKey(keyInfo.keysym, null, false);

        setTimeout(() => {
          rfb.sendKey(ctrlKeysym, null, false);

          // Ensure nothing remains held before the next shortcut.
          releaseVncModifiers();
        }, 20);
      }, 20);
    }, 20);
  }

  function sendVncShiftInsert() {
    const rfb = rfbObj.current;
    if (!rfb) return;

    // CLI uses Shift+Insert rather than Firefox's Ctrl+V. The prior host
    // keydown is stopped, so deliver precisely one remote paste shortcut.
    releaseVncModifiers();
    rfb.sendKey(0xffe1, null, true);  // Shift_L
    rfb.sendKey(0xff63, null, true);  // Insert
    rfb.sendKey(0xff63, null, false);
    rfb.sendKey(0xffe1, null, false);
  }

  function finishMacPaste(reason) {
    if (!pendingMacPaste.current) {
      return;
    }

    pendingMacPaste.current = false;

    if (macPasteTimer.current) {
      clearTimeout(macPasteTimer.current);
      macPasteTimer.current = null;
    }

  /*
   * This sends editor text when it is current. If a browser copy is
   * pending, the sync function deliberately does nothing so the new
   * Firefox clipboard is not overwritten.
   */
    syncInternalClipboardToVnc();

    macPasteTimer.current = setTimeout(() => {
      syncInternalClipboardToVnc();
      sendVncCtrlShortcut("v");

      macPasteTimer.current = null;

      console.log(`Remote Ctrl+V sent after ${reason}`);
    }, 150);
  }

  function handleBrowserKeyUp(e) {
    if (
      props.currentTab !== "browser" ||
      rfbStatus !== "connected" ||
      !pendingMacPaste.current
    ) {
      return;
    }

    const commandReleased =
      e.key === "Meta" ||
      e.code === "MetaLeft" ||
      e.code === "MetaRight" ||
      !e.metaKey;

    if (commandReleased) {
    /*
     * Do not prevent this event. noVNC must receive the keyup so it
     * can release the remote Mac/Alt modifier.
     */
      setTimeout(() => {
        finishMacPaste("Mac Command key release");
      }, 0);
    }
  }

  function clearBrowserCopyPending() {
    browserCopyPending.current = false;

    if (browserCopyTimer.current) {
      clearTimeout(browserCopyTimer.current);
      browserCopyTimer.current = null;
    }
  }

  function beginBrowserCopy() {
    clearBrowserCopyPending();
    browserCopyPending.current = true;

    /*
    * noVNC/Linux may have already sent the selected text before the
    * explicit copy shortcut. Give it a short chance to send another
    * event, then promote the cached selection if it does not.
    */
    browserCopyTimer.current = setTimeout(() => {
      if (!browserCopyPending.current) {
        return;
      }

      const cachedText = browserSelectionCandidate.current;

      clearBrowserCopyPending();

      if (cachedText) {
        setInternalClipboard(
          cachedText,
          "internal_browser"
        );

        console.log(
          "Explicit browser copy used cached selection"
        );
      } else {
        console.log(
          "Browser copy completed without any selected text"
        );
      }
    }, 250);
  }

  function handleBrowserClipboardShortcut(e) {
    // The legacy Monaco study intercepted Ctrl/Cmd+V before the browser could
    // deliver host clipboard contents. In noVNC, a keydown is visible even
    // when the native paste event is not. This records a *blocked host
    // keyboard path*, NOT proof that a user had external text copied.
    // CLI's supported internal paste shortcut is Shift+Insert.
    const inVncView = !!(rfbElement.current &&
      rfbElement.current.contains(e.target));
    const pasteKey = (e.key || "").toLowerCase();
    const isHostPasteKey = pasteKey === "v" && !e.altKey &&
      ((e.ctrlKey && !e.metaKey) || (e.metaKey && !e.ctrlKey));
    if (props.currentTab === "cli" && rfbStatus === "connected" &&
        inVncView && isHostPasteKey) {
      e.preventDefault();
      e.stopPropagation();
      if (typeof e.stopImmediatePropagation === "function") {
        e.stopImmediatePropagation();
      }
      if (!e.repeat) recordClipboardActivity({
        kind: "host_paste_shortcut_blocked", surface: "internal_cli",
        method: e.metaKey ? "meta_shortcut" : "ctrl_shortcut",
        source: "unknown",
      });
      return;
    }
    // Passive CLI keyboard observation only for Shift+Insert.

    // A Shift+Insert request does not prove that the terminal inserted text.
    if (props.currentTab === "cli" && rfbStatus === "connected" &&
        !e.repeat && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey &&
        (e.key === "Insert" || e.code === "Numpad0") &&
        rfbElement.current?.contains(e.target)) {
      const source = getNerdsInternalClipboardSource();
      const clipboardText = getNerdsInternalClipboard();
      recordClipboardActivity({
        kind: "paste_requested", surface: "internal_cli", method: "shift_insert",
        source, text: observedTextCandidate(source, clipboardText),
      });

      // Explicit Firefox Ctrl+V already pushes its clipboard back through
      // noVNC; CLI Shift+Insert did not. The X11 clipboard may still hold a
      // previous selection, so synchronize *only* when Firefox originated
      // this clipboard value, then send the remote paste after propagation.
      // Do not alter native CLI->CLI, sidebar, or Guide paste behavior.
      if (source === "internal_browser") {
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") {
          e.stopImmediatePropagation();
        }
        if (browserToCliPasteTimer.current) {
          clearTimeout(browserToCliPasteTimer.current);
          browserToCliPasteTimer.current = null;
        }
        if (browserCopyPending.current || !clipboardText || !rfbObj.current) {
          // Never inject the *previous* Firefox value while a new copy is
          // pending. A subsequent Shift+Insert can retry after the copy.
          console.warn("NERDs Firefox clipboard not ready for CLI paste");
          return;
        }
        rfbObj.current.clipboardPasteFrom(clipboardText);
        browserToCliPasteTimer.current = setTimeout(() => {
          browserToCliPasteTimer.current = null;
          if (activeTabRef.current === "cli" && rfbObj.current) {
            sendVncShiftInsert();
          }
        }, 180);
        return;
      }
    }
    if (
      props.currentTab !== "browser" ||
      rfbStatus !== "connected"
    ) {
      return;
    }

    const key = (e.key || "").toLowerCase();
    // Sidebar copy uses a separate internal-only clipboard path.
    // Do not hijack Ctrl/Cmd+C when the participant selected task text.
    const selection = window.getSelection();
    const taskArea = document.getElementById("taskWindow");
    const copyingSidebarText = (key === "c" || key === "x") &&
      taskArea && selection && !selection.isCollapsed &&
      taskArea.contains(selection.anchorNode) &&
      taskArea.contains(selection.focusNode);
    if (copyingSidebarText || e.target?.closest?.("#taskWindow")) return;


    const isClipboardShortcut =
      (e.ctrlKey || e.metaKey) &&
      !e.altKey &&
      (key === "c" || key === "x" || key === "v");

    if (!isClipboardShortcut) {
      return;
    }

  /*
   * Prevent the host browser and noVNC from independently processing
   * the original clipboard shortcut.
   */
    e.preventDefault();
    e.stopPropagation();

    if (typeof e.stopImmediatePropagation === "function") {
      e.stopImmediatePropagation();
    }

    // The host's native browser clipboard shortcut was prevented above.
    // Internal Firefox paste may still proceed through the separate VNC path.
    // Only label the blocked host *path*, never the clipboard's origin.
    if (key === "v" && !e.repeat && inVncView) {
      recordClipboardActivity({
        kind: "host_paste_shortcut_blocked", surface: "internal_browser",
        method: e.metaKey ? "meta_shortcut" : "ctrl_shortcut",
        source: "unknown",
      });
    }

  /*
   * Mac Cmd+V: record the paste request but do not send Ctrl+V until
   * the physical Command key has been released.
   */
    if (key === "v" && e.metaKey && !e.ctrlKey) {
      if (
        e.repeat ||
        pendingMacPaste.current ||
        macPasteTimer.current
      ) {
        console.log(
          "Mac paste already pending; extra Cmd+V ignored"
        );

        return;
      }

      recordClipboardActivity({
        kind: "paste_requested", surface: "internal_browser",
        method: "meta_shortcut", source: getNerdsInternalClipboardSource(),
        text: observedTextCandidate(getNerdsInternalClipboardSource(), getNerdsInternalClipboard()),
      });
      syncInternalClipboardToVnc();
      pendingMacPaste.current = true;

    /*
     * Normally handleBrowserKeyUp completes the paste. This fallback
     * handles the unusual case where the browser loses the keyup event.
     */
      macPasteTimer.current = setTimeout(() => {
        finishMacPaste("keyup fallback");
      }, 2000);

      console.log(
        "Mac Cmd+V detected; waiting for Command key release"
      );

      return;
    }

  /*
   * Preserve the working Ctrl+V behavior.
   */
    if (key === "v" && e.ctrlKey && !e.metaKey) {
      if (!e.repeat) recordClipboardActivity({
        kind: "paste_requested", surface: "internal_browser",
        method: "ctrl_shortcut", source: getNerdsInternalClipboardSource(),
        text: observedTextCandidate(getNerdsInternalClipboardSource(), getNerdsInternalClipboard()),
      });
      syncInternalClipboardToVnc();

      setTimeout(() => {
        syncInternalClipboardToVnc();
        sendVncCtrlShortcut("v");
      }, 150);

      console.log("Ctrl+V queued as remote Ctrl+V");
      return;
    }

  /*
   * Mark browser copy as pending before sending remote Ctrl+C. This
   * prevents mouse clicks or paste attempts from replacing the new
   * Firefox clipboard with older editor text.
   */
    if (key === "c") {
      if (!e.repeat) recordClipboardActivity({
        kind: "copy_requested", surface: "internal_browser",
        method: e.metaKey ? "meta_shortcut" : "ctrl_shortcut",
        source: "internal_browser",
      });
      beginBrowserCopy();
      sendVncCtrlShortcut("c");

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+C sent; ` +
        "waiting for browser clipboard"
      );

      return;
    }

    if (key === "x") {
      if (!e.repeat) recordClipboardActivity({
        kind: "copy_requested", surface: "internal_browser",
        method: e.metaKey ? "meta_shortcut" : "ctrl_shortcut",
        source: "internal_browser",
      });
      beginBrowserCopy();
      sendVncCtrlShortcut("x");

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+X sent; ` +
        "waiting for browser clipboard"
      );
    }
  }

  // Initialize the audio plugin.
  if (!audioPlugin.current) {
    audioPlugin.current = new AudioPlugin();
    audioPlugin.current.initUi();
  }

  function startAudio() {
    if (audioPlugin.current) {
      debug("Starting audio stream");
      audioPlugin.current.startAudio();
    }
  }

  function stopAudio() {
    if (audioPlugin.current) {
      debug("Stopping audio stream");
      audioPlugin.current.stopAudio();
      audioPlugin.current.removeUi();
    }
  }

  function connect() {
    if (
      rfbStatus === "connected" ||
      rfbStatus === "connecting"
    ) {
      return;
    }

    setRfbStatus("connecting");

    let vncURL =
      `wss://${window.location.host}` +
      `${window.location.pathname}?token=vnc`;

    if (DEV_MODE) {
      vncURL = "ws://192.168.1.35:82?token=vnc";
    }

    const rfb = new RFB(rfbElement.current, vncURL);

    // rfb.scaleViewport = true;
    rfb.resizeSession = true;
    rfb.background = "#494949";

    rfb.addEventListener("connect", handleConnect);
    rfb.addEventListener("disconnect", handleDisconnect);
    rfb.addEventListener("clipboard", handleClipboard);

    rfbObj.current = rfb;
  }

  function handleConnect() {
    debug("Connected to browser instance");

    setRfbStatus("connected");
    setAlerted(false);
    startAudio();

    // Only locally copied UI text needs a VNC update at connect time.
    setTimeout(() => {
      syncUiClipboardOnVncFocus();
    }, 250);
  }

  function handleDisconnect(stat) {
    debug("Handled disconnect");
    stopAudio();

    if (!stat.detail.clean) {
      debug("Unclean disconnect");
      setRfbStatus("failed");
    } else {
      debug("Clean disconnect");
      setRfbStatus("disconnected");
    }
  }

  function handleClipboard(stat) {
    debug("Got clipboard event"); // Never log stat.detail: contains clipboard text.

    if (!stat.detail || !stat.detail.text) {
      return;
    }

    const text = stat.detail.text;

    // CLI terminal clipboard:
    // Save text received from xterm as internal clipboard content.
    if (activeTabRef.current === "cli") {
      // A new xterm selection updates both bytes and provenance. If the
      // same bytes were previously copied in Firefox, the source changes.
      if (text !== getInternalClipboard() ||
          getNerdsInternalClipboardSource() !== "internal_cli") {
        setInternalClipboard(text, "internal_cli", { observedFromVnc: true });
      }

      console.log("CLI clipboard received by NERDs");
      return;
    }

    // Preserve existing Firefox clipboard behavior.
    browserSelectionCandidate.current = text;

    if (!browserCopyPending.current) {
      console.log(
        "Browser selection cached but not copied"
      );
      return;
    }

    clearBrowserCopyPending();

    setInternalClipboard(
      text,
      "internal_browser",
      { observedFromVnc: true }
    );

   console.log(
      "Explicit browser copy saved to NERDs clipboard"
    );
  }

  // Create the initial VNC connection.
  useEffect(() => {
    if (NO_VNC) {
      return undefined;
    }

    connect();

    return () => {
      if (rfbObj.current) {
        rfbObj.current.disconnect();
      }

      debug("Disconnected RFB object on unmount");
    };
  }, []);

  function doResize() {
    if (!containerElement.current || !rfbElement.current) {
      return;
    }

    const width = Math.round(
      containerElement.current.offsetWidth
    );

    if (width !== 0) {
      debug(`Setting width to ${width}px`);
      rfbElement.current.style.width = `${width}px`;
    }
  }

  // Resize when the Browser tab becomes visible.
  useEffect(() => {
    if (
      props.currentTab === "browser" &&
      containerElement.current
    ) {
      doResize();
    }
  }, [props.currentTab]);

  // Resize when the outer browser container changes size.
  useEffect(() => {
    const observer = new ResizeObserver(doResize);
    const container = containerElement.current;

    if (container) {
      observer.observe(container);
    }

    return () => {
      if (container) {
        observer.unobserve(container);
      }

      observer.disconnect();
    };
  }, []);

  // Do not overwrite a fresh X11 CLI selection on a tab switch.
  // Only explicit sidebar/guide copies need to be pushed to noVNC.
  useEffect(() => {
    if (props.currentTab === "browser" && rfbStatus === "connected") {
      syncUiClipboardOnVncFocus();
    }
  }, [props.currentTab, rfbStatus]);

  /*
   * Receive clipboard updates from CodeEditor. This lets copied editor
   * text reach the VNC clipboard before the user presses Cmd+V.
   */
  useEffect(() => {
    function handleInternalClipboardEvent(event) {
      // The CLI clipboard already originated inside VNC.
      // Do not immediately send it back to VNC.
      if (event.detail?.source === "internal_cli") {
        return;
      }
      /*
      * A newer editor copy replaces any earlier pending browser copy.
      */
      if (event.detail?.source === "code_editor") {
        clearBrowserCopyPending();
        browserSelectionCandidate.current = "";
      }

      if (rfbStatus === "connected") {
        syncInternalClipboardToVnc();
      }
    }

    window.addEventListener(
      "nerds-internal-clipboard",
      handleInternalClipboardEvent
    );

    return () => {
      window.removeEventListener(
        "nerds-internal-clipboard",
        handleInternalClipboardEvent
      );
    };
  }, [rfbStatus]);

  // Attempt to reconnect when the local device returns online.
  useEffect(() => {
    function handleOnline() {
      connect();
    }

    window.addEventListener("online", handleOnline);

    return () => {
      window.removeEventListener("online", handleOnline);
    };
  }, [rfbStatus]);

  /*
   * Register the shortcut handler only once on window for each relevant
   * state change. Do not also register it on rfbElement, because that can
   * cause the same shortcut to be processed twice.
   */
  useEffect(() => {
    window.addEventListener(
      "keydown",
      handleBrowserClipboardShortcut,
      true
    );

    window.addEventListener(
      "keyup",
      handleBrowserKeyUp,
      true
    );

    return () => {
      window.removeEventListener(
        "keydown",
        handleBrowserClipboardShortcut,
        true
      );

      window.removeEventListener(
        "keyup",
        handleBrowserKeyUp,
        true
      );

      if (macPasteTimer.current) {
        clearTimeout(macPasteTimer.current);
        macPasteTimer.current = null;
      }

      if (browserToCliPasteTimer.current) {
        clearTimeout(browserToCliPasteTimer.current);
        browserToCliPasteTimer.current = null;
      }

      if (browserCopyTimer.current) {
        clearTimeout(browserCopyTimer.current);
        browserCopyTimer.current = null;
      }

      pendingMacPaste.current = false;
      browserCopyPending.current = false;
    };
  }, [props.currentTab, rfbStatus]);

  // Report connection changes and attempt reconnects.
  useEffect(() => {
    debug(`New RFB state: ${rfbStatus}`);
    props.setConnStatus(rfbStatus === "connected");

    if (rfbStatus === "disconnected") {
      debug("Trying to reconnect to RFB");
      connect();
    } else if (rfbStatus === "failed" && !alerted) {
      setAlerted(true);

      alert(
        "You have been disconnected from the study infrastructure. " +
        "Please check your internet connection and reconnect. " +
        "If you believe this is an error, please contact the study " +
        "administrators."
      );
    }
  }, [rfbStatus, alerted]);

  return (
    <div
      className="browserContainer"
      ref={containerElement}
    >
      <div
        className="viewContainer"
        ref={rfbElement}
        tabIndex={0}
        onMouseDown={syncUiClipboardOnVncFocus}
        onFocus={syncUiClipboardOnVncFocus}
        onPasteCapture={handleConfirmedHostPaste}
      >
      </div>
    </div>
  );
}