import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Copy,
  Eye,
  ImagePlus,
  Plus,
  Trash2,
} from "lucide-react";
import { useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { MarkdownView } from "@/components/MarkdownView";
import { Field, FormMessage } from "@/components/form";
import { Busy, ErrorState, LoadingRows, NotFoundBlock, PageHeader } from "@/components/page";
import { Badge } from "@/components/ui/badge";
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
import { errorText, formatDateTime, isNotFound, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { CodingEditor } from "./coding/CodingEditor";

import {
  EDITABLE_TYPES,
  fieldErrors,
  insertAt,
  parseTags,
  typeHint,
  typeLabel,
  visibilityLabel,
  type Question,
  type QuestionType,
  type Visibility,
} from "./lib";

interface OptionDraft {
  key: number;
  label: string;
  is_correct: boolean;
}

interface Draft {
  type: QuestionType;
  visibility: Visibility;
  tags: string;
  body: string;
  points: string;
  negative_marks: string;
  msq_scoring: "ALL_OR_NOTHING" | "PARTIAL";
  max_answer_length: string;
  rubric: string;
  options: OptionDraft[];
}

let nextKey = 1;
const option = (label = "", is_correct = false): OptionDraft => ({
  key: nextKey++,
  label,
  is_correct,
});

function startingOptions(type: QuestionType): OptionDraft[] {
  if (type === "TRUE_FALSE") return [option("True", true), option("False")];
  if (type === "MCQ" || type === "MSQ") return [option(), option(), option(), option()];
  return [];
}

function emptyDraft(type: QuestionType): Draft {
  return {
    type,
    visibility: "PRIVATE",
    tags: "",
    body: "",
    points: "1",
    negative_marks: "0",
    msq_scoring: "ALL_OR_NOTHING",
    max_answer_length: "",
    rubric: "",
    options: startingOptions(type),
  };
}

function draftOf(question: Question): Draft {
  const v = question.version;
  return {
    type: question.type,
    visibility: question.visibility,
    tags: question.tags.join(", "),
    body: v.body,
    points: String(Number(v.points)),
    negative_marks: String(Number(v.negative_marks)),
    msq_scoring: v.msq_scoring ?? "ALL_OR_NOTHING",
    max_answer_length: v.max_answer_length ? String(v.max_answer_length) : "",
    rubric: v.rubric ?? "",
    options: v.options.map((o) => option(o.label, o.is_correct)),
  };
}

/** The request body: only the fields that make sense for the type. */
function payload(draft: Draft) {
  const descriptive = draft.type === "DESCRIPTIVE";
  return {
    visibility: draft.visibility,
    tags: parseTags(draft.tags),
    body: draft.body,
    points: draft.points || "0",
    // Coding questions have no negative marks (PRD § 6.2).
    negative_marks: draft.type === "CODING" ? "0" : draft.negative_marks || "0",
    msq_scoring: draft.type === "MSQ" ? draft.msq_scoring : null,
    max_answer_length:
      descriptive && draft.max_answer_length ? Number(draft.max_answer_length) : null,
    rubric: descriptive && draft.rubric.trim() ? draft.rubric : null,
    options: draft.options.map(({ label, is_correct }) => ({ label, is_correct })),
  };
}

// ------------------------------------------------------------------------------- page

/** New question, or an existing one: editable if it's yours, read-only otherwise (FRONTEND_SPEC § 5.2). */
export function QuestionEditorPage() {
  const { questionId } = useParams();
  const question = useQuery({
    enabled: Boolean(questionId),
    queryKey: ["questions", questionId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/questions/{question_id}", {
          params: { path: { question_id: questionId ?? "" } },
        }),
      ),
    // While a coding question validates, its report fills in: keep looking.
    refetchInterval: (query) =>
      query.state.data?.coding?.validation_status === "VALIDATING" ? 1500 : false,
  });

  if (!questionId) return <NewQuestion />;
  if (question.isPending) return <LoadingRows rows={8} />;
  if (question.isError) {
    if (isNotFound(question.error))
      return <NotFoundBlock what="question" back="/teacher/questions" />;
    return <ErrorState error={question.error} onRetry={() => void question.refetch()} />;
  }
  if (!question.data.is_mine) return <SharedQuestion question={question.data} />;
  // Keyed by version so the form restarts from the saved state after a new version.
  const form = (
    <QuestionForm
      key={question.data.version.id}
      question={question.data}
      embedded={question.data.type === "CODING"}
    />
  );
  if (question.data.type === "CODING") {
    return <CodingEditor question={question.data} problem={form} />;
  }
  return form;
}

