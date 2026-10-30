import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Eye,
  Pencil,
  Play,
  Plus,
  Trash2,
  XCircle,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { CodeEditor } from "@/components/CodeEditor";
import { Field, FormMessage } from "@/components/form";
import { Busy, ConfirmDialog, LoadingRows, PageHeader } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { errorText, formatDateTime, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import type { Question } from "../lib";
import {
  codingBody,
  comparisonText,
  effectiveMs,
  outcomeText,
  sizeText,
  statusText,
  type CodingIn,
  type CodingView,
  type ComparisonMode,
  type TestCase,
  type ValidationReport,
} from "./lib";

const TABS = [
  { key: "problem", label: "Problem" },
  { key: "languages", label: "Languages & limits" },
  { key: "tests", label: "Test cases" },
  { key: "validate", label: "Validate" },
] as const;
type Tab = (typeof TABS)[number]["key"];

/**
 * The coding question editor (FRONTEND_SPEC § 5.3): Problem · Languages & limits · Test cases ·
 * Validate. Each tab saves on its own; every panel stays mounted, so unsaved edits survive a tab
 * switch. `problem` is the shared question form (statement, marks, tags, sharing).
 */
export function CodingEditor({ question, problem }: { question: Question; problem: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "problem") as Tab;
  const coding = question.coding as CodingView;
  const version = question.version;

  return (
    <section className="max-w-5xl">
      <Link
        to="/teacher/questions"
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        ← All questions
      </Link>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            Coding question <StatusBadge status={coding.validation_status} />
            {question.archived_at && <Badge variant="outline">Archived</Badge>}
          </span>
        }
        description={`Version ${version.version_no} · Updated ${formatDateTime(question.updated_at)}`}
        actions={
          <Button variant="outline" asChild>
            <Link to="preview">
              <Eye /> Student preview
            </Link>
          </Button>
        }
      />
      {version.is_locked && (
        <div className="mb-4">
          <FormMessage tone="info">
            A published exam uses this version. Any change creates a new version (to validate
            again); the exam keeps the old one.
          </FormMessage>
        </div>
      )}
      <div
        role="tablist"
        aria-label="Coding question"
        className="mb-5 flex flex-wrap gap-1 border-b"
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={`panel-${t.key}`}
            onClick={() => setParams({ tab: t.key }, { replace: true })}
            className={cn(
              "-mb-px border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              tab === t.key
                ? "border-selection text-foreground"
                : "text-muted-foreground hover:text-foreground border-transparent",
            )}
          >
            {t.label}
            {t.key === "tests" && ` (${coding.test_case_count})`}
          </button>
        ))}
      </div>
      <Panel name="problem" tab={tab}>
        <div className="space-y-6">
          {problem}
          <FormatsCard question={question} coding={coding} />
        </div>
      </Panel>
      <Panel name="languages" tab={tab}>
        <LanguagesTab key={version.id} question={question} coding={coding} />
      </Panel>
      <Panel name="tests" tab={tab}>
        <TestCasesTab question={question} coding={coding} />
      </Panel>
      <Panel name="validate" tab={tab}>
        <ValidateTab key={version.id} question={question} coding={coding} />
      </Panel>
    </section>
  );
}

