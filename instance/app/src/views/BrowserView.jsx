import { useRef, useEffect, useState } from "react";
import RFB from "@novnc/novnc";
import "./BrowserView.css";
import ControlButton from "../components/ControlButton";
import AudioPlugin from "../lib/novnc-audio";
import { DEV_MODE } from "../util";

/* Completely disables the VNC session to enable testing without backend */
const NO_VNC = false;

export default function BrowserView(props) {
  const rfbElement = useRef(null);
  const containerElement = useRef(null);
  const rfbObj = useRef(null);

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
    localStorage.setItem("NERDS_INTERNAL_CLIPBOARD_TS", String(Date.now()));

    console.log(`NERDS internal clipboard saved from ${source}:`, text);
  }

  function syncInternalClipboardToVnc() {
    if (!rfbObj.current) {
      return;
    }

    const text = getInternalClipboard();

    // Send the NERDS internal clipboard into the remote Firefox/Linux clipboard.
    // If empty, send empty text so a stale remote clipboard is not reused.
    rfbObj.current.clipboardPasteFrom(text || "");

    if (text) {
      console.log("NERDS internal clipboard sent to VNC");
    } else {
      console.log("NERDS internal clipboard is empty; VNC clipboard cleared");
    }
  }

  function sendVncCtrlShortcut(key) {
    if (!rfbObj.current) {
      return;
    }

    const lowerKey = key.toLowerCase();

    const keyInfo = {
      c: { keysym: 0x0063, code: "KeyC" },
      v: { keysym: 0x0076, code: "KeyV" },
      x: { keysym: 0x0078, code: "KeyX" }
    }[lowerKey];

    if (!keyInfo) {
      return;
    }

    const ctrlKeysym = 0xffe3; // Control_L

    rfbObj.current.sendKey(ctrlKeysym, "ControlLeft", true);
    rfbObj.current.sendKey(keyInfo.keysym, keyInfo.code, true);
    rfbObj.current.sendKey(keyInfo.keysym, keyInfo.code, false);
    rfbObj.current.sendKey(ctrlKeysym, "ControlLeft", false);
  }

  function handleBrowserClipboardShortcut(e) {
    if (props.currentTab !== "browser" || rfbStatus !== "connected") {
      return;
    }

    const key = (e.key || "").toLowerCase();

    const isClipboardShortcut =
      (e.ctrlKey || e.metaKey) &&
      !e.altKey &&
      (key === "c" || key === "v" || key === "x");

    if (!isClipboardShortcut) {
      return;
    }

    e.preventDefault();
    e.stopPropagation();

    if (typeof e.stopImmediatePropagation === "function") {
      e.stopImmediatePropagation();
    }

    if (key === "v") {
      // Push only the NERDS internal clipboard into the remote browser.
      // The delay gives noVNC/remote Firefox time to receive clipboardPasteFrom().
      syncInternalClipboardToVnc();

      setTimeout(() => {
        sendVncCtrlShortcut("v");
      }, 200);

      console.log(
        `${e.metaKey ? "Cmd" : "Ctrl"}+V translated to remote Ctrl+V using NERDS internal clipboard`
      );

      return;
    }

    if (key === "c") {
      sendVncCtrlShortcut("c");
      console.log(`${e.metaKey ? "Cmd" : "Ctrl"}+C translated to remote Ctrl+C`);
      return;
    }

    if (key === "x") {
      sendVncCtrlShortcut("x");
      console.log(`${e.metaKey ? "Cmd" : "Ctrl"}+X translated to remote Ctrl+X`);
    }
  }

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

  function connect(quiet) {
    if (rfbStatus !== "connected" && rfbStatus !== "connecting") {
      setRfbStatus("connecting");

      let vncURL = `wss://${window.location.host}${window.location.pathname}?token=vnc`;
      if (DEV_MODE) {
        vncURL = `ws://192.168.1.35:82?token=vnc`;
      }

      let rfb = new RFB(rfbElement.current, vncURL);

      //rfb.scaleViewport = true;
      rfb.resizeSession = true;
      rfb.background = "#494949";

      rfb.addEventListener("connect", handleConnect);
      rfb.addEventListener("disconnect", handleDisconnect);
      rfb.addEventListener("clipboard", handleClipboard);

      rfbObj.current = rfb;
    }
  }

  const handleDisconnect = (stat) => {
    debug("Handled disconnect");
    stopAudio();

    if (!stat.detail.clean) {
      debug("Unclean disconnect");
      setRfbStatus("failed");
    } else {
      debug("Clean disconnect");
      setRfbStatus("disconnected");
    }
  };

  function handleConnect() {
    debug("Connected to browser instance");
    setRfbStatus("connected");
    setAlerted(false);
    startAudio();

    setTimeout(syncInternalClipboardToVnc, 250);
  }

  const handleClipboard = (stat) => {
    debug("Got clipboard event");
    debug(stat.detail);

    // Remote Firefox copied/cut something.
    // Save it only to the NERDS internal clipboard, not navigator.clipboard.
    if (stat.detail && stat.detail.text) {
      setInternalClipboard(stat.detail.text, "internal_browser");
    }
  };

  useEffect(() => {
    if (!NO_VNC) {
      connect();

      return () => {
        if (rfbObj.current) {
          rfbObj.current.disconnect();
        }

        debug("disconnected RFB object on unmount");
      };
    }
  }, []);

  function doResize() {
    if (containerElement.current) {
      const width = Math.round(containerElement.current.offsetWidth);

      if (width !== 0) {
        debug(`Setting width to ${width}px`);
        rfbElement.current.style.width = `${width}px`;
      }
    }
  }

  useEffect(() => {
    if (props.currentTab === "browser" && containerElement.current) {
      doResize();
    }
  }, [props.currentTab, containerElement, rfbElement]);

  useEffect(() => {
    const observer = new ResizeObserver(doResize);

    if (containerElement.current) {
      observer.observe(containerElement.current);

      return (() => {
        if (containerElement.current) {
          observer.unobserve(containerElement.current);
        }
      });
    }
  }, [containerElement, rfbElement]);

  useEffect(() => {
    if (props.currentTab === "browser" && rfbStatus === "connected") {
      syncInternalClipboardToVnc();
    }
  }, [props.currentTab, rfbStatus]);

  useEffect(() => {
    function handleInternalClipboardEvent() {
      if (rfbStatus === "connected") {
        syncInternalClipboardToVnc();
      }
    }

    window.addEventListener("nerds-internal-clipboard", handleInternalClipboardEvent);

    return () => {
      window.removeEventListener("nerds-internal-clipboard", handleInternalClipboardEvent);
    };
  }, [rfbStatus]);

  useEffect(() => {
    window.addEventListener("online", connect);

    return (() => {
      window.removeEventListener("online", connect);
    });
  });

  useEffect(() => {
    window.addEventListener("keydown", handleBrowserClipboardShortcut, true);

    const node = rfbElement.current;
    if (node) {
      node.addEventListener("keydown", handleBrowserClipboardShortcut, true);
    }

    return () => {
      window.removeEventListener("keydown", handleBrowserClipboardShortcut, true);

      if (node) {
        node.removeEventListener("keydown", handleBrowserClipboardShortcut, true);
      }
    };
  }, [props.currentTab, rfbStatus]);

  useEffect(() => {
    debug(`New RFB state: ${rfbStatus}`);
    props.setConnStatus(rfbStatus === "connected");

    if (rfbStatus === "disconnected") {
      debug("Trying to reconnect to RFB");
      connect();
    } else if (rfbStatus === "failed" && !alerted) {
      setAlerted(true);
      alert("You have been disconnected from the study infrastructure. Please "
        + "check your internet connection and reconnect. If you believe this "
        + "is an error, please contact the study administrators.");
    }
  }, [rfbStatus, alerted]);

  let reconButton = (<ControlButton disabled={true} title="Reconnect" />);
  if (rfbStatus === "disconnected") {
    reconButton = (<ControlButton onClick={connect} title="Reconnect" />);
  }

  return (
    <div className="browserContainer" ref={containerElement}>
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