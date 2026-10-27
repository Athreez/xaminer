import {
  Award,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Clock,
  Download,
  Search,
  Trophy,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Style guide for the Xaminer theme (FRONTEND_SPEC.md § 3.1). Visit /theme. */
export function ThemePreviewPage() {
  const [selected, setSelected] = useState("B");

  return (
    <main className="mx-auto max-w-5xl space-y-10 px-4 py-10">
      <header className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="bg-brand-gradient shadow-glow grid size-12 place-items-center rounded-xl text-primary-foreground">
            <Award className="size-6" />
          </div>
          <div>
            <h1 className="text-brand-gradient text-3xl font-bold">Theme preview</h1>
            <p className="text-muted-foreground">
              Every colour and component of the Xaminer theme.
            </p>
          </div>
        </div>
        <ThemeToggle />
      </header>

      <section aria-labelledby="stats" className="space-y-3">
        <h2 id="stats" className="text-lg font-semibold">
          Stat cards
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <StatCard value="5" label="Total attempts" />
          <StatCard value="2" label="Passed" tone="success" />
          <StatCard value="3" label="Needs improvement" tone="danger" />
        </div>
      </section>

      <section aria-labelledby="list" className="space-y-3">
        <h2 id="list" className="text-lg font-semibold">
          Search, filters and result rows
        </h2>
        <div className="flex gap-3">
          <label className="bg-card border-input flex flex-1 items-center gap-2 rounded-xl border px-4">
            <Search className="text-muted-foreground size-4" />
            <span className="sr-only">Search</span>
            <input
              className="placeholder:text-muted-foreground h-11 flex-1 bg-transparent outline-none"
              placeholder="Search by exam…"
            />
          </label>
          <Button className="h-11 px-5">All</Button>
          <Button variant="outline" className="h-11 px-5">
            Passed
          </Button>
          <Button variant="outline" className="h-11 px-5">
            Failed
          </Button>
        </div>
        <ResultRow title="Organizational Behaviour" date="12 Oct 2026" score="2/5" percent={40} />
        <ResultRow title="Data Structures" date="27 Jul 2026" score="6/6" percent={100} passed />
      </section>

      <section aria-labelledby="exam" className="space-y-3">
        <h2 id="exam" className="text-lg font-semibold">
          Exam screen pieces (always light during proctored exams)
        </h2>
        <div className="bg-card space-y-5 rounded-2xl border p-6">
          <div className="flex items-center justify-between">
            <p className="text-lg font-semibold">Question 4 of 5</p>
            <p className="bg-background flex items-center gap-2 rounded-xl border px-4 py-2 font-mono">
              <Clock className="text-selection size-4" />
              <span aria-label="Time remaining">00:53</span>
            </p>
          </div>
          <div>
            <div className="bg-muted h-2 overflow-hidden rounded-full">
              <div className="bg-progress-gradient h-full w-3/5 rounded-full" />
            </div>
            <p className="text-muted-foreground mt-2 text-sm">3 of 5 answered</p>
          </div>
          <p className="text-lg leading-relaxed font-semibold">
            Which statement best describes the role of a strong organizational culture?
          </p>
          <div role="radiogroup" aria-label="Answer options" className="space-y-3">
            {[
              ["A", "It replaces all written rules and regulations."],
              ["B", "It reduces ambiguity by providing shared meaning, increasing commitment."],
              ["C", "It guarantees high financial performance."],
            ].map(([key, text]) => (
              <button
                key={key}
                type="button"
                role="radio"
                aria-checked={selected === key}
                onClick={() => setSelected(key!)}
                className={cn(
                  "flex w-full items-center gap-4 rounded-xl border px-5 py-4 text-left font-medium transition-colors",
                  selected === key
                    ? "border-selection bg-selection-soft border-2"
                    : "hover:bg-accent",
                )}
              >
                <span
                  className={cn(
                    "grid size-5 shrink-0 place-items-center rounded-full border-2",
                    selected === key ? "border-selection" : "border-muted-foreground",
                  )}
                >
                  {selected === key && <span className="bg-selection size-2.5 rounded-full" />}
                </span>
                {key}) {text}
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between">
            <Button variant="secondary" size="lg">
              Previous
            </Button>
            <nav aria-label="Questions" className="flex gap-2">
              <NavButton n={1} state="answered" />
              <NavButton n={2} state="answered" />
              <NavButton n={3} state="answered" />
              <NavButton n={4} state="current" />
              <NavButton n={5} state="unvisited" />
            </nav>
            <Button variant="progress" size="lg">
              Next
            </Button>
          </div>
        </div>
      </section>

      <section aria-labelledby="form" className="space-y-3">
        <h2 id="form" className="text-lg font-semibold">
          Form
        </h2>
        <form className="bg-card max-w-md space-y-4 rounded-2xl border p-6">
          <h3 className="text-brand-gradient text-xl font-bold">Create exam</h3>
          <Field label="Title" placeholder="e.g. Mid-term: Data Structures" />
          <Field label="Duration (minutes)" placeholder="60" />
          <Field label="Pass mark (%)" placeholder="40" error="Must be between 0 and 100." />
          <div className="flex gap-2">
            <Button type="button">Save</Button>
            <Button type="button" variant="outline">
              Cancel
            </Button>
            <Button type="button" variant="destructive">
              Delete
            </Button>
          </div>
        </form>
      </section>
    </main>
  );
}

function StatCard({
  value,
  label,
  tone,
}: {
  value: string;
  label: string;
  tone?: "success" | "danger";
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border p-6 text-center",
        tone === "success" && "bg-success-soft border-success/40",
        tone === "danger" && "bg-danger-soft border-destructive/40",
        !tone && "bg-card",
      )}
    >
      <p
        className={cn(
          "text-3xl font-bold",
          tone === "success" && "text-success",
          tone === "danger" && "text-destructive",
        )}
      >
        {value}
      </p>
      <p className="text-muted-foreground mt-1 text-sm">{label}</p>
    </div>
  );
}

function ResultRow(props: {
  title: string;
  date: string;
  score: string;
  percent: number;
  passed?: boolean;
}) {
  const { title, date, score, percent, passed } = props;
  return (
    <div
      className={cn(
        "bg-card flex items-center gap-4 rounded-2xl border p-5",
        passed && "border-success/40",
      )}
    >
      <div
        className={cn(
          "grid size-12 place-items-center rounded-xl",
          passed ? "bg-brand-gradient shadow-glow text-primary-foreground" : "bg-muted",
        )}
      >
        {passed ? (
          <Trophy className="size-6" />
        ) : (
          <BookOpen className="text-muted-foreground size-6" />
        )}
      </div>
      <div className="flex-1">
        <p className="flex items-center gap-2 text-lg font-semibold">
          {title}
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
              passed
                ? "bg-success-soft text-success border-success/40"
                : "bg-danger-soft text-destructive border-destructive/40",
            )}
          >
            {passed ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
            {passed ? "Passed" : "Not passed"}
          </span>
        </p>
        <p className="text-muted-foreground mt-1 flex items-center gap-4 text-sm">
          <span className="flex items-center gap-1">
            <CalendarDays className="size-4" /> {date}
          </span>
          <span>
            Score: <strong className={passed ? "text-success" : "text-destructive"}>{score}</strong>
          </span>
        </p>
      </div>
      <p
        className={cn(
          "grid size-14 place-items-center rounded-full border-4 text-sm font-bold",
          passed ? "border-success text-success" : "border-destructive text-destructive",
        )}
      >
        {percent}%
      </p>
      {passed && (
        <Button>
          <Download /> View & download
        </Button>
      )}
    </div>
  );
}

function NavButton({ n, state }: { n: number; state: "answered" | "current" | "unvisited" }) {
  const label = { answered: "answered", current: "current question", unvisited: "not visited" }[
    state
  ];
  return (
    <button
      type="button"
      aria-label={`Question ${n}, ${label}`}
      aria-current={state === "current" ? "step" : undefined}
      className={cn(
        "grid size-10 place-items-center rounded-lg text-sm font-semibold",
        state === "answered" && "bg-success-soft text-success border-success/40 border",
        state === "current" && "bg-selection text-white",
        state === "unvisited" && "bg-muted text-muted-foreground border border-dashed",
      )}
    >
      {n}
    </button>
  );
}

function Field({
  label,
  placeholder,
  error,
}: {
  label: string;
  placeholder: string;
  error?: string;
}) {
  const id = label.toLowerCase().replace(/\W+/g, "-");
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        className={cn(
          "bg-background border-input placeholder:text-muted-foreground focus-visible:ring-ring/50 h-11 w-full rounded-xl border px-4 outline-none focus-visible:ring-[3px]",
          error && "border-destructive",
        )}
      />
      {error && (
        <p id={`${id}-error`} className="text-destructive text-sm">
          {error}
        </p>
      )}
    </div>
  );
}
