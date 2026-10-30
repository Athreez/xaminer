import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useLocation } from "react-router";

import { api } from "@/api/client";
import { Field, FormMessage } from "@/components/form";
import { Busy } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { errorText, unwrap } from "@/lib/api";
import { fieldErrors } from "@/features/questions/lib";

import { useExam } from "./context";
import { fromLocalInput, toLocalInput, type Exam } from "./lib";

interface Form {
  title: string;
  instructions: string;
  open_at: string;
  close_at: string;
  duration_min: string;
  navigation_mode: Exam["navigation_mode"];
  shuffle_questions: boolean;
  shuffle_options: boolean;
  run_code_enabled: boolean;
  counted_submission: Exam["counted_submission"];
  release_policy: Exam["release_policy"];
  pass_percent: string;
  proctoring_mode: Exam["proctoring_mode"];
  sensitivity: Exam["proctoring_detectors"]["sensitivity"];
  gaze: boolean;
  books: boolean;
  consent_text: string;
}

function formOf(exam: Exam): Form {
  return {
    title: exam.title,
    instructions: exam.instructions,
    open_at: toLocalInput(exam.open_at),
    close_at: toLocalInput(exam.close_at),
    duration_min: exam.duration_min ? String(exam.duration_min) : "",
    navigation_mode: exam.navigation_mode,
    shuffle_questions: exam.shuffle_questions,
    shuffle_options: exam.shuffle_options,
    run_code_enabled: exam.run_code_enabled,
    counted_submission: exam.counted_submission,
    release_policy: exam.release_policy,
    pass_percent: exam.pass_percent ? String(Number(exam.pass_percent)) : "",
    proctoring_mode: exam.proctoring_mode,
    sensitivity: exam.proctoring_detectors.sensitivity,
    gaze: exam.proctoring_detectors.gaze,
    books: exam.proctoring_detectors.books,
    consent_text: exam.consent_text ?? "",
  };
}

/** What the API takes, from the form. */
function body(form: Form) {
  return {
    title: form.title,
    instructions: form.instructions,
    open_at: fromLocalInput(form.open_at),
    close_at: fromLocalInput(form.close_at),
    duration_min: form.duration_min ? Number(form.duration_min) : null,
    navigation_mode: form.navigation_mode,
    shuffle_questions: form.shuffle_questions,
    shuffle_options: form.shuffle_options,
    run_code_enabled: form.run_code_enabled,
    counted_submission: form.counted_submission,
    release_policy: form.release_policy,
    pass_percent: form.pass_percent || null,
    proctoring_mode: form.proctoring_mode,
    proctoring_detectors: { sensitivity: form.sensitivity, gaze: form.gaze, books: form.books },
    consent_text: form.consent_text.trim() || null,
  };
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="bg-card shadow-card space-y-4 rounded-xl border p-6">
      <legend className="sr-only">{title}</legend>
      <div>
        <h2 className="font-semibold">{title}</h2>
        {hint && <p className="text-muted-foreground text-sm">{hint}</p>}
      </div>
      {children}
    </fieldset>
  );
}

function Toggle({
  id,
  label,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label id={id} htmlFor={`${id}-box`} className="flex items-center gap-2 text-sm">
      <Checkbox
        id={`${id}-box`}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(on) => onChange(on === true)}
      />
      {label}
    </label>
  );
}

/** All exam settings, grouped (FRONTEND_SPEC § 5.4, PRD § 6.3). Locked after publish except the
 * window's end. */
