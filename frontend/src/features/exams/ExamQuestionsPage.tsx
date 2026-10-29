import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GripVertical, Plus, Search, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormMessage } from "@/components/form";
import { Busy, EmptyState, ErrorState, LoadingRows } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorText, unwrap, useDebounced } from "@/lib/api";
import { cn } from "@/lib/utils";
import { fieldErrors, typeLabel } from "@/features/questions/lib";

import { useExam } from "./context";

type Row = components["schemas"]["ExamQuestionView"];

interface Item {
  question_id: string;
  title: string;
  type: Row["type"];
  owner: string;
  question_points: number;
  question_negative: number;
  points: string; // "" = the question's own
  negative_marks: string;
}

function itemOf(row: Row): Item {
  return {
    question_id: row.question_id,
    title: row.title,
    type: row.type,
    owner: row.is_mine ? "You" : row.owner_name,
    question_points: Number(row.question_points),
    // The question's own negative marks are shown only when the exam doesn't set its own.
    question_negative: row.negative_marks_override ? 0 : Number(row.negative_marks),
    points: row.points_override ? String(Number(row.points_override)) : "",
    negative_marks: row.negative_marks_override ? String(Number(row.negative_marks_override)) : "",
  };
}

const payload = (items: Item[]) =>
  items.map((i) => ({
    question_id: i.question_id,
    points: i.points || null,
    negative_marks: i.negative_marks || null,
  }));

