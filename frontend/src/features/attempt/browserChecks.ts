import { useCallback, useEffect, useRef, useState } from "react";

import type { BrowserEvent } from "./useExamSession";

/** Leaving the page for less than this isn't counted (a stray click on the taskbar). */
const AWAY_MS = 1000;
const REMEMBERED = 50;

/** The same text, however the copy and the paste wrote its line breaks and edges. */
export function normalise(text: string): string {
  return text.replace(/\r\n?/g, "\n").trim();
}

/** True when this text was copied (or cut) inside the exam. */
export function copiedInside(text: string, copies: readonly string[]): boolean {
  const wanted = normalise(text);
  return wanted === "" || copies.includes(wanted);
}

export function fullscreenSupported(): boolean {
  return typeof document !== "undefined" && document.fullscreenEnabled === true;
}

/**
 * Browser checks during an exam (when the exam has them on): fullscreen, staying on the page,
 * pasting only what was copied in the exam, one screen. Each break is recorded for the teacher;
 * the student only sees neutral reminders (PRD PRC-09: never the events themselves).
 */
export function useBrowserChecks(enabled: boolean, record: (event: BrowserEvent) => void) {
  const [fullscreen, setFullscreen] = useState(() => !!document.fullscreenElement);
  const [notice, setNotice] = useState<string | null>(null);
  const exitedAt = useRef<number | null>(null);
  const awayAt = useRef<{ at: number; how: string } | null>(null);
  const copies = useRef<string[]>([]);
  const screensReported = useRef(false);
  const recordRef = useRef(record);
  useEffect(() => {
    recordRef.current = record;
  }, [record]);

  useEffect(() => {
    if (!enabled) return;
    const emit = (event: BrowserEvent) => recordRef.current(event);

    // Fullscreen: every exit, with how long until the student came back.
    const onFullscreen = () => {
      const now = Date.now();
      const inFull = !!document.fullscreenElement;
      setFullscreen(inFull);
      if (!inFull) {
        exitedAt.current = now;
      } else if (exitedAt.current !== null) {
        emit({ kind: "FULLSCREEN_EXIT", at: exitedAt.current, durationMs: now - exitedAt.current });
        exitedAt.current = null;
      }
    };

    // Leaving: another tab (hidden) or another window (blur); one event per time away.
    const leave = (how: string) => {
      if (!awayAt.current) awayAt.current = { at: Date.now(), how };
    };
    const back = () => {
      const away = awayAt.current;
      awayAt.current = null;
      if (!away) return;
      const durationMs = Date.now() - away.at;
      if (durationMs < AWAY_MS) return;
      emit({ kind: "TAB_SWITCH", at: away.at, durationMs, details: { how: away.how } });
      setNotice("Please stay on the exam page until you submit.");
    };
    const onVisibility = () => (document.hidden ? leave("tab") : back());
    const onBlur = () => leave("window");
    const onFocus = () => {
      if (!document.hidden) back();
    };

    // Copy inside the exam is remembered so it can be pasted back; anything else is blocked.
    const onCopy = (event: ClipboardEvent) => {
      // What's being copied: the code editor puts it in the event; a text box keeps its own
      // selection (the page's selection doesn't include it); anything else is the page's.
      const box = document.activeElement;
      const inBox =
        box instanceof HTMLTextAreaElement || box instanceof HTMLInputElement
          ? box.value.slice(box.selectionStart ?? 0, box.selectionEnd ?? 0)
          : "";
      const text =
        event.clipboardData?.getData("text/plain") ||
        inBox ||
        window.getSelection()?.toString() ||
        "";
      const clean = normalise(text);
      if (!clean) return;
      copies.current = [clean, ...copies.current.filter((c) => c !== clean)].slice(0, REMEMBERED);
    };
    const onPaste = (event: ClipboardEvent) => {
      const text = event.clipboardData?.getData("text/plain") ?? "";
      if (copiedInside(text, copies.current)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      emit({ kind: "PASTE_BLOCKED", details: { length: text.length, how: "paste" } });
      setNotice("You can only paste text you copied in this exam.");
    };
    let draggingInside = false;
    const onDragStart = () => {
      draggingInside = true;
    };
    const onDragEnd = () => {
      draggingInside = false;
    };
    const onDrop = (event: DragEvent) => {
      if (draggingInside) return;
      const text = event.dataTransfer?.getData("text/plain") ?? "";
      event.preventDefault();
      event.stopImmediatePropagation();
      if (text) {
        emit({ kind: "PASTE_BLOCKED", details: { length: text.length, how: "drop" } });
        setNotice("You can only paste text you copied in this exam.");
      }
    };

    // More than one screen (Chrome and Edge can tell; elsewhere this can't be checked).
    const screenInfo = window.screen as Screen & { isExtended?: boolean };
    const checkScreens = () => {
      if (screenInfo.isExtended === true && !screensReported.current) {
        screensReported.current = true;
        emit({ kind: "MULTIPLE_SCREENS", details: { screens: "extended" } });
        setNotice("Please use one screen during the exam.");
      } else if (screenInfo.isExtended === false) {
        screensReported.current = false;
      }
    };
    checkScreens();
    const screenEvents = screenInfo as unknown as EventTarget;

    document.addEventListener("fullscreenchange", onFullscreen);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    document.addEventListener("copy", onCopy);
    document.addEventListener("cut", onCopy);
    window.addEventListener("paste", onPaste, { capture: true });
    document.addEventListener("dragstart", onDragStart);
    document.addEventListener("dragend", onDragEnd);
    window.addEventListener("drop", onDrop, { capture: true });
    screenEvents.addEventListener?.("change", checkScreens);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreen);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("copy", onCopy);
      document.removeEventListener("cut", onCopy);
      window.removeEventListener("paste", onPaste, { capture: true });
      document.removeEventListener("dragstart", onDragStart);
      document.removeEventListener("dragend", onDragEnd);
      window.removeEventListener("drop", onDrop, { capture: true });
      screenEvents.removeEventListener?.("change", checkScreens);
    };
  }, [enabled]);

  const enterFullscreen = useCallback(() => {
    void document.documentElement.requestFullscreen?.().catch(() => undefined);
  }, []);

  return {
    /** Questions stay hidden until this is true (when the browser supports fullscreen). */
    inFullscreen: !enabled || !fullscreenSupported() || fullscreen,
    enterFullscreen,
    notice: enabled ? notice : null,
    dismissNotice: () => setNotice(null),
  };
}