export function ExamSettingsPage() {
  const { exam, draft, refresh } = useExam();
  const location = useLocation();
  const initial = formOf(exam);
  const [form, setForm] = useState<Form>(initial);
  const [saved, setSaved] = useState(false);
  const locked = !draft; // published or archived
  const canEndLater = exam.status === "PUBLISHED";

  // Jump to the setting a publish-check link points at (#duration_min).
  useEffect(() => {
    const id = location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView({ block: "center" });
  }, [location.hash]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setSaved(false);
    setForm((f) => ({ ...f, [key]: value }));
  };

  const save = useMutation({
    mutationFn: async () => {
      const next = body(form);
      const before = body(initial);
      // Only what changed: a published exam accepts just close_at.
      const changes = Object.fromEntries(
        Object.entries(next).filter(
          ([key, value]) =>
            JSON.stringify(value) !== JSON.stringify(before[key as keyof typeof before]),
        ),
      );
      return unwrap(
        await api.PATCH("/api/v1/exams/{exam_id}", {
          params: { path: { exam_id: exam.id } },
          body: changes,
        }),
      );
    },
    onSuccess: () => {
      setSaved(true);
      refresh();
    },
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const errors = fieldErrors(save.error);
  const changed = JSON.stringify(body(form)) !== JSON.stringify(body(initial));
  const lockedField = (field: keyof Form) => locked && !(canEndLater && field === "close_at");

  return (
    <form onSubmit={onSubmit} className="space-y-6" noValidate>
      {exam.status === "PUBLISHED" && (
        <FormMessage tone="info">
          The exam is published, so its settings are fixed. Only the window's end can still change.
        </FormMessage>
      )}
      {exam.status === "ARCHIVED" && (
        <FormMessage tone="info">This exam is archived and can't be changed.</FormMessage>
      )}
      {saved && !changed && <FormMessage tone="success">Settings saved.</FormMessage>}
      {save.isError && Object.keys(errors).length === 0 && (
        <FormMessage tone="error">{errorText(save.error)}</FormMessage>
      )}

      <Group title="Schedule" hint="When students can take it, and for how long.">
        <div id="title">
          <Field label="Title" error={errors.title}>
            {(props) => (
              <Input
                {...props}
                disabled={lockedField("title")}
                value={form.title}
                onChange={(e) => set("title", e.target.value)}
              />
            )}
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <div id="open_at">
            <Field label="Opens" error={errors.open_at}>
              {(props) => (
                <Input
                  {...props}
                  type="datetime-local"
                  disabled={lockedField("open_at")}
                  value={form.open_at}
                  onChange={(e) => set("open_at", e.target.value)}
                />
              )}
            </Field>
          </div>
          <div id="close_at">
            <Field label="Closes" error={errors.close_at}>
              {(props) => (
                <Input
                  {...props}
                  type="datetime-local"
                  disabled={lockedField("close_at")}
                  min={form.open_at || undefined}
                  value={form.close_at}
                  onChange={(e) => set("close_at", e.target.value)}
                />
              )}
            </Field>
          </div>
          <div id="duration_min">
            <Field label="Duration (minutes)" error={errors.duration_min}>
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={1}
                  max={600}
                  disabled={lockedField("duration_min")}
                  value={form.duration_min}
                  onChange={(e) => set("duration_min", e.target.value)}
                />
              )}
            </Field>
          </div>
        </div>
        <p className="text-muted-foreground text-xs">
          Times are in your computer's time zone. Each student gets the full duration, cut short
          only by the window's end.
        </p>
        <div id="instructions">
          <Field label="Instructions (Markdown, shown before starting)" error={errors.instructions}>
            {(props) => (
              <Textarea
                {...props}
                rows={4}
                disabled={lockedField("instructions")}
                value={form.instructions}
                onChange={(e) => set("instructions", e.target.value)}
              />
            )}
          </Field>
        </div>
      </Group>

      <Group title="Navigation">
        <div id="navigation_mode">
          <Field label="Moving between questions">
            {(props) => (
              <Select
                value={form.navigation_mode}
                disabled={locked}
                onValueChange={(v) => set("navigation_mode", v as Form["navigation_mode"])}
              >
                <SelectTrigger {...props} className="w-full sm:w-96">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="FREE">Free: any order, can go back</SelectItem>
                  <SelectItem value="SEQUENTIAL">Sequential: in order, no going back</SelectItem>
                </SelectContent>
              </Select>
            )}
          </Field>
        </div>
        <Toggle
          id="shuffle_questions"
          label="Shuffle question order for each student"
          checked={form.shuffle_questions}
          disabled={locked}
          onChange={(on) => set("shuffle_questions", on)}
        />
        <Toggle
          id="shuffle_options"
          label="Shuffle answer options for each student"
          checked={form.shuffle_options}
          disabled={locked}
          onChange={(on) => set("shuffle_options", on)}
        />
      </Group>

      <Group title="Coding" hint="Only matters if the exam has coding questions.">
        <Toggle
          id="run_code_enabled"
          label="Students can run their code against the example tests"
          checked={form.run_code_enabled}
          disabled={locked}
          onChange={(on) => set("run_code_enabled", on)}
        />
        <div id="counted_submission">
          <Field label="Which submission counts">
            {(props) => (
              <Select
                value={form.counted_submission}
                disabled={locked}
                onValueChange={(v) => set("counted_submission", v as Form["counted_submission"])}
              >
                <SelectTrigger {...props} className="w-full sm:w-96">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="BEST">The best one</SelectItem>
                  <SelectItem value="LAST">The last one</SelectItem>
                </SelectContent>
              </Select>
            )}
          </Field>
        </div>
      </Group>

      <Group title="Results">
        <div className="grid gap-4 sm:grid-cols-2">
          <div id="release_policy">
            <Field label="Results are shown to students">
              {(props) => (
                <Select
                  value={form.release_policy}
                  disabled={locked}
                  onValueChange={(v) => set("release_policy", v as Form["release_policy"])}
                >
                  <SelectTrigger {...props} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MANUAL">When I release them</SelectItem>
                    <SelectItem value="ON_SUBMIT">Right after submitting</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </Field>
          </div>
          <div id="pass_percent">
            <Field label="Pass mark (%, optional)" error={errors.pass_percent}>
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={0}
                  max={100}
                  disabled={lockedField("pass_percent")}
                  value={form.pass_percent}
                  onChange={(e) => set("pass_percent", e.target.value)}
                />
              )}
            </Field>
          </div>
        </div>
      </Group>

      <Group
        title="Proctoring"
        hint="The AI only flags moments for you to review; it never decides anything."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div id="proctoring_mode">
            <Field label="Mode">
              {(props) => (
                <Select
                  value={form.proctoring_mode}
                  disabled={locked}
                  onValueChange={(v) => set("proctoring_mode", v as Form["proctoring_mode"])}
                >
                  <SelectTrigger {...props} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="OFF">Off</SelectItem>
                    <SelectItem value="VIDEO">Webcam</SelectItem>
                    <SelectItem value="VIDEO_AUDIO">Webcam and microphone</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </Field>
          </div>
          <div id="sensitivity">
            <Field label="Sensitivity">
              {(props) => (
                <Select
                  value={form.sensitivity}
                  disabled={locked || form.proctoring_mode === "OFF"}
                  onValueChange={(v) => set("sensitivity", v as Form["sensitivity"])}
                >
                  <SelectTrigger {...props} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="RELAXED">Relaxed: fewer flags</SelectItem>
                    <SelectItem value="STANDARD">Standard</SelectItem>
                    <SelectItem value="STRICT">Strict: flags sooner</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </Field>
          </div>
        </div>
        <Toggle
          id="gaze"
          label="Flag looking away from the screen for a long time"
          checked={form.gaze}
          disabled={locked || form.proctoring_mode === "OFF"}
          onChange={(on) => set("gaze", on)}
        />
        <Toggle
          id="books"
          label="Flag books (closed-book exam)"
          checked={form.books}
          disabled={locked || form.proctoring_mode === "OFF"}
          onChange={(on) => set("books", on)}
        />
        <div id="consent_text">
          <Field
            label="Consent text (empty: the institution's default, or the standard text)"
            error={errors.consent_text}
          >
            {(props) => (
              <Textarea
                {...props}
                rows={4}
                disabled={lockedField("consent_text")}
                placeholder="Students read and accept this before a proctored exam."
                value={form.consent_text}
                onChange={(e) => set("consent_text", e.target.value)}
              />
            )}
          </Field>
        </div>
      </Group>

      {exam.status !== "ARCHIVED" && (
        <div className="flex gap-2">
          <Button type="submit" disabled={!changed || save.isPending}>
            <Busy busy={save.isPending}>Save settings</Busy>
          </Button>
          {changed && (
            <Button type="button" variant="ghost" onClick={() => setForm(initial)}>
              Undo changes
            </Button>
          )}
        </div>
      )}
    </form>
  );
}
