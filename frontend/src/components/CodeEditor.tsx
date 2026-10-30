import { cpp } from "@codemirror/lang-cpp";
import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import type { Extension } from "@codemirror/state";
import { EditorView, basicSetup } from "codemirror";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

const LANGUAGES: Record<string, () => Extension> = {
  cpp17: cpp,
  java21: java,
  python312: python,
  node22: javascript,
};

// Colours from the app's theme, so the editor follows light and dark mode.
const theme = EditorView.theme({
  "&": { backgroundColor: "var(--color-card)", color: "var(--color-foreground)" },
  ".cm-content": { fontFamily: "ui-monospace, SFMono-Regular, Consolas, monospace" },
  ".cm-gutters": {
    backgroundColor: "var(--color-muted)",
    color: "var(--color-muted-foreground)",
    border: "none",
  },
  ".cm-activeLine, .cm-activeLineGutter": {
    backgroundColor: "color-mix(in oklab, var(--color-selection) 8%, transparent)",
  },
  "&.cm-focused": { outline: "2px solid var(--color-ring)", outlineOffset: "-2px" },
  ".cm-cursor": { borderLeftColor: "var(--color-foreground)" },
});

/**
 * A code editor (CodeMirror) for one language. Tab is left to the browser, so keyboard users can
 * always move on (FRONTEND_SPEC § 11). Changing `language` starts a fresh editor.
 */
export function CodeEditor({
  value,
  onChange,
  language,
  label,
  className,
  readOnly = false,
}: {
  value: string;
  onChange?: (value: string) => void;
  language: string;
  label: string;
  className?: string;
  readOnly?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const changed = useRef(onChange);
  const initial = useRef(value);

  useEffect(() => {
    changed.current = onChange;
  }, [onChange]);

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      doc: initial.current,
      extensions: [
        basicSetup,
        LANGUAGES[language]?.() ?? [],
        theme,
        EditorView.editable.of(!readOnly),
        EditorView.contentAttributes.of({ "aria-label": label }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) changed.current?.(update.state.doc.toString());
        }),
      ],
    });
    view.current = editor;
    return () => editor.destroy();
  }, [language, label, readOnly]);

  // Replaced from outside (another language picked, a reset): show the new text.
  useEffect(() => {
    initial.current = value;
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return (
    <div
      ref={host}
      className={cn("overflow-hidden rounded-lg border text-sm [&_.cm-editor]:min-h-40", className)}
    />
  );
}
