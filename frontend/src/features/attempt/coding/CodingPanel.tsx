import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Code2, History, Play, RotateCcw, Send, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { api, errorCode } from "@/api/client";
import { CodeEditor } from "@/components/CodeEditor";
import { MarkdownView } from "@/components/MarkdownView";
import { FormMessage } from "@/components/form";
import { Busy, ConfirmDialog } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { errorText, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { AttemptItem } from "../lib";
import type { ExamSession } from "../useExamSession";
import {
  PLATFORM_FAILURE,
  diffLines,
  elapsed,
  fetchHistory,
  historyKey,
  verdictText,
  visible,
  type RunView,
  type SubmissionHistory,
  type SubmissionView,
} from "./lib";

const RUN_GAP_MS = 8000;

/**
 * A coding question in the exam (FRONTEND_SPEC § 7): problem · code · results. Run (public tests,
 * never graded) and Submit (graded, every test) look and behave differently on purpose (§ 7.2).
 */
export function CodingPanel({
  attemptId,
  item,
  session,
  runCodeEnabled,
  countedRule,
  wide,
}: {
  attemptId: string;
  item: AttemptItem;
  session: ExamSession;
  runCodeEnabled: boolean;
  countedRule: "BEST" | "LAST";
  wide: boolean;
}) {
  const coding = item.question.coding!;
  const locked = session.ended !== null;
  const [area, setArea] = useState<"problem" | "code" | "results">("problem");
  const problem = <Problem item={item} countedRule={countedRule} />;
  const work = (
    <Workspace
      attemptId={attemptId}
      item={item}
      session={session}
      runAllowed={runCodeEnabled && coding.run_code_allowed}
      locked={locked}
      onResult={() => setArea("results")}
    />
  );

  if (wide) {
    return (
      <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div className="min-w-0">{problem}</div>
        <div className="min-w-0">{work}</div>
      </div>
    );
  }
  // Narrow window: one area at a time (§ 7.1).
  return (
    <div className="space-y-4">
      <p className="bg-warning-soft rounded-lg px-3 py-2 text-sm">
        Coding works best on a wider screen (at least 1280 px).
      </p>
      <div role="tablist" aria-label="Coding question" className="flex gap-1 border-b">
        {(["problem", "code", "results"] as const).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={area === key}
            onClick={() => setArea(key)}
            className={cn(
              "-mb-px border-b-2 px-3 py-1.5 text-sm font-medium capitalize",
              area === key ? "border-selection" : "text-muted-foreground border-transparent",
            )}
          >
            {key}
          </button>
        ))}
      </div>
      <div hidden={area !== "problem"}>{problem}</div>
      <div hidden={area === "problem"}>{work}</div>
    </div>
  );
}

// ----------------------------------------------------------------------------- problem

function Problem({ item, countedRule }: { item: AttemptItem; countedRule: "BEST" | "LAST" }) {
  const coding = item.question.coding!;
  const section = (title: string, text: string) =>
    text.trim() ? (
      <section>
        <h3 className="text-muted-foreground mb-1 text-xs font-semibold tracking-wide uppercase">
          {title}
        </h3>
        <MarkdownView text={text} />
      </section>
    ) : null;
  return (
    <div className="space-y-5">
      <MarkdownView text={item.question.body} />
      {section("Input", coding.input_format)}
      {section("Output", coding.output_format)}
      {section("Constraints", coding.constraints)}
      {coding.examples.map((example, i) => (
        <section key={i}>
          <h3 className="text-muted-foreground mb-1 text-xs font-semibold tracking-wide uppercase">
            Example {i + 1}
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            <Block label="Input" text={example.input} />
            <Block label="Expected output" text={example.expected_output} />
          </div>
        </section>
      ))}
      <p className="text-muted-foreground text-sm">
        Limits: {coding.time_limit_ms / 1000} s · {coding.memory_limit_mb} MB (slower languages get
        more time).{" "}
        {coding.partial_scoring
          ? "Marks for each test passed."
          : "Full marks only if every test passes."}{" "}
        Counted: your {countedRule === "BEST" ? "best" : "last"} submission.
      </p>
    </div>
  );
}

function Block({ label, text, className }: { label: string; text: string; className?: string }) {
  return (
    <div className={className}>
      <p className="text-muted-foreground mb-0.5 text-xs">{label}</p>
      <pre className="bg-muted max-h-48 overflow-auto rounded-lg px-3 py-2 font-mono text-xs whitespace-pre-wrap">
        {text || " "}
      </pre>
    </div>
  );
}

// ----------------------------------------------------------------------------- code + results

function Workspace({
  attemptId,
  item,
  session,
  runAllowed,
  locked,
  onResult,
}: {
  attemptId: string;
  item: AttemptItem;
  session: ExamSession;
  runAllowed: boolean;
  locked: boolean;
  onResult: () => void;
}) {
  const queryClient = useQueryClient();
  const eq = item.exam_question_id;
  const coding = item.question.coding!;
  const languages = coding.languages;
  const [language, setLanguage] = useState(session.lastLanguage[eq] ?? languages[0]?.key ?? "");
  const [switched, setSwitched] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);
  const [useCustom, setUseCustom] = useState(false);
  const [customInput, setCustomInput] = useState("");
  const [tab, setTab] = useState<"run" | "submissions">("run");
  const [runId, setRunId] = useState<string | null>(null);
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const [lastRunAt, setLastRunAt] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const starter = languages.find((l) => l.key === language)?.starter_code ?? "";
  const source = session.drafts[eq]?.[language] ?? starter;
  const name = (key: string) => languages.find((l) => l.key === key)?.display_name ?? key;

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(id);
  }, []);

  const history = useQuery({
    queryKey: historyKey(attemptId, eq),
    queryFn: () => fetchHistory(attemptId, eq),
  });
  const run = useQuery({
    enabled: runId !== null,
    queryKey: ["run", runId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: runId ?? "" } } })),
    refetchInterval: (q) => q.state.data?.poll_after_ms ?? false,
  });
  const submission = useQuery({
    enabled: submissionId !== null,
    queryKey: ["submission", submissionId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/submissions/{submission_id}", {
          params: { path: { submission_id: submissionId ?? "" } },
        }),
      ),
    refetchInterval: (q) => q.state.data?.poll_after_ms ?? false,
  });
  // When a submission is graded, the history (and which one counts) changes.
  const graded = submission.data && submission.data.status !== "QUEUED";
  useEffect(() => {
    if (graded) void queryClient.invalidateQueries({ queryKey: historyKey(attemptId, eq) });
  }, [graded, queryClient, attemptId, eq]);

  const startRun = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/attempts/{attempt_id}/questions/{exam_question_id}/runs", {
          params: { path: { attempt_id: attemptId, exam_question_id: eq } },
          body: { language_key: language, source, custom_input: useCustom ? customInput : null },
        }),
      ),
    onSuccess: (started) => {
      setRunId(started.id);
      setLastRunAt(Date.now());
      queryClient.setQueryData(["run", started.id], started);
      setTab("run");
      onResult();
    },
  });
  const submit = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/attempts/{attempt_id}/questions/{exam_question_id}/submissions", {
          params: { path: { attempt_id: attemptId, exam_question_id: eq } },
          body: { language_key: language, source },
        }),
      ),
    onSuccess: (sent) => {
      setConfirmSubmit(false);
      setSubmissionId(sent.id);
      queryClient.setQueryData(["submission", sent.id], sent);
      void queryClient.invalidateQueries({ queryKey: historyKey(attemptId, eq) });
      setTab("submissions");
      onResult();
    },
    onError: () => setConfirmSubmit(false),
  });

  const cooldown = Math.max(0, Math.ceil((lastRunAt + RUN_GAP_MS - now) / 1000));
  const runBusy = startRun.isPending || run.data?.status === "QUEUED";
  const left = history.data?.submissions_left;
  const max = history.data?.max_submissions ?? coding.max_submissions;
  const used = left === undefined ? undefined : max - left;
  const runsLeft = run.data?.runs_left;
  const tooSoon = errorCode(startRun.error) === "RUN_TOO_SOON";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">Language</span>
        <Select
          value={language}
          disabled={locked}
          onValueChange={(next) => {
            setSwitched(language);
            setLanguage(next);
          }}
        >
          <SelectTrigger className="w-56" aria-label="Language">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languages.map((l) => (
              <SelectItem key={l.key} value={l.key}>
                {l.display_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button variant="ghost" size="sm" disabled={locked} onClick={() => setResetting(true)}>
          <RotateCcw /> Reset to starter
        </Button>
        {switched && switched !== language && (
          <span className="text-muted-foreground text-xs">Your {name(switched)} code is kept.</span>
        )}
      </div>

      <CodeEditor
        key={language}
        language={language}
        label={`Your code, ${name(language)}`}
        value={source}
        readOnly={locked}
        onChange={(code) => session.setDraft(eq, language, code)}
        className="[&_.cm-editor]:min-h-72"
      />

      {runAllowed && useCustom && (
        <Textarea
          aria-label="Input for your program"
          rows={3}
          className="font-mono text-sm"
          placeholder="Input for your program"
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
        />
      )}

      <div className="flex flex-wrap items-center gap-3">
        {runAllowed ? (
          <>
            <Button
              variant="outline"
              disabled={locked || runBusy || cooldown > 0 || !source.trim()}
              onClick={() => startRun.mutate()}
            >
              <Busy busy={runBusy}>
                <Play /> {cooldown > 0 ? `Run again in ${cooldown} s` : "Run code"}
              </Busy>
            </Button>
            <label className="flex items-center gap-1.5 text-sm">
              <Checkbox checked={useCustom} onCheckedChange={(v) => setUseCustom(v === true)} />
              Custom input
            </label>
            {runsLeft !== undefined && (
              <span className="text-muted-foreground text-xs">{runsLeft} runs left</span>
            )}
          </>
        ) : (
          <span className="text-muted-foreground text-sm">Run Code is off for this question.</span>
        )}
        <div className="ml-auto flex items-center gap-3">
          {used !== undefined && (
            <span className="text-muted-foreground text-sm tabular-nums">
              {used}/{max} submitted
            </span>
          )}
          <Button
            disabled={locked || submit.isPending || left === 0 || !source.trim()}
            onClick={() => setConfirmSubmit(true)}
          >
            <Send /> Submit
          </Button>
        </div>
      </div>
      {startRun.isError && !tooSoon && (
        <FormMessage tone="error">{errorText(startRun.error)}</FormMessage>
      )}
      {submit.isError && <FormMessage tone="error">{errorText(submit.error)}</FormMessage>}

      <div className="bg-card rounded-xl border">
        <div role="tablist" aria-label="Results" className="flex gap-1 border-b px-3">
          {(
            [
              ["run", "Run", Code2],
              ["submissions", "Submissions", History],
            ] as const
          ).map(([key, label, Icon]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium",
                tab === key ? "border-selection" : "text-muted-foreground border-transparent",
              )}
            >
              <Icon className="size-4" aria-hidden /> {label}
            </button>
          ))}
        </div>
        <div className="space-y-4 p-4">
          {tab === "run" ? (
            <RunResult run={run.data} now={now} startedAt={lastRunAt} />
          ) : (
            <>
              {submission.data && <SubmissionResult submission={submission.data} now={now} />}
              <SubmissionList history={history.data} name={name} />
            </>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmSubmit}
        onOpenChange={setConfirmSubmit}
        title="Submit for grading?"
        description={`This uses 1 of your ${max} submissions. It runs on every test, including hidden ones.`}
        confirmLabel="Submit"
        busy={submit.isPending}
        onConfirm={() => submit.mutate()}
      />
      <ConfirmDialog
        open={resetting}
        onOpenChange={setResetting}
        title={`Reset your ${name(language)} code?`}
        description="Your code in this language is replaced by the starter code. Other languages are kept."
        confirmLabel="Reset"
        busy={false}
        onConfirm={() => {
          session.setDraft(eq, language, starter);
          setResetting(false);
        }}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------- results

const NOT_GRADED = "Run results do not affect your score.";

function RunResult({
  run,
  now,
  startedAt,
}: {
  run: RunView | undefined;
  now: number;
  startedAt: number;
}) {
  if (!run) {
    return (
      <p className="text-muted-foreground text-sm">
        Run your code on the examples (or your own input) to check it. {NOT_GRADED}
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs">{NOT_GRADED}</p>
      {run.status === "QUEUED" && <p className="text-sm">Running — {elapsed(startedAt, now)}</p>}
      {run.status === "FAILED" && <FormMessage tone="error">{PLATFORM_FAILURE}</FormMessage>}
      {run.status === "COMPLETED" && (run.results ?? []).length === 0 && run.compile_output && (
        <Block label="Doesn't compile" text={run.compile_output} />
      )}
      {(run.results ?? []).map((r) => {
        const result = r as {
          name: string;
          input: string | null;
          expected_output: string | null;
          stdout: string;
          stderr: string;
          passed: boolean | null;
          outcome: string | null;
          time_ms: number;
        };
        return result.name === "custom" ? (
          <div key="custom" className="space-y-2">
            <p className="text-sm font-medium">Your input</p>
            <Block label="Output" text={result.stdout} />
            {result.stderr && <Block label="Errors" text={result.stderr} />}
          </div>
        ) : (
          <PublicCase
            key={result.name}
            number={Number(result.name)}
            passed={Boolean(result.passed)}
            outcome={result.outcome}
            input={result.input ?? ""}
            expected={result.expected_output ?? ""}
            actual={result.stdout}
            timeMs={result.time_ms}
          />
        );
      })}
    </div>
  );
}

function PublicCase({
  number,
  passed,
  outcome,
  input,
  expected,
  actual,
  timeMs,
}: {
  number: number;
  passed: boolean;
  outcome: string | null;
  input: string;
  expected: string;
  actual: string;
  timeMs: number | null;
}) {
  const rows = diffLines(expected, actual);
  return (
    <details open={!passed} className="rounded-lg border">
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm">
        <Mark passed={passed} />
        Test {number}: {passed ? "Passed" : (verdictText[outcome ?? ""] ?? "Failed")}
        {timeMs !== null && (
          <span className="text-muted-foreground ml-auto text-xs">{timeMs} ms</span>
        )}
      </summary>
      <div className="space-y-2 border-t p-3">
        <Block label="Input" text={input} />
        <div>
          <div className="text-muted-foreground mb-0.5 grid grid-cols-2 gap-2 text-xs">
            <span>Expected output</span>
            <span>Your output</span>
          </div>
          <div className="bg-muted overflow-auto rounded-lg font-mono text-xs">
            {rows.map((row, i) => (
              <div
                key={i}
                className={cn("grid grid-cols-2 gap-2 px-3 py-0.5", !row.same && "bg-danger-soft")}
              >
                <span className="break-all whitespace-pre-wrap">
                  {row.expected === null ? "—" : visible(row.expected)}
                </span>
                <span className="break-all whitespace-pre-wrap">
                  {row.actual === null ? "—" : visible(row.actual)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </details>
  );
}

function Mark({ passed }: { passed: boolean }) {
  return passed ? (
    <CheckCircle2 className="text-success size-4" aria-label="Passed" />
  ) : (
    <XCircle className="text-destructive size-4" aria-label="Failed" />
  );
}

function SubmissionResult({ submission, now }: { submission: SubmissionView; now: number }) {
  const s = submission;
  if (s.status === "QUEUED") {
    return (
      <p className="text-sm">
        Submission {s.submission_no}: running — {elapsed(Date.parse(s.created_at), now)}
      </p>
    );
  }
  if (s.status === "FAILED") return <FormMessage tone="error">{PLATFORM_FAILURE}</FormMessage>;
  const compileError = s.verdict === "COMPILE_ERROR";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="font-semibold">{verdictText[s.verdict ?? ""] ?? s.verdict}</span>
        <span className="tabular-nums">
          {Number(s.score)} / {Number(s.max_score)}
        </span>
        {!compileError && s.total_cases !== null && (
          <span className="text-muted-foreground text-sm">
            {s.passed_cases} of {s.total_cases} tests passed
          </span>
        )}
      </div>
      {compileError && (
        <>
          <p className="text-sm">Score 0 — code that doesn't compile scores zero.</p>
          <Block label="Compiler output" text={s.compile_output ?? ""} />
        </>
      )}
      {s.cases.map((c) =>
        c.hidden ? (
          <p key={c.number} className="flex items-center gap-2 text-sm">
            <Mark passed={c.passed} /> Hidden test {c.number}: {c.passed ? "Passed" : "Failed"}
          </p>
        ) : (
          <PublicCase
            key={c.number}
            number={c.number}
            passed={c.passed}
            outcome={c.outcome}
            input={c.input ?? ""}
            expected={c.expected_output ?? ""}
            actual={c.stdout ?? ""}
            timeMs={c.time_ms ?? null}
          />
        ),
      )}
    </div>
  );
}

function SubmissionList({
  history,
  name,
}: {
  history: SubmissionHistory | undefined;
  name: (key: string) => string;
}) {
  const [viewing, setViewing] = useState<SubmissionView | null>(null);
  if (!history?.submissions.length) {
    return <p className="text-muted-foreground text-sm">No submissions yet.</p>;
  }
  return (
    <>
      <table className="w-full text-sm">
        <thead className="text-muted-foreground text-left">
          <tr>
            <th className="py-1 pr-3 font-medium">#</th>
            <th className="py-1 pr-3 font-medium">Time</th>
            <th className="py-1 pr-3 font-medium">Language</th>
            <th className="py-1 pr-3 font-medium">Result</th>
            <th className="py-1 pr-3 font-medium">Score</th>
            <th className="py-1" />
          </tr>
        </thead>
        <tbody>
          {history.submissions.map((s) => (
            <tr key={s.id} className="border-t">
              <td className="py-1.5 pr-3 tabular-nums">
                {s.submission_no}
                {s.is_auto && <span className="text-muted-foreground"> (auto)</span>}
              </td>
              <td className="py-1.5 pr-3 tabular-nums">
                {new Date(s.created_at).toLocaleTimeString()}
              </td>
              <td className="py-1.5 pr-3">{name(s.language_key)}</td>
              <td className="py-1.5 pr-3">
                {s.status === "QUEUED"
                  ? "Running…"
                  : s.status === "FAILED"
                    ? "Couldn't run"
                    : (verdictText[s.verdict ?? ""] ?? s.verdict)}
                {s.is_counted && (
                  <Badge variant="secondary" className="ml-2">
                    Counts
                  </Badge>
                )}
              </td>
              <td className="py-1.5 pr-3 tabular-nums">
                {s.score === null ? "—" : `${Number(s.score)} / ${Number(s.max_score)}`}
              </td>
              <td className="py-1.5 text-right">
                <Button variant="ghost" size="sm" onClick={() => setViewing(s)}>
                  View code
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Dialog open={viewing !== null} onOpenChange={(open) => !open && setViewing(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>
              Submission {viewing?.submission_no} · {viewing ? name(viewing.language_key) : ""}
            </DialogTitle>
          </DialogHeader>
          {viewing && (
            <CodeEditor
              language={viewing.language_key}
              label={`Submission ${viewing.submission_no} code`}
              value={viewing.source}
              readOnly
              className="[&_.cm-editor]:max-h-[60vh]"
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
