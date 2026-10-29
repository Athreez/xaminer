import { useRef, type KeyboardEvent } from "react";

import { cn } from "@/lib/utils";

import { navLabel, navStateText, type NavState } from "./lib";

const COLUMNS = 5;

export interface NavItem {
  number: number;
  state: NavState;
  open: boolean; // false: sequential exam, already passed
}

/**
 * The question navigator (FRONTEND_SPEC § 6.4). Each state has its own shape, so colour is never
 * the only cue, and a full name for screen readers. One tab stop: arrow keys move, Enter opens.
 */
export function QuestionNavigator({
  items,
  current,
  sequential,
  onOpen,
}: {
  items: NavItem[];
  current: number;
  sequential: boolean;
  onOpen: (index: number) => void;
}) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  function move(event: KeyboardEvent, from: number) {
    const step: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: COLUMNS,
      ArrowUp: -COLUMNS,
    };
    let to: number | null = null;
    if (event.key in step) to = from + (step[event.key] ?? 0);
    if (event.key === "Home") to = 0;
    if (event.key === "End") to = items.length - 1;
    if (to === null) return;
    event.preventDefault();
    buttons.current[Math.max(0, Math.min(items.length - 1, to))]?.focus();
  }

  return (
    <nav aria-label="Questions" className="space-y-4">
      <h2 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">
        Questions
      </h2>
      {sequential && (
        <p className="bg-muted rounded-lg px-3 py-2 text-xs">
          This exam goes forward only: once you move on, you can't go back to earlier questions.
        </p>
      )}
      <ol className="grid grid-cols-5 gap-2">
        {items.map((item, i) => (
          <li key={item.number}>
            <button
              ref={(el) => {
                buttons.current[i] = el;
              }}
              type="button"
              tabIndex={i === current ? 0 : -1}
              disabled={!item.open}
              aria-current={i === current ? "step" : undefined}
              aria-label={navLabel(item.number, item.state, !item.open)}
              onClick={() => onOpen(i)}
              onKeyDown={(e) => move(e, i)}
              className={cn(
                "relative grid size-9 place-items-center rounded-md text-xs font-semibold",
                "focus-visible:ring-ring outline-none focus-visible:ring-2",
                "disabled:cursor-not-allowed disabled:opacity-40",
                i === current && "ring-selection ring-2 ring-offset-2 ring-offset-(--color-card)",
              )}
            >
              <Shape state={item.state} />
              <span className={cn("relative", filled(item.state) && "text-primary-foreground")}>
                {item.number}
              </span>
            </button>
          </li>
        ))}
      </ol>
      <Legend />
    </nav>
  );
}

function filled(state: NavState): boolean {
  return state === "answered" || state === "answered-marked";
}

/** Circle: not visited · square: not answered · filled square: answered · diamond: marked. */
function Shape({ state, small = false }: { state: NavState; small?: boolean }) {
  const diamond = state === "marked" || state === "answered-marked";
  return (
    <span
      aria-hidden
      className={cn(
        "absolute border-2",
        small ? "inset-0.5" : diamond ? "inset-1.5" : "inset-0.5",
        state === "not-visited" && "border-muted-foreground/50 rounded-full",
        state === "not-answered" && "border-foreground/60 rounded-[2px]",
        diamond && "border-warning rotate-45 rounded-[2px]",
        filled(state) && "border-primary bg-primary rounded-[2px]",
        state === "answered-marked" && "border-warning",
      )}
    />
  );
}

const LEGEND: NavState[] = ["answered", "not-answered", "marked", "answered-marked", "not-visited"];

function Legend() {
  return (
    <ul className="text-muted-foreground space-y-1.5 text-xs">
      {LEGEND.map((state) => (
        <li key={state} className="flex items-center gap-2">
          <span className="relative inline-block size-4 shrink-0">
            <Shape state={state} small />
          </span>
          <span className="first-letter:uppercase">{navStateText[state]}</span>
        </li>
      ))}
    </ul>
  );
}
