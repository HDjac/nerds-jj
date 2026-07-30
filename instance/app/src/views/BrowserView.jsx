import { useRef, useEffect, useState } from "react";
import RFB from "@novnc/novnc";
import "./BrowserView.css";
import AudioPlugin from "../lib/novnc-audio";
import { DEV_MODE } from "../util";

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
  const pendingMacPaste = useRef(false);
  const browserCopyPending = useRef(false);
  const browserCopyTimer = useRef(null);
  const browserSelectionCandidate = useRef("");

  const SHOW_DEBUG = DEV_MODE;

  function debug(msg) {
    if (SHOW_DEBUG) {
      console.debug(msg);
    }
  }

  function getInternalClipboard() {
    return (
      window.__NERDS_INTERNAL_CLIPBOARD__ ||
      localStorage.getItem("NERDS_INTERNAL_CLIPBOARD") ||
      ""
    );
  }

  function setInternalClipboard(text, source) {
    if (!text || text.length === 0) {
      return;
    }

    window.__NERDS_INTERNAL_CLIPBOARD__ = text;
    localStorage.setItem("NERDS_INTERNAL_CLIPBOARD", text);
    localStorage.setItem("NERDS_INTERNAL_CLIPBOARD_SOURCE", source);
    localStorage.setItem(
      "NERDS_INTERNAL_CLIPBOARD_TS",
      String(Date.now())
    );

    window.dispatchEvent(
      new CustomEvent("nerds-internal-clipboard", {
        detail: { text, source }
      })
    );

    console.log(
      `NERDS internal clipboard saved from ${source}:`,
      text
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
    if (
      props.currentTab !== "browser" ||
      rfbStatus !== "connected"
    ) {
      return;
    }

    const key = (e.key || "").toLowerCase();

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
      beginBrowserCopy();
      sendVncCtrlShortcut("c");

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+C sent; ` +
        "waiting for browser clipboard"
      );

      return;
    }

    if (key === "x") {
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

    // Synchronize any editor text that was copied before connecting.
    setTimeout(() => {
      syncInternalClipboardToVnc();
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
    debug("Got clipboard event");
    debug(stat.detail);

    if (!stat.detail || !stat.detail.text) {
      return;
    }

    const text = stat.detail.text;

    /*
    * Always remember the latest Linux selection, but do not immediately
    * make it the NERDS clipboard unless Copy/Cut was explicitly used.
    */
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
      "internal_browser"
    );

    console.log(
      "Explicit browser copy saved to NERDS clipboard"
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

  // Synchronize the internal clipboard when switching to Browser.
  useEffect(() => {
    if (
      props.currentTab === "browser" &&
      rfbStatus === "connected"
    ) {
      syncInternalClipboardToVnc();
    }
  }, [props.currentTab, rfbStatus]);

  /*
   * Receive clipboard updates from CodeEditor. This lets copied editor
   * text reach the VNC clipboard before the user presses Cmd+V.
   */
  useEffect(() => {
    function handleInternalClipboardEvent(event) {
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
        onMouseDown={syncInternalClipboardToVnc}
        onFocus={syncInternalClipboardToVnc}
      >
      </div>
    </div>
  );
}