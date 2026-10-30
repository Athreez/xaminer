import { useMutation, useQueryClient } from "@tanstack/react-query";
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
  events,
  outcome,
  startedAt,
  queryKey,
}: {
  events: Event[];
  outcome: string | null | undefined;
  startedAt: string | null | undefined;
  queryKey: unknown[];
}) {
  if (events.length === 0) {
    return (
      <section className="bg-card rounded-xl border p-4 text-sm">
        <h3 className="font-semibold">Integrity</h3>
        <p className="text-muted-foreground mt-1">
          {outcome ? "No browser-check events: nothing to review." : "No checks on this exam."}
        </p>
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
      <ol className="space-y-2">
        {events.map((e) => (
          <EventRow key={e.id} event={e} startedAt={startedAt} queryKey={queryKey} />
        ))}
      </ol>
    </section>
  );
}

function EventRow({
  event,
  startedAt,
  queryKey,
}: {
  event: Event;
  startedAt: string | null | undefined;
  queryKey: unknown[];
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