function BackLink() {
  return (
    <Link
      to="/teacher/questions"
      className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
    >
      <ArrowLeft className="size-4" /> All questions
    </Link>
  );
}

function NewQuestion() {
  const [type, setType] = useState<QuestionType | null>(null);
  if (type) return <QuestionForm key={type} newType={type} onChangeType={() => setType(null)} />;
  return (
    <section className="max-w-3xl">
      <BackLink />
      <PageHeader title="New question" description="Choose the kind of question." />
      <div className="grid gap-3 sm:grid-cols-2">
        {[...EDITABLE_TYPES, "CODING" as const].map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setType(t)}
            className="bg-card shadow-card hover:border-selection rounded-xl border p-5 text-left transition-colors"
          >
            <span className="font-semibold">{typeLabel[t]}</span>
            <span className="text-muted-foreground mt-1 block text-sm">{typeHint[t]}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------- read-only

function SharedQuestion({ question }: { question: Question }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const copy = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/questions/{question_id}/copy", {
          params: { path: { question_id: question.id } },
        }),
      ),
    onSuccess: (mine) => {
      void queryClient.invalidateQueries({ queryKey: ["questions"] });
      navigate(`/teacher/questions/${mine.id}`, {
        state: { notice: "This is your own copy. Edit it as you like." },
      });
    },
  });
  const v = question.version;
  return (
    <section className="max-w-3xl">
      <BackLink />
      <PageHeader
        title={typeLabel[question.type]}
        description={`Shared by ${question.owner.full_name} · Version ${v.version_no} · Updated ${formatDateTime(question.updated_at)}`}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link to="preview">
                <Eye /> Student preview
              </Link>
            </Button>
            <Button disabled={copy.isPending} onClick={() => copy.mutate()}>
              <Busy busy={copy.isPending}>
                <Copy /> Copy to edit
              </Busy>
            </Button>
          </>
        }
      />
      {copy.isError && <FormMessage tone="error">{errorText(copy.error)}</FormMessage>}
      <div className="bg-card shadow-card space-y-5 rounded-xl border p-6">
        <p className="text-muted-foreground text-sm">
          You can use this question in your exams, or copy it to change it. Only{" "}
          {question.owner.full_name} can edit the original.
        </p>
        <MarkdownView text={v.body} images={question.image_urls} />
        {v.options.length > 0 && (
          <ul className="space-y-2">
            {v.options.map((o) => (
              <li
                key={o.id}
                className={cn(
                  "flex items-start gap-3 rounded-lg border px-3 py-2",
                  o.is_correct && "border-success bg-success-soft",
                )}
              >
                <MarkdownView text={o.label} images={question.image_urls} className="flex-1" />
                {o.is_correct && <Badge className="bg-success text-white">Correct</Badge>}
              </li>
            ))}
          </ul>
        )}
        {v.rubric && (
          <div>
            <h2 className="mb-1 text-sm font-semibold">Rubric</h2>
            <MarkdownView text={v.rubric} images={question.image_urls} />
          </div>
        )}
        <p className="text-muted-foreground text-sm">
          {Number(v.points)} marks
          {Number(v.negative_marks) > 0 && ` · −${Number(v.negative_marks)} if wrong`}
          {question.tags.length > 0 && ` · Tags: ${question.tags.join(", ")}`}
        </p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------------------- the form