/** Choose and order the exam's questions (FRONTEND_SPEC § 5.4, PRD EX-02). */
export function ExamQuestionsPage() {
  const { exam, draft } = useExam();
  // Kept here: saving reloads the list, which restarts the editor below.
  const [notice, setNotice] = useState<string | null>(null);
  const listed = useQuery({
    queryKey: ["exams", exam.id, "questions"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/questions", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
  });

  if (listed.isPending) return <LoadingRows rows={6} />;
  if (listed.isError)
    return <ErrorState error={listed.error} onRetry={() => void listed.refetch()} />;
  // Keyed by the saved list, so the editor restarts from the server's state after a save.
  return (
    <QuestionsEditor
      key={JSON.stringify(listed.data.questions.map((q) => [q.question_id, q.points_override]))}
      saved={listed.data.questions.map(itemOf)}
      editable={draft}
      notice={notice}
      setNotice={setNotice}
    />
  );
}

function QuestionsEditor({
  saved,
  editable,
  notice,
  setNotice,
}: {
  saved: Item[];
  editable: boolean;
  notice: string | null;
  setNotice: (notice: string | null) => void;
}) {
  const { exam, refresh } = useExam();
  const [items, setItems] = useState<Item[]>(saved);
  const [dragged, setDragged] = useState<number | null>(null);
  const changed = JSON.stringify(payload(items)) !== JSON.stringify(payload(saved));
  const total = items.reduce((sum, i) => sum + (Number(i.points) || i.question_points), 0);

  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PUT("/api/v1/exams/{exam_id}/questions", {
          params: { path: { exam_id: exam.id } },
          body: { questions: payload(items) },
        }),
      ),
    onSuccess: () => {
      setNotice("Questions saved.");
      refresh();
    },
  });
  const errors = fieldErrors(save.error);

  function move(from: number, to: number) {
    if (to < 0 || to >= items.length || from === to) return;
    setNotice(null);
    setItems((list) => {
      const next = [...list];
      const [moved] = next.splice(from, 1);
      if (moved) next.splice(to, 0, moved);
      return next;
    });
  }
  const update = (index: number, change: Partial<Item>) => {
    setNotice(null);
    setItems((list) => list.map((item, i) => (i === index ? { ...item, ...change } : item)));
  };

  return (
    <div className={cn("grid gap-6", editable && "lg:grid-cols-[1fr_22rem]")}>
      <div className="space-y-3">
        {!editable && (
          <FormMessage tone="info">
            {exam.status === "PUBLISHED"
              ? "The exam is published: these questions and versions are fixed."
              : "This exam is archived and can't be changed."}
          </FormMessage>
        )}
        {notice && !changed && <FormMessage tone="success">{notice}</FormMessage>}
        {save.isError && <FormMessage tone="error">{errorText(save.error)}</FormMessage>}

        <div className="flex items-baseline justify-between">
          <h2 className="font-semibold">
            {items.length} {items.length === 1 ? "question" : "questions"}
          </h2>
          <p className="text-sm">
            Total: <span className="font-semibold tabular-nums">{total}</span> marks
          </p>
        </div>

        {items.length === 0 ? (
          <EmptyState title="No questions yet">
            {editable ? "Add questions from your bank on the right." : null}
          </EmptyState>
        ) : (
          <ol className="space-y-2">
            {items.map((item, index) => {
              const error =
                errors[`questions.${index}.question_id`] ??
                errors[`questions.${index}.negative_marks`] ??
                errors[`questions.${index}.points`];
              return (
                <li
                  key={item.question_id}
                  draggable={editable}
                  onDragStart={() => setDragged(index)}
                  onDragOver={(e) => editable && e.preventDefault()}
                  onDrop={() => {
                    if (dragged !== null) move(dragged, index);
                    setDragged(null);
                  }}
                  className={cn(
                    "bg-card shadow-card rounded-xl border p-3",
                    dragged === index && "opacity-50",
                    error && "border-destructive",
                  )}
                >
                  <div className="flex items-start gap-2">
                    {editable && (
                      <GripVertical
                        className="text-muted-foreground mt-1 size-4 shrink-0 cursor-grab"
                        aria-hidden
                      />
                    )}
                    <span className="text-muted-foreground mt-0.5 w-6 text-sm font-medium tabular-nums">
                      {index + 1}.
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{item.title || "(no text)"}</p>
                      <p className="text-muted-foreground text-xs">
                        {typeLabel[item.type]} · {item.owner} · worth {item.question_points} in the
                        bank
                      </p>
                      {error && <p className="text-destructive mt-1 text-sm">{error}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Input
                        aria-label={`Marks for question ${index + 1}`}
                        type="number"
                        min={0.5}
                        step={0.5}
                        className="h-9 w-20"
                        placeholder={String(item.question_points)}
                        disabled={!editable}
                        value={item.points}
                        onChange={(e) => update(index, { points: e.target.value })}
                      />
                      <Input
                        aria-label={`Negative marks for question ${index + 1}`}
                        title="Negative marks for a wrong answer"
                        type="number"
                        min={0}
                        step={0.25}
                        className="h-9 w-20"
                        placeholder={item.question_negative ? `−${item.question_negative}` : "0"}
                        disabled={!editable}
                        value={item.negative_marks}
                        onChange={(e) => update(index, { negative_marks: e.target.value })}
                      />
                      {editable && (
                        <div className="flex">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Move question ${index + 1} up`}
                            disabled={index === 0}
                            onClick={() => move(index, index - 1)}
                          >
                            <ArrowUp />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Move question ${index + 1} down`}
                            disabled={index === items.length - 1}
                            onClick={() => move(index, index + 1)}
                          >
                            <ArrowDown />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Remove question ${index + 1}`}
                            onClick={() => setItems((list) => list.filter((_, i) => i !== index))}
                          >
                            <X />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {editable && (
          <p className="text-muted-foreground text-xs">
            Drag to reorder, or use the arrows. Leave marks empty to use the question's own.
          </p>
        )}
        {editable && (
          <div className="flex gap-2">
            <Button disabled={!changed || save.isPending} onClick={() => save.mutate()}>
              <Busy busy={save.isPending}>Save questions</Busy>
            </Button>
            {changed && (
              <Button variant="ghost" onClick={() => setItems(saved)}>
                Undo changes
              </Button>
            )}
          </div>
        )}
      </div>

      {editable && (
        <BankPicker
          chosen={new Set(items.map((i) => i.question_id))}
          onAdd={(item) => {
            setNotice(null);
            setItems((list) => [...list, item]);
          }}
        />
      )}
    </div>
  );
}

/** The question bank, to add from: your questions and colleagues' shared ones. */
function BankPicker({ chosen, onAdd }: { chosen: Set<string>; onAdd: (item: Item) => void }) {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const bank = useQuery({
    queryKey: ["questions", { q, picker: true }],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/questions", {
          params: { query: { q: q || undefined, owner: "all", limit: 50 } },
        }),
      ),
  });

  return (
    <aside className="bg-card shadow-card self-start rounded-xl border p-4 lg:sticky lg:top-4">
      <h2 className="mb-2 font-semibold">Question bank</h2>
      <div className="relative mb-3">
        <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <Input
          aria-label="Search the question bank"
          placeholder="Search questions"
          className="pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {bank.isPending ? (
        <LoadingRows rows={4} />
      ) : bank.isError ? (
        <ErrorState error={bank.error} onRetry={() => void bank.refetch()} />
      ) : bank.data.data.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm">
          {q ? "No questions match." : "Your bank is empty."}{" "}
          <Link to="/teacher/questions/new" className="text-selection hover:underline">
            Write a question
          </Link>
        </p>
      ) : (
        <ul className="max-h-[32rem] space-y-1 overflow-y-auto">
          {bank.data.data.map((question) => {
            const added = chosen.has(question.id);
            return (
              <li
                key={question.id}
                className="flex items-start gap-2 rounded-lg p-2 hover:bg-accent/50"
              >
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 text-sm font-medium">
                    {question.title || "(no text)"}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {typeLabel[question.type]} · {Number(question.points)} marks
                    {!question.is_mine && ` · ${question.owner.full_name}`}
                  </p>
                </div>
                {added ? (
                  <Badge variant="outline">Added</Badge>
                ) : (
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={`Add "${question.title}"`}
                    onClick={() =>
                      onAdd({
                        question_id: question.id,
                        title: question.title,
                        type: question.type,
                        owner: question.is_mine ? "You" : question.owner.full_name,
                        question_points: Number(question.points),
                        question_negative: 0,
                        points: "",
                        negative_marks: "",
                      })
                    }
                  >
                    <Plus />
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
