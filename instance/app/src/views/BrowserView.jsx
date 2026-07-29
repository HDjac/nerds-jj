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

    const text = getInternalClipboard();

    // Send only the NERDS internal clipboard to remote Firefox.
    // Sending an empty value also prevents stale remote text from being reused.
    rfbObj.current.clipboardPasteFrom(text || "");

    if (text) {
      console.log("NERDS internal clipboard sent to VNC");
    } else {
      console.log("NERDS internal clipboard is empty; VNC clipboard cleared");
    }
  }

  function sendVncCtrlShortcut(key) {
    const rfb = rfbObj.current;

    if (!rfb) {
      return;
    }

    const keyInfo = {
      c: { keysym: 0x0063, code: "KeyC" },
      v: { keysym: 0x0076, code: "KeyV" },
      x: { keysym: 0x0078, code: "KeyX" }
    }[key.toLowerCase()];

    if (!keyInfo) {
      return;
    }

  /*
   * Reset noVNC keyboard tracking. On macOS, noVNC can translate
   * the Cmd/Super key into remote Alt, so Meta/Super releases alone
   * are insufficient.
   */
    rfb.blur();

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

    modifiers.forEach((keysym) => {
      rfb.sendKey(keysym, null, false);
    });

    rfb.focus();

    const ctrlKeysym = 0xffe3;

    rfb.sendKey(ctrlKeysym, "ControlLeft", true);
    rfb.sendKey(keyInfo.keysym, keyInfo.code, true);
    rfb.sendKey(keyInfo.keysym, keyInfo.code, false);
    rfb.sendKey(ctrlKeysym, "ControlLeft", false);
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
     * Prevent the host browser and noVNC from processing the original
     * clipboard shortcut. We will send a controlled shortcut instead.
     */
    e.preventDefault();
    e.stopPropagation();

    if (typeof e.stopImmediatePropagation === "function") {
      e.stopImmediatePropagation();
    }

    if (key === "v") {
      /*
       * Update the remote Linux clipboard twice. The second update
       * handles cases where focus is changing between the React page,
       * the noVNC canvas, and remote Firefox.
       */
      syncInternalClipboardToVnc();

      setTimeout(() => {
        syncInternalClipboardToVnc();
      }, 150);

      /*
       * Give remote Firefox time to receive the clipboard value before
       * sending one Ctrl+V. This should make one Cmd+V produce one paste.
       */
      setTimeout(() => {
        sendVncCtrlShortcut("v");
      }, 400);

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+V queued for the remote browser`
      );

      return;
    }

    if (key === "c") {
      sendVncCtrlShortcut("c");

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+C translated to remote Ctrl+C`
      );

      return;
    }

    if (key === "x") {
      sendVncCtrlShortcut("x");

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+X translated to remote Ctrl+X`
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

    /*
     * Text copied or cut inside remote Firefox is stored only in the
     * NERDS internal clipboard. It is not written to navigator.clipboard.
     */
    if (stat.detail && stat.detail.text) {
      setInternalClipboard(
        stat.detail.text,
        "internal_browser"
      );
    }
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
    function handleInternalClipboardEvent() {
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

    return () => {
      window.removeEventListener(
        "keydown",
        handleBrowserClipboardShortcut,
        true
      );
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