function QuestionForm({
  question,
  newType,
  onChangeType,
  embedded = false,
}: {
  question?: Question;
  newType?: QuestionType;
  onChangeType?: () => void;
  /** Inside the coding editor's Problem tab, which has its own header. */
  embedded?: boolean;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const initial = question ? draftOf(question) : emptyDraft(newType ?? "MCQ");
  const [draft, setDraft] = useState<Draft>(initial);
  const [tab, setTab] = useState<"write" | "preview">("write");
  const [images, setImages] = useState<Record<string, string>>(question?.image_urls ?? {});
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice ?? null,
  );
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const version = question?.version;
  const choice = draft.type === "MCQ" || draft.type === "MSQ";

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const setOption = (key: number, change: Partial<OptionDraft>) =>
    setDraft((d) => ({
      ...d,
      options: d.options.map((o) =>
        o.key === key
          ? { ...o, ...change }
          : // Single-answer types: marking one correct unmarks the others.
            change.is_correct && d.type !== "MSQ"
            ? { ...o, is_correct: false }
            : o,
      ),
    }));
  const moveOption = (index: number, by: -1 | 1) =>
    setDraft((d) => {
      const options = [...d.options];
      const [moved] = options.splice(index, 1);
      if (moved) options.splice(index + by, 0, moved);
      return { ...d, options };
    });

  const save = useMutation({
    mutationFn: async () => {
      if (!question) {
        const created = unwrap(
          await api.POST("/api/v1/questions", { body: { ...payload(draft), type: draft.type } }),
        );
        return { saved: created, newVersion: false };
      }
      const result = await api.PATCH("/api/v1/questions/{question_id}", {
        params: { path: { question_id: question.id } },
        body: payload(draft),
      });
      return {
        saved: unwrap(result),
        newVersion: result.response.headers.get("X-New-Version") === "true",
      };
    },
    onSuccess: ({ saved, newVersion }) => {
      void queryClient.invalidateQueries({ queryKey: ["questions"] });
      if (!question) {
        navigate(`/teacher/questions/${saved.id}`, {
          replace: true,
          state: { notice: "Question created." },
        });
        return;
      }
      queryClient.setQueryData(["questions", question.id], saved);
      setNotice(
        newVersion
          ? `Saved as version ${saved.version.version_no}. Published exams keep version ${saved.version.version_no - 1}.`
          : "Saved.",
      );
      if (!newVersion) setDraft(draftOf(saved)); // show the cleaned text the server stored
    },
  });

  const archive = useMutation({
    mutationFn: async (to: "archive" | "restore") =>
      unwrap(
        await api.POST(
          to === "archive"
            ? "/api/v1/questions/{question_id}/archive"
            : "/api/v1/questions/{question_id}/restore",
          { params: { path: { question_id: question?.id ?? "" } } },
        ),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(["questions", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: ["questions"] });
      setNotice(saved.archived_at ? "Archived. It's hidden from the question list." : "Restored.");
    },
  });

  const upload = useMutation({
    mutationFn: async (file: File) =>
      unwrap(
        await api.POST("/api/v1/uploads/images", {
          body: { file: file as unknown as string },
          bodySerializer: () => {
            const form = new FormData();
            form.append("file", file);
            return form;
          },
        }),
      ),
    onSuccess: (image) => {
      setImages((prev) => ({ ...prev, [image.ref]: image.url }));
      const area = bodyRef.current;
      const start = area?.selectionStart ?? draft.body.length;
      const end = area?.selectionEnd ?? draft.body.length;
      set("body", insertAt(draft.body, start, end, `![Describe the image](${image.ref})`));
    },
  });

  function onPickImage(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) upload.mutate(file);
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setNotice(null);
    save.mutate();
  }

  const errors = fieldErrors(save.error);
  const generalError =
    save.isError && Object.keys(errors).length === 0 ? errorText(save.error) : null;
  const changed = JSON.stringify(payload(draft)) !== JSON.stringify(payload(initial));

  const coding = draft.type === "CODING";
  return (
    <section className={embedded ? undefined : "max-w-4xl"}>
      {!embedded && <BackLink />}
      {!embedded && (
        <PageHeader
          title={
            <span className="flex flex-wrap items-center gap-3">
              {question ? "Edit question" : `New ${typeLabel[draft.type].toLowerCase()} question`}
              <Badge variant="outline">{typeLabel[draft.type]}</Badge>
              {question?.archived_at && <Badge variant="outline">Archived</Badge>}
            </span>
          }
          description={
            version
              ? `Version ${version.version_no} · Updated ${formatDateTime(question.updated_at)}`
              : typeHint[draft.type]
          }
          actions={
            question ? (
              <>
                <Button variant="outline" asChild>
                  <Link to="preview">
                    <Eye /> Student preview
                  </Link>
                </Button>
                <Button
                  variant="outline"
                  disabled={archive.isPending}
                  onClick={() => archive.mutate(question.archived_at ? "restore" : "archive")}
                >
                  {question.archived_at ? (
                    <>
                      <ArchiveRestore /> Restore
                    </>
                  ) : (
                    <>
                      <Archive /> Archive
                    </>
                  )}
                </Button>
              </>
            ) : (
              onChangeType && (
                <Button variant="ghost" onClick={onChangeType}>
                  Change type
                </Button>
              )
            )
          }
        />
      )}

      <div className="mb-4 space-y-3">
        {version?.is_locked && !embedded && (
          <FormMessage tone="info">
            Saving creates a new version. Published exams keep the old one.
          </FormMessage>
        )}
        {notice && <FormMessage tone="success">{notice}</FormMessage>}
        {generalError && <FormMessage tone="error">{generalError}</FormMessage>}
        {archive.isError && <FormMessage tone="error">{errorText(archive.error)}</FormMessage>}
        {Object.keys(errors).length > 0 && (
          <FormMessage tone="error">Some fields need fixing. See the messages below.</FormMessage>
        )}
      </div>

      <form onSubmit={onSubmit} className="space-y-6" noValidate>
        {/* Question text */}
        <div className="bg-card shadow-card space-y-3 rounded-xl border p-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">{coding ? "Problem statement" : "Question"}</h2>
            <div className="flex gap-1">
              <div className="flex gap-1" role="tablist" aria-label="Question text">
                {(["write", "preview"] as const).map((t) => (
                  <Button
                    key={t}
                    type="button"
                    size="sm"
                    role="tab"
                    aria-selected={tab === t}
                    variant={tab === t ? "secondary" : "ghost"}
                    onClick={() => setTab(t)}
                  >
                    {t === "write" ? "Write" : "Preview"}
                  </Button>
                ))}
              </div>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={upload.isPending}
                onClick={() => fileRef.current?.click()}
              >
                <Busy busy={upload.isPending}>
                  <ImagePlus /> Image
                </Busy>
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="sr-only"
                aria-label="Upload an image"
                onChange={onPickImage}
              />
            </div>
          </div>
          {upload.isError && <FormMessage tone="error">{errorText(upload.error)}</FormMessage>}
          {tab === "write" ? (
            <Field label="Question text (Markdown)" error={errors.body}>
              {(props) => (
                <Textarea
                  {...props}
                  ref={bodyRef}
                  rows={10}
                  className="font-mono text-sm"
                  placeholder={
                    "What is the time complexity of binary search?\n\nUse **bold**, `code`, lists and ```code blocks```."
                  }
                  value={draft.body}
                  onChange={(e) => set("body", e.target.value)}
                />
              )}
            </Field>
          ) : (
            <div className="min-h-40 rounded-lg border p-4">
              {draft.body.trim() ? (
                <MarkdownView text={draft.body} images={images} />
              ) : (
                <p className="text-muted-foreground text-sm">Nothing to preview yet.</p>
              )}
            </div>
          )}
        </div>

        {/* Options */}
        {draft.options.length > 0 || choice ? (
          <div className="bg-card shadow-card space-y-3 rounded-xl border p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="font-semibold">Options</h2>
              <p className="text-muted-foreground text-sm">
                {draft.type === "MSQ"
                  ? "Tick every correct option."
                  : draft.type === "TRUE_FALSE"
                    ? "Pick the correct answer."
                    : "Pick the one correct option."}
              </p>
            </div>
            {errors.options && <p className="text-destructive text-sm">{errors.options}</p>}
            <ol className="space-y-2">
              {draft.options.map((o, i) => {
                const error = errors[`options.${i}.label`];
                return (
                  <li key={o.key} className="flex items-start gap-2">
                    <span className="text-muted-foreground mt-3 w-5 text-sm font-medium">
                      {String.fromCharCode(65 + i)}.
                    </span>
                    <label className="mt-3 flex items-center gap-1.5 text-sm">
                      {draft.type === "MSQ" ? (
                        <Checkbox
                          checked={o.is_correct}
                          onCheckedChange={(on) => setOption(o.key, { is_correct: on === true })}
                          aria-label={`Option ${i + 1} is correct`}
                        />
                      ) : (
                        <input
                          type="radio"
                          name="correct"
                          className="accent-selection size-4"
                          checked={o.is_correct}
                          onChange={() => setOption(o.key, { is_correct: true })}
                          aria-label={`Option ${i + 1} is correct`}
                        />
                      )}
                    </label>
                    <div className="flex-1 space-y-1">
                      {draft.type === "TRUE_FALSE" ? (
                        <p className="mt-2.5 font-medium">{o.label}</p>
                      ) : (
                        <Input
                          aria-label={`Option ${i + 1}`}
                          aria-invalid={error ? true : undefined}
                          placeholder={`Option ${i + 1}`}
                          value={o.label}
                          onChange={(e) => setOption(o.key, { label: e.target.value })}
                        />
                      )}
                      {error && <p className="text-destructive text-sm">{error}</p>}
                    </div>
                    {choice && (
                      <div className="mt-1 flex">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={i === 0}
                          aria-label={`Move option ${i + 1} up`}
                          onClick={() => moveOption(i, -1)}
                        >
                          <ArrowUp />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={i === draft.options.length - 1}
                          aria-label={`Move option ${i + 1} down`}
                          onClick={() => moveOption(i, 1)}
                        >
                          <ArrowDown />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          disabled={draft.options.length <= 2}
                          aria-label={`Remove option ${i + 1}`}
                          onClick={() =>
                            set(
                              "options",
                              draft.options.filter((x) => x.key !== o.key),
                            )
                          }
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
            {choice && draft.options.length < 10 && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => set("options", [...draft.options, option()])}
              >
                <Plus /> Add option
              </Button>
            )}
            {draft.type === "MSQ" && (
              <Field label="Marking" error={errors.msq_scoring}>
                {(props) => (
                  <Select
                    value={draft.msq_scoring}
                    onValueChange={(v) => set("msq_scoring", v as Draft["msq_scoring"])}
                  >
                    <SelectTrigger {...props} className="w-full sm:w-96">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL_OR_NOTHING">
                        All or nothing: full marks only if every choice is right
                      </SelectItem>
                      <SelectItem value="PARTIAL">
                        Partial: marks for each correct choice
                      </SelectItem>
                    </SelectContent>
                  </Select>
                )}
              </Field>
            )}
          </div>
        ) : null}

        {/* Descriptive */}
        {draft.type === "DESCRIPTIVE" && (
          <div className="bg-card shadow-card space-y-4 rounded-xl border p-6">
            <h2 className="font-semibold">Answer</h2>
            <Field
              label="Longest answer allowed (characters, optional)"
              error={errors.max_answer_length}
            >
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={1}
                  max={20000}
                  className="w-40"
                  value={draft.max_answer_length}
                  onChange={(e) => set("max_answer_length", e.target.value)}
                />
              )}
            </Field>
            <Field label="Rubric (graders only, never shown to students)" error={errors.rubric}>
              {(props) => (
                <Textarea
                  {...props}
                  rows={4}
                  placeholder="What a full-marks answer mentions."
                  value={draft.rubric}
                  onChange={(e) => set("rubric", e.target.value)}
                />
              )}
            </Field>
          </div>
        )}

        {/* Marks and sharing */}
        <div className="bg-card shadow-card grid gap-4 rounded-xl border p-6 sm:grid-cols-2">
          <Field label="Marks" error={errors.points}>
            {(props) => (
              <Input
                {...props}
                type="number"
                min={0.5}
                step={0.5}
                value={draft.points}
                onChange={(e) => set("points", e.target.value)}
              />
            )}
          </Field>
          {!coding && (
            <Field label="Negative marks for a wrong answer" error={errors.negative_marks}>
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={0}
                  step={0.25}
                  value={draft.negative_marks}
                  onChange={(e) => set("negative_marks", e.target.value)}
                />
              )}
            </Field>
          )}
          <Field label="Tags (comma-separated)" error={errors.tags}>
            {(props) => (
              <Input
                {...props}
                placeholder="arrays, easy"
                value={draft.tags}
                onChange={(e) => set("tags", e.target.value)}
              />
            )}
          </Field>
          <Field label="Who can see it" error={errors.visibility}>
            {(props) => (
              <Select
                value={draft.visibility}
                onValueChange={(v) => set("visibility", v as Visibility)}
              >
                <SelectTrigger {...props} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(["PRIVATE", "INSTITUTION"] as const).map((v) => (
                    <SelectItem key={v} value={v}>
                      {visibilityLabel[v]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        </div>

        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending || (question && !changed)}>
            <Busy busy={save.isPending}>
              {question
                ? "Save changes"
                : coding
                  ? "Create, then set up the code"
                  : "Create question"}
            </Busy>
          </Button>
          {question && changed && (
            <Button type="button" variant="ghost" onClick={() => setDraft(initial)}>
              Undo changes
            </Button>
          )}
        </div>
      </form>
    </section>
  );
}
