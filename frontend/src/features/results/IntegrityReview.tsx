import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormMessage } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorText, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { eventLabel, integrityLabel } from "./lib";

type Event = components["schemas"]["EventView"];
type Picture = components["schemas"]["Picture"];

function seconds(ms: number | null | undefined): string {
  if (ms == null) return "";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

function facts(e: Event): string {
  const parts: string[] = [];
  const d = e.details as Record<string, unknown>;
  if (e.duration_ms != null) {
    const away = e.kind === "TAB_SWITCH" || e.kind === "FULLSCREEN_EXIT";
    parts.push(away ? `away ${seconds(e.duration_ms)}` : `for ${seconds(e.duration_ms)}`);
  }
  if (e.kind === "MULTIPLE_FACES" && typeof d.faces === "number") parts.push(`${d.faces} faces`);
  if (e.kind === "GAZE_AWAY" && d.direction === "up") parts.push("looking up");
  if (e.confidence != null) parts.push(`server check ${Math.round(e.confidence * 100)} %`);
  if (e.kind === "PASTE_BLOCKED" && typeof d.length === "number")
    parts.push(`${d.length} characters${d.how === "drop" ? ", dragged in" : ""}`);
  if (e.kind === "TAB_SWITCH" && d.how === "window") parts.push("another window");
  return parts.join(", ");
}

const severityStyle: Record<string, string> = {
  LOW: "border-border text-muted-foreground",
  MEDIUM: "border-warning/40 text-warning",
  HIGH: "border-destructive/40 text-destructive",
};

/**
 * The attempt's proctoring events in time order (PRD PRC-10, PRC-11): the teacher dismisses or
 * flags each, with a note. The integrity outcome follows and never changes the score.
 */
export function IntegrityReview({
  examId,
  attemptId,
  events,
  outcome,
  startedAt,
  queryKey,
}: {
  examId: string;
  attemptId: string;
  events: Event[];
  outcome: string | null | undefined;
  startedAt: string | null | undefined;
  queryKey: unknown[];
}) {
  // Pictures only when asked for: each look is audit-logged, and the links last 5 minutes.
  const [showPictures, setShowPictures] = useState(false);
  const pictures = useQuery({
    queryKey: ["exams", examId, "results", attemptId, "pictures"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/results/{attempt_id}/pictures", {
          params: { path: { exam_id: examId, attempt_id: attemptId } },
        }),
      ),
    enabled: showPictures,
    staleTime: 4 * 60_000,
    gcTime: 4 * 60_000,
  });
  const picturesBar = outcome && (
    <div className="space-y-2 text-sm">
      {!showPictures ? (
        <Button size="sm" variant="outline" onClick={() => setShowPictures(true)}>
          Show pictures
        </Button>
      ) : pictures.isPending ? (
        <p className="text-muted-foreground">Loading pictures…</p>
      ) : pictures.isError ? (
        <FormMessage tone="error">{errorText(pictures.error)}</FormMessage>
      ) : (
        <ScreenPictures pictures={pictures.data.screen} />
      )}
    </div>
  );
  if (events.length === 0) {
    return (
      <section className="bg-card space-y-2 rounded-xl border p-4 text-sm">
        <h3 className="font-semibold">Integrity</h3>
        <p className="text-muted-foreground">
          {outcome ? "No proctoring events: nothing to review." : "No checks on this exam."}
        </p>
        {picturesBar}
      </section>
    );
  }
  const open = events.filter((e) => !e.decision).length;
  return (
    <section className="bg-card space-y-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Integrity</h3>
        <span className="text-sm">
          {integrityLabel[outcome ?? ""] ?? "—"}
          {open > 0 && <span className="text-muted-foreground"> · {open} to review</span>}
        </span>
      </div>
      {picturesBar}
      <ol className="space-y-2">
        {events.map((e) => (
          <EventRow
            key={e.id}
            event={e}
            startedAt={startedAt}
            queryKey={queryKey}
            pictures={pictures.data?.events[e.id] ?? []}
          />
        ))}
      </ol>
    </section>
  );
}

function Thumbnail({ picture, label }: { picture: Picture; label: string }) {
  return (
    <a href={picture.url} target="_blank" rel="noreferrer" className="block">
      <img
        src={picture.url}
        alt={label}
        loading="lazy"
        className="h-24 rounded border object-cover"
      />
    </a>
  );
}

function ScreenPictures({ pictures }: { pictures: Picture[] }) {
  if (pictures.length === 0) return <p className="text-muted-foreground">No screen pictures.</p>;
  return (
    <div>
      <p className="mb-1 font-medium">Screen</p>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {pictures.map((p) => {
          const label = `Screen at ${new Date(p.taken_at).toLocaleTimeString()}${
            p.purpose === "LEFT_PAGE" ? ", on leaving the exam page" : ""
          }`;
          return (
            <figure key={p.url} className="shrink-0">
              <Thumbnail picture={p} label={label} />
              <figcaption className="text-muted-foreground mt-0.5 text-xs">
                {new Date(p.taken_at).toLocaleTimeString()}
                {p.purpose === "LEFT_PAGE" && " · left the page"}
              </figcaption>
            </figure>
          );
        })}
      </div>
    </div>
  );
}

function EventRow({
  event,
  startedAt,
  queryKey,
  pictures,
}: {
  event: Event;
  startedAt: string | null | undefined;
  queryKey: unknown[];
  pictures: Picture[];
}) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState(event.note ?? "");
  const decide = useMutation({
    mutationFn: async (decision: "DISMISSED" | "FLAGGED") =>
      unwrap(
        await api.PUT("/api/v1/proctoring-events/{event_id}/decision", {
          params: { path: { event_id: event.id } },
          body: { decision, note: note.trim() || null },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });
  const at = startedAt
    ? `${seconds(new Date(event.occurred_at).getTime() - new Date(startedAt).getTime())} in`
    : new Date(event.occurred_at).toLocaleTimeString();

  return (
    <li className={cn("rounded-lg border p-3", event.decision === "DISMISSED" && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline" className={severityStyle[event.severity]}>
          {event.severity.toLowerCase()}
        </Badge>
        <span className="font-medium">{eventLabel[event.kind] ?? event.kind}</span>
        <span className="text-muted-foreground">
          {at}
          {facts(event) && ` · ${facts(event)}`}
        </span>
        {event.decision && (
          <Badge variant="outline" className="ml-auto">
            {event.decision === "FLAGGED" ? "Flagged" : "Dismissed"}
          </Badge>
        )}
      </div>
      {pictures.length > 0 && (
        <div className="mt-2 flex gap-2">
          {pictures.map((p, i) => (
            <Thumbnail
              key={p.url}
              picture={p}
              label={`${eventLabel[event.kind] ?? event.kind}, picture ${i + 1} of ${pictures.length}`}
            />
          ))}
        </div>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Input
          aria-label={`Note on ${eventLabel[event.kind] ?? event.kind} at ${at}`}
          placeholder="Note (optional)"
          className="h-8 max-w-sm flex-1"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button
          size="sm"
          variant="outline"
          disabled={decide.isPending}
          onClick={() => decide.mutate("DISMISSED")}
        >
          Dismiss
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="text-destructive"
          disabled={decide.isPending}
          onClick={() => decide.mutate("FLAGGED")}
        >
          Flag
        </Button>
      </div>
      {decide.isError && <FormMessage tone="error">{errorText(decide.error)}</FormMessage>}
    </li>
  );
}
