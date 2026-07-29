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
      c: { keysym: 0x0063, code: "KeyC" },
      v: { keysym: 0x0076, code: "KeyV" },
      x: { keysym: 0x0078, code: "KeyX" }
    }[key.toLowerCase()];

    if (!keyInfo) {
      return;
    }

    releaseVncModifiers();

    const ctrlKeysym = 0xffe3;

    rfb.sendKey(ctrlKeysym, "ControlLeft", true);
    rfb.sendKey(keyInfo.keysym, keyInfo.code, true);
    rfb.sendKey(keyInfo.keysym, keyInfo.code, false);
    rfb.sendKey(ctrlKeysym, "ControlLeft", false);
  }

  function sendVncShiftInsert() {
    const rfb = rfbObj.current;

    if (!rfb) {
      return;
    }

  /*
   * Linux Firefox supports Shift+Insert for paste. This avoids trying
   * to generate Ctrl+V while the physical Mac Cmd key is still down.
   */
    releaseVncModifiers();

    const shiftKeysym = 0xffe1;
    const insertKeysym = 0xff63;

    rfb.sendKey(shiftKeysym, "ShiftLeft", true);
    rfb.sendKey(insertKeysym, "Insert", true);
    rfb.sendKey(insertKeysym, "Insert", false);
    rfb.sendKey(shiftKeysym, "ShiftLeft", false);

    console.log("Remote Shift+Insert sent for Mac Cmd+V");
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
   * the original shortcut.
   */
    e.preventDefault();
    e.stopPropagation();

    if (typeof e.stopImmediatePropagation === "function") {
      e.stopImmediatePropagation();
    }

  /*
   * Mac Cmd+V uses Shift+Insert remotely. Avoid scheduling additional
   * pastes when the keys are held down and generate repeat events.
   */
    if (key === "v" && e.metaKey && !e.ctrlKey) {
      if (e.repeat) {
        return;
      }

      syncInternalClipboardToVnc();

      /*
      * If a paste is already pending, do not cancel or postpone it.
      * Additional Cmd+V presses are ignored until the first paste finishes.
      */
      if (macPasteTimer.current) {
        console.log("Mac paste already pending; extra Cmd+V ignored");
        return;
      }

      syncInternalClipboardToVnc();

      macPasteTimer.current = setTimeout(() => {
        syncInternalClipboardToVnc();
        sendVncCtrlShortcut("v");
        macPasteTimer.current = null;
      }, 400);

      console.log("First Mac Cmd+V scheduled as remote Ctrl+V");

      return;
    }

  /*
   * Keep the currently working Ctrl+V behavior.
   */
    if (key === "v" && e.ctrlKey && !e.metaKey) {
      syncInternalClipboardToVnc();

      setTimeout(() => {
        sendVncCtrlShortcut("v");
      }, 150);

      console.log("Ctrl+V queued as remote Ctrl+V");
      return;
    }

  /*
   * Preserve the working browser-to-editor copy and cut behavior.
   */
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

      if (macPasteTimer.current) {
        clearTimeout(macPasteTimer.current);
        macPasteTimer.current = null;
      }
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