function Panel({ name, tab, children }: { name: Tab; tab: Tab; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${name}`} aria-labelledby={`tab-${name}`} hidden={tab !== name}>
      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: CodingView["validation_status"] }) {
  const tone = {
    PASSED: "bg-success-soft text-success border-success/40",
    FAILED: "bg-danger-soft text-destructive border-destructive/40",
    VALIDATING: "bg-selection-soft text-foreground",
    NEEDS_VALIDATION: "bg-warning-soft text-warning border-warning/40",
  }[status];
  return (
    <Badge variant="outline" className={tone}>
      {statusText[status]}
    </Badge>
  );
}

function Card({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="bg-card shadow-card space-y-4 rounded-xl border p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{title}</h2>
        {actions}
      </div>
      {children}
    </div>
  );
}

/** Saves the whole coding setup (PUT replaces it), then shows the saved question. */
function useSaveCoding(question: Question) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CodingIn) => {
      const result = await api.PUT("/api/v1/questions/{question_id}/coding", {
        params: { path: { question_id: question.id } },
        body,
      });
      return {
        saved: unwrap(result),
        newVersion: result.response.headers.get("X-New-Version") === "true",
      };
    },
    onSuccess: ({ saved }) => {
      queryClient.setQueryData(["questions", question.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["questions", question.id, "test-cases"] });
    },
  });
}

function savedNotice(newVersion: boolean, question: Question): string {
  return newVersion
    ? `Saved as version ${question.version.version_no + 1}. Published exams keep the old one.`
    : "Saved.";
}

// ----------------------------------------------------------------------------- Problem

function FormatsCard({ question, coding }: { question: Question; coding: CodingView }) {
  const [draft, setDraft] = useState({
    input_format: coding.input_format,
    output_format: coding.output_format,
    constraints: coding.constraints,
  });
  const save = useSaveCoding(question);
  const changed =
    draft.input_format !== coding.input_format ||
    draft.output_format !== coding.output_format ||
    draft.constraints !== coding.constraints;
  const fields = [
    { key: "input_format", label: "Input format", hint: "e.g. Two integers a and b on one line." },
    { key: "output_format", label: "Output format", hint: "e.g. Their sum." },
    { key: "constraints", label: "Constraints", hint: "e.g. -10⁹ ≤ a, b ≤ 10⁹" },
  ] as const;
  return (
    <Card
      title="Input, output and constraints"
      actions={
        <Button
          size="sm"
          disabled={!changed || save.isPending}
          onClick={() => save.mutate(codingBody(coding, draft))}
        >
          <Busy busy={save.isPending}>Save</Busy>
        </Button>
      }
    >
      {save.isSuccess && !changed && (
        <FormMessage tone="success">{savedNotice(save.data.newVersion, question)}</FormMessage>
      )}
      {save.isError && <FormMessage tone="error">{errorText(save.error)}</FormMessage>}
      {fields.map((f) => (
        <Field key={f.key} label={`${f.label} (Markdown)`}>
          {(props) => (
            <Textarea
              {...props}
              rows={3}
              placeholder={f.hint}
              value={draft[f.key]}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          )}
        </Field>
      ))}
      <p className="text-muted-foreground text-sm">
        Examples: students see your <strong>public</strong> test cases in full as examples. Add them
        on the Test cases tab.
      </p>
    </Card>
  );
}

// ----------------------------------------------------------------------------- Languages & limits

function useLanguages() {
  return useQuery({
    queryKey: ["languages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/languages")),
    staleTime: Infinity,
  });
}

function LanguagesTab({ question, coding }: { question: Question; coding: CodingView }) {
  const languages = useLanguages();
  const save = useSaveCoding(question);
  const [starter, setStarter] = useState<Record<string, string>>(
    Object.fromEntries(coding.allowed_languages.map((l) => [l.language_key, l.starter_code ?? ""])),
  );
  const [order, setOrder] = useState<string[]>(coding.allowed_languages.map((l) => l.language_key));
  const [settings, setSettings] = useState({
    time_limit_ms: String(coding.time_limit_ms),
    memory_limit_mb: String(coding.memory_limit_mb),
    comparison_mode: coding.comparison_mode,
    partial_scoring: coding.partial_scoring,
    run_code_allowed: coding.run_code_allowed,
    max_submissions: String(coding.max_submissions),
  });
  const set = <K extends keyof typeof settings>(key: K, value: (typeof settings)[K]) =>
    setSettings((s) => ({ ...s, [key]: value }));

  if (languages.isPending) return <LoadingRows rows={4} />;
  if (languages.isError)
    return <FormMessage tone="error">{errorText(languages.error)}</FormMessage>;

  const toggle = (key: string, on: boolean) => {
    setOrder((o) => (on ? [...o, key] : o.filter((k) => k !== key)));
    if (on && !(key in starter)) setStarter((s) => ({ ...s, [key]: "" }));
  };
  const timeMs = Number(settings.time_limit_ms) || 0;
  const body = codingBody(coding, {
    allowed_languages: order.map((key) => ({
      language_key: key,
      starter_code: starter[key] ?? "",
    })),
    time_limit_ms: timeMs,
    memory_limit_mb: Number(settings.memory_limit_mb) || 0,
    comparison_mode: settings.comparison_mode,
    partial_scoring: settings.partial_scoring,
    run_code_allowed: settings.run_code_allowed,
    max_submissions: Number(settings.max_submissions) || 0,
  });
  const changed = JSON.stringify(body) !== JSON.stringify(codingBody(coding, {}));
  const errors = Object.fromEntries(
    (
      (save.error as { error?: { details?: { field?: string; message: string }[] } } | null)?.error
        ?.details ?? []
    ).map((d) => [(d.field ?? "").split(".").slice(-1)[0], d.message]),
  );

  return (
    <div className="space-y-6">
      {save.isSuccess && !changed && (
        <FormMessage tone="success">{savedNotice(save.data.newVersion, question)}</FormMessage>
      )}
      {save.isError && <FormMessage tone="error">{errorText(save.error)}</FormMessage>}
      <Card title="Languages">
        <p className="text-muted-foreground text-sm">
          Students may use the ones you tick. Starter code is what their editor opens with.
        </p>
        {languages.data.map((lang) => {
          const on = order.includes(lang.key);
          return (
            <div key={lang.key} className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <Checkbox checked={on} onCheckedChange={(v) => toggle(lang.key, v === true)} />
                {lang.display_name}
                <span className="text-muted-foreground font-normal">
                  · gets {effectiveMs(timeMs, lang.time_multiplier)} ms
                  {lang.time_multiplier !== 1 && ` (${lang.time_multiplier}× the limit)`}
                </span>
              </label>
              {on && (
                <CodeEditor
                  language={lang.key}
                  label={`Starter code, ${lang.display_name}`}
                  value={starter[lang.key] ?? ""}
                  onChange={(v) => setStarter((s) => ({ ...s, [lang.key]: v }))}
                  className="[&_.cm-editor]:min-h-24"
                />
              )}
            </div>
          );
        })}
      </Card>
      <Card title="Limits and marking">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Time limit (ms, 100–10,000)" error={errors.time_limit_ms}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={100}
                max={10000}
                step={100}
                value={settings.time_limit_ms}
                onChange={(e) => set("time_limit_ms", e.target.value)}
              />
            )}
          </Field>
          <Field label="Memory limit (MB, 16–512)" error={errors.memory_limit_mb}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={16}
                max={512}
                value={settings.memory_limit_mb}
                onChange={(e) => set("memory_limit_mb", e.target.value)}
              />
            )}
          </Field>
          <Field label="Submissions per student (1–100)" error={errors.max_submissions}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={1}
                max={100}
                value={settings.max_submissions}
                onChange={(e) => set("max_submissions", e.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="Comparing output">
          {(props) => (
            <Select
              value={settings.comparison_mode}
              onValueChange={(v) => set("comparison_mode", v as ComparisonMode)}
            >
              <SelectTrigger {...props} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(comparisonText) as ComparisonMode[]).map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {comparisonText[mode]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <Checkbox
            checked={settings.partial_scoring}
            onCheckedChange={(v) => set("partial_scoring", v === true)}
          />
          <span>
            <span className="font-medium">Partial marks</span>
            <span className="text-muted-foreground block">
              Marks for each test passed, by weight. Off: full marks only if every test passes.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm">
          <Checkbox
            checked={settings.run_code_allowed}
            onCheckedChange={(v) => set("run_code_allowed", v === true)}
          />
          <span>
            <span className="font-medium">Run Code allowed</span>
            <span className="text-muted-foreground block">
              Students can try their code on the public test cases before submitting.
            </span>
          </span>
        </label>
      </Card>
      <div className="flex gap-2">
        <Button disabled={!changed || save.isPending} onClick={() => save.mutate(body)}>
          <Busy busy={save.isPending}>Save languages and limits</Busy>
        </Button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- Test cases

interface CaseDraft {
  id: string | null;
  visibility: "PUBLIC" | "HIDDEN";
  weight: string;
  input: string;
  expected_output: string;
}

function TestCasesTab({ question, coding }: { question: Question; coding: CodingView }) {
  const queryClient = useQueryClient();
  const qid = question.id;
  const cases = useQuery({
    queryKey: ["questions", qid, "test-cases"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/questions/{question_id}/test-cases", {
          params: { path: { question_id: qid } },
        }),
      ),
  });
  const [editing, setEditing] = useState<CaseDraft | null>(null);
  const [removing, setRemoving] = useState<TestCase | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["questions", qid] });
  };

  const saveCase = useMutation({
    mutationFn: async (draft: CaseDraft) => {
      const body = {
        visibility: draft.visibility,
        weight: Number(draft.weight) || 0,
        input: draft.input,
        expected_output: draft.expected_output,
      };
      if (draft.id) {
        return unwrap(
          await api.PATCH("/api/v1/questions/{question_id}/test-cases/{case_id}", {
            params: { path: { question_id: qid, case_id: draft.id } },
            body,
          }),
        );
      }
      return unwrap(
        await api.POST("/api/v1/questions/{question_id}/test-cases", {
          params: { path: { question_id: qid } },
          body,
        }),
      );
    },
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE("/api/v1/questions/{question_id}/test-cases/{case_id}", {
          params: { path: { question_id: qid, case_id: id } },
        }),
      ),
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
  });
  const reorder = useMutation({
    mutationFn: async (ids: string[]) =>
      unwrap(
        await api.PUT("/api/v1/questions/{question_id}/test-cases/order", {
          params: { path: { question_id: qid } },
          body: { ids },
        }),
      ),
    onSuccess: refresh,
  });

  if (cases.isPending) return <LoadingRows rows={4} />;
  if (cases.isError) return <FormMessage tone="error">{errorText(cases.error)}</FormMessage>;
  const list = cases.data;
  const total = list.reduce((sum, c) => sum + c.weight, 0);
  const move = (i: number, by: -1 | 1) => {
    const ids = list.map((c) => c.id);
    const [id] = ids.splice(i, 1);
    if (id) ids.splice(i + by, 0, id);
    reorder.mutate(ids);
  };
  const busy = reorder.isPending || remove.isPending;

  return (
    <div className="space-y-4">
      {coding.hidden_test_case_count === 0 && (
        <FormMessage tone="error">
          Add at least one hidden test case: without one the question can't be validated or
          published.
        </FormMessage>
      )}
      {(reorder.isError || remove.isError) && (
        <FormMessage tone="error">{errorText(reorder.error ?? remove.error)}</FormMessage>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-muted-foreground text-sm">
          {list.length} of 50 · total weight {total}. Public cases are the examples students see;
          hidden ones are never shown.
        </p>
        <Button
          disabled={list.length >= 50}
          onClick={() =>
            setEditing({
              id: null,
              visibility: list.length ? "HIDDEN" : "PUBLIC",
              weight: "1",
              input: "",
              expected_output: "",
            })
          }
        >
          <Plus /> Add test case
        </Button>
      </div>
      <div className="bg-card shadow-card overflow-x-auto rounded-xl border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-muted-foreground text-left">
            <tr>
              <th className="px-4 py-2.5 font-medium">#</th>
              <th className="px-4 py-2.5 font-medium">Shown to students</th>
              <th className="px-4 py-2.5 font-medium">Weight</th>
              <th className="px-4 py-2.5 font-medium">Input</th>
              <th className="px-4 py-2.5 font-medium">Expected output</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {list.length === 0 && (
              <tr>
                <td colSpan={6} className="text-muted-foreground px-4 py-6 text-center">
                  No test cases yet.
                </td>
              </tr>
            )}
            {list.map((c, i) => (
              <tr key={c.id} className="border-t">
                <td className="px-4 py-2 tabular-nums">{i + 1}</td>
                <td className="px-4 py-2">
                  {c.visibility === "PUBLIC" ? (
                    <Badge variant="outline">Public example</Badge>
                  ) : (
                    <Badge variant="secondary">Hidden</Badge>
                  )}
                </td>
                <td className="px-4 py-2 tabular-nums">{c.weight}</td>
                <td className="text-muted-foreground px-4 py-2 font-mono text-xs">
                  {sizeText(c.input)}
                </td>
                <td className="text-muted-foreground px-4 py-2 font-mono text-xs">
                  {sizeText(c.expected_output)}
                </td>
                <td className="px-2 py-1">
                  <div className="flex justify-end">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Move test ${i + 1} up`}
                      disabled={i === 0 || busy}
                      onClick={() => move(i, -1)}
                    >
                      <ArrowUp />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Move test ${i + 1} down`}
                      disabled={i === list.length - 1 || busy}
                      onClick={() => move(i, 1)}
                    >
                      <ArrowDown />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Edit test ${i + 1}`}
                      onClick={() =>
                        setEditing({
                          id: c.id,
                          visibility: c.visibility,
                          weight: String(c.weight),
                          input: c.input,
                          expected_output: c.expected_output,
                        })
                      }
                    >
                      <Pencil />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Delete test ${i + 1}`}
                      disabled={busy}
                      onClick={() => setRemoving(c)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="sm:max-w-2xl">
          {editing && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                saveCase.mutate(editing);
              }}
              className="space-y-4"
            >
              <DialogHeader>
                <DialogTitle>{editing.id ? "Edit test case" : "New test case"}</DialogTitle>
                <DialogDescription>
                  The program gets the input on standard input; its output is compared with the
                  expected output.
                </DialogDescription>
              </DialogHeader>
              {saveCase.isError && (
                <FormMessage tone="error">{errorText(saveCase.error)}</FormMessage>
              )}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Shown to students">
                  {(props) => (
                    <Select
                      value={editing.visibility}
                      onValueChange={(v) =>
                        setEditing({ ...editing, visibility: v as CaseDraft["visibility"] })
                      }
                    >
                      <SelectTrigger {...props} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="PUBLIC">Public: shown as an example</SelectItem>
                        <SelectItem value="HIDDEN">Hidden: never shown</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                </Field>
                <Field label="Weight (1–1000)">
                  {(props) => (
                    <Input
                      {...props}
                      type="number"
                      min={1}
                      max={1000}
                      value={editing.weight}
                      onChange={(e) => setEditing({ ...editing, weight: e.target.value })}
                    />
                  )}
                </Field>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Input">
                  {(props) => (
                    <Textarea
                      {...props}
                      rows={8}
                      className="font-mono text-sm"
                      value={editing.input}
                      onChange={(e) => setEditing({ ...editing, input: e.target.value })}
                    />
                  )}
                </Field>
                <Field label="Expected output">
                  {(props) => (
                    <Textarea
                      {...props}
                      rows={8}
                      className="font-mono text-sm"
                      value={editing.expected_output}
                      onChange={(e) => setEditing({ ...editing, expected_output: e.target.value })}
                    />
                  )}
                </Field>
              </div>
              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => setEditing(null)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={saveCase.isPending}>
                  <Busy busy={saveCase.isPending}>{editing.id ? "Save" : "Add"}</Busy>
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Delete this test case?"
        description="The question will need validating again."
        confirmLabel="Delete"
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </div>
  );
}

// ----------------------------------------------------------------------------- Validate

function ValidateTab({ question, coding }: { question: Question; coding: CodingView }) {
  const queryClient = useQueryClient();
  const languages = useLanguages();
  const allowed = coding.allowed_languages.map((l) => l.language_key);
  const saved = Object.fromEntries(
    coding.reference_solutions.map((r) => [r.language_key, r.source]),
  );
  const [language, setLanguage] = useState(allowed.find((k) => k in saved) ?? allowed[0] ?? "");
  const [sources, setSources] = useState<Record<string, string>>(saved);
  const name = (key: string) => languages.data?.find((l) => l.key === key)?.display_name ?? key;
  const show = (q: Question) => queryClient.setQueryData(["questions", question.id], q);

  const saveReference = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/questions/{question_id}/reference-solutions/{language_key}", {
          params: { path: { question_id: question.id, language_key: language } },
          body: { source: sources[language] ?? "" },
        }),
      ),
    onSuccess: show,
  });
  const validate = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/questions/{question_id}/validate", {
          params: { path: { question_id: question.id } },
        }),
      ),
    onSuccess: show,
  });

  const unsaved = (sources[language] ?? "") !== (saved[language] ?? "");
  const report = coding.validation_report as ValidationReport | null;
  const running = coding.validation_status === "VALIDATING";

  return (
    <div className="space-y-6">
      <Card title="Reference solution">
        {allowed.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Choose languages first (Languages & limits).
          </p>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">
              Your own correct program. Validation runs every saved one on every test case; all must
              pass.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger className="w-64" aria-label="Language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {allowed.map((key) => (
                    <SelectItem key={key} value={key}>
                      {name(key)}
                      {key in saved ? " · saved" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                size="sm"
                disabled={!unsaved || !(sources[language] ?? "").trim() || saveReference.isPending}
                onClick={() => saveReference.mutate()}
              >
                <Busy busy={saveReference.isPending}>Save solution</Busy>
              </Button>
            </div>
            {saveReference.isError && (
              <FormMessage tone="error">{errorText(saveReference.error)}</FormMessage>
            )}
            {language && (
              <CodeEditor
                key={language}
                language={language}
                label={`Reference solution, ${name(language)}`}
                value={sources[language] ?? ""}
                onChange={(v) => setSources((s) => ({ ...s, [language]: v }))}
                className="[&_.cm-editor]:min-h-56"
              />
            )}
          </>
        )}
      </Card>

      <Card
        title="Validation"
        actions={
          <Button
            disabled={coding.blocks.length > 0 || running || validate.isPending || unsaved}
            onClick={() => validate.mutate()}
          >
            <Busy busy={validate.isPending || running}>
              <Play /> {running ? "Validating…" : "Validate"}
            </Busy>
          </Button>
        }
      >
        <p className="flex items-center gap-2 text-sm">
          Status: <StatusBadge status={coding.validation_status} />
        </p>
        {unsaved && <p className="text-warning text-sm">Save the solution first.</p>}
        {coding.blocks.length > 0 && (
          <ul className="text-warning list-disc space-y-1 pl-5 text-sm">
            {coding.blocks.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        )}
        {validate.isError && <FormMessage tone="error">{errorText(validate.error)}</FormMessage>}
        {coding.validation_status === "NEEDS_VALIDATION" && coding.blocks.length === 0 && (
          <p className="text-muted-foreground text-sm">
            Ready. Validate after any change to the tests, limits or solutions; exams can't be
            published until it passes.
          </p>
        )}
        {report && <Report report={report} name={name} />}
      </Card>
    </div>
  );
}

function Report({ report, name }: { report: ValidationReport; name: (key: string) => string }) {
  return (
    <div className="space-y-5">
      {(report.warnings ?? []).length > 0 && (
        <div className="bg-warning-soft space-y-1 rounded-lg p-3 text-sm">
          {report.warnings?.map((w) => (
            <p key={w} className="flex items-start gap-2">
              <AlertTriangle className="text-warning mt-0.5 size-4 shrink-0" aria-hidden /> {w}
            </p>
          ))}
        </div>
      )}
      {report.pending.map((key) => (
        <p key={key} className="text-muted-foreground text-sm">
          {name(key)}: running…
        </p>
      ))}
      {Object.entries(report.languages).map(([key, lang]) => (
        <div key={key} className="space-y-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            {lang.status === "PASSED" ? (
              <CheckCircle2 className="text-success size-4" aria-hidden />
            ) : (
              <XCircle className="text-destructive size-4" aria-hidden />
            )}
            {name(key)}:{" "}
            {lang.status === "PASSED"
              ? "every test passed"
              : lang.status === "ERROR"
                ? "couldn't run"
                : "failed"}
            <span className="text-muted-foreground font-normal">
              · limit {lang.time_limit_ms} ms
            </span>
          </h3>
          {lang.error && <p className="text-destructive text-sm">{lang.error}</p>}
          {lang.compile_output && lang.cases.length === 0 && (
            <pre className="bg-muted max-h-48 overflow-auto rounded-lg p-3 text-xs whitespace-pre-wrap">
              {lang.compile_output}
            </pre>
          )}
          {lang.cases.length > 0 && (
            <table className="w-full text-sm">
              <thead className="text-muted-foreground text-left">
                <tr>
                  <th className="py-1 pr-4 font-medium">Test</th>
                  <th className="py-1 pr-4 font-medium">Result</th>
                  <th className="py-1 pr-4 font-medium">Time</th>
                  <th className="py-1 font-medium">Memory</th>
                </tr>
              </thead>
              <tbody>
                {lang.cases.map((c) => (
                  <tr key={c.name} className="border-t align-top">
                    <td className="py-1.5 pr-4 tabular-nums">
                      {Number(c.name)}{" "}
                      {c.hidden ? <span className="text-muted-foreground">(hidden)</span> : null}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 pr-4",
                        c.outcome === "PASSED" ? "text-success" : "text-destructive",
                      )}
                    >
                      {outcomeText[c.outcome] ?? c.outcome}
                      {c.stdout !== null && c.outcome !== "PASSED" && (
                        <span className="text-muted-foreground block font-mono text-xs">
                          printed: {c.stdout.slice(0, 120) || "(nothing)"}
                        </span>
                      )}
                    </td>
                    <td className="py-1.5 pr-4 tabular-nums">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1",
                          c.slow && "text-warning font-medium",
                        )}
                      >
                        {c.slow && (
                          <AlertTriangle
                            className="size-3.5"
                            aria-label="Over half the time limit"
                          />
                        )}
                        {c.time_ms} ms
                      </span>
                    </td>
                    <td className="text-muted-foreground py-1.5">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}
