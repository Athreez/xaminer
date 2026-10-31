import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormMessage } from "@/components/form";
import { Busy, EmptyState, ErrorState, LoadingRows, TableCard } from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { errorText, unwrap } from "@/lib/api";
import { cn } from "@/lib/utils";

import { formatClock } from "../attempt/lib";
import { eventLabel } from "../results/lib";
import { useExam } from "./context";

type Row = components["schemas"]["MonitorRow"];
type Alert = components["schemas"]["Alert"];

const nowLabel: Record<string, string> = { ...eventLabel, CAMERA_OFF: "Camera off" };

function duration(seconds: number): string {
  return seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min`;
}
type Action = "extend" | "force-submit" | "void";

const statusLabel: Record<Row["status"], string> = {
  NOT_STARTED: "Not started",
  IN_PROGRESS: "In progress",
  SUBMITTED: "Submitted",
  AUTO_SUBMITTED: "Submitted (time up)",
  VOIDED: "Voided",
};

const connectionStyle: Record<string, { label: string; dot: string }> = {
  ONLINE: { label: "Online", dot: "bg-success" },
  WEAK: { label: "Weak", dot: "bg-warning" },
  OFFLINE: { label: "Offline", dot: "bg-destructive" },
};

/**
 * Live monitor (FRONTEND_SPEC § 5.4, PRD MON-01, MON-02, MON-06): every assigned student, refreshed every
 * 10 s, time left counting down in between. Row actions ask for a reason (kept in the audit log).
 * Proctored exams: what proctoring sees right now on each row, and new alerts announced.
 */
export function MonitorPage() {
  const { exam } = useExam();
  const [acting, setActing] = useState<{ row: Row; action: Action } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const monitor = useQuery({
    queryKey: ["exams", exam.id, "monitor"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/exams/{exam_id}/monitor", {
          params: { path: { exam_id: exam.id } },
        }),
      ),
    refetchInterval: 10_000,
  });
  const elapsed = useSecondsSince(monitor.dataUpdatedAt);

  if (exam.status === "DRAFT")
    return (
      <EmptyState title="Not published yet">
        The monitor shows students once the exam is published.
      </EmptyState>
    );
  if (monitor.isPending) return <LoadingRows />;
  if (monitor.isError)
    return <ErrorState error={monitor.error} onRetry={() => void monitor.refetch()} />;
  const { rows, counts, alerts } = monitor.data;

  return (
    <div className="space-y-4">
      {notice && <FormMessage tone="success">{notice}</FormMessage>}
      <LiveAlerts alerts={alerts} base={`/teacher/exams/${exam.id}`} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
        {(["IN_PROGRESS", "NOT_STARTED", "SUBMITTED", "AUTO_SUBMITTED", "VOIDED"] as const).map(
          (s) =>
            (counts[s] ?? 0) > 0 && (
              <span key={s}>
                <span className="font-semibold tabular-nums">{counts[s]}</span>{" "}
                <span className="text-muted-foreground">{statusLabel[s].toLowerCase()}</span>
              </span>
            ),
        )}
        <span className="text-muted-foreground ml-auto text-xs">Refreshes every 10 s</span>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="Nobody is assigned">Assign students on the Students tab.</EmptyState>
      ) : (
        <TableCard>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Student</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Answered</TableHead>
                <TableHead className="text-right">Time left</TableHead>
                <TableHead>Connection</TableHead>
                <TableHead className="text-right">Unsaved</TableHead>
                <TableHead className="text-right">Events</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <TableRow key={r.student_id}>
                  <TableCell>
                    <div className="font-medium">{r.full_name}</div>
                    <div className="text-muted-foreground text-xs">{r.roll_no ?? r.email}</div>
                    {(r.happening ?? []).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {r.happening!.map((h) => (
                          <span
                            key={h.kind}
                            className="bg-warning-soft text-warning rounded px-1.5 py-0.5 text-xs"
                          >
                            Now: {nowLabel[h.kind] ?? h.kind} · {duration(h.seconds)}
                          </span>
                        ))}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">{statusLabel[r.status]}</Badge>
                    {r.extra_minutes > 0 && (
                      <span className="text-muted-foreground ml-1 text-xs">
                        +{r.extra_minutes} min
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.attempt_id ? `${r.answered} / ${r.total}` : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {r.seconds_left == null
                      ? "—"
                      : formatClock(Math.max(0, r.seconds_left - elapsed))}
                  </TableCell>
                  <TableCell>
                    {r.connection ? (
                      <span className="inline-flex items-center gap-1.5 text-sm">
                        <span
                          aria-hidden
                          className={cn("size-2 rounded-full", connectionStyle[r.connection]!.dot)}
                        />
                        {connectionStyle[r.connection]!.label}
                      </span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell
                    className={cn("text-right tabular-nums", r.unsynced > 0 && "text-warning")}
                  >
                    {r.status === "IN_PROGRESS" ? r.unsynced : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{r.event_count}</TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      {r.status === "IN_PROGRESS" && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setActing({ row: r, action: "extend" })}
                          >
                            Extend
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setActing({ row: r, action: "force-submit" })}
                          >
                            Submit now
                          </Button>
                        </>
                      )}
                      {r.attempt_id && r.status !== "VOIDED" && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive"
                          onClick={() => setActing({ row: r, action: "void" })}
                        >
                          Void
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableCard>
      )}
      {acting && (
        <ActionDialog
          key={`${acting.row.attempt_id}-${acting.action}`}
          row={acting.row}
          action={acting.action}
          onClose={() => setActing(null)}
          onDone={(text) => {
            setActing(null);
            setNotice(text);
            void monitor.refetch();
          }}
        />
      )}
    </div>
  );
}

/**
 * Medium and high proctoring events of the last 30 minutes, newest first. New ones are announced
 * (screen readers too) and counted in the tab's title until marked seen, so a teacher watching
 * another tab notices.
 */
function LiveAlerts({ alerts, base }: { alerts: Alert[]; base: string }) {
  const [seen, setSeen] = useState<Set<string> | null>(null);
  const title = useRef(document.title);
  // The first load counts as seen: only what arrives while watching is new.
  if (seen === null) setSeen(new Set(alerts.map((a) => a.event_id)));
  const fresh = seen ? alerts.filter((a) => !seen.has(a.event_id)) : [];

  useEffect(() => {
    const original = title.current;
    document.title = fresh.length ? `(${fresh.length}) ${original}` : original;
    return () => {
      document.title = original;
    };
  }, [fresh.length]);
  const newest = fresh[0];
  const announcement = newest
    ? `New alert: ${newest.full_name}, ${eventLabel[newest.kind] ?? newest.kind}`
    : "";

  return (
    <section aria-labelledby="alerts-title" className="bg-card rounded-xl border p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id="alerts-title" className="flex items-center gap-2 font-semibold">
          <BellRing aria-hidden className="size-4" />
          Alerts
          {fresh.length > 0 && <Badge className="bg-destructive">{fresh.length} new</Badge>}
        </h2>
        {fresh.length > 0 && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setSeen(new Set(alerts.map((a) => a.event_id)))}
          >
            Mark seen
          </Button>
        )}
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      {alerts.length === 0 ? (
        <p className="text-muted-foreground mt-1 text-sm">
          Nothing in the last 30 minutes. Medium and high proctoring events appear here within a
          minute.
        </p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm">
          {alerts.map((a) => (
            <li
              key={a.event_id}
              className={cn(
                "flex flex-wrap items-center gap-2 rounded px-2 py-1",
                !seen?.has(a.event_id) && "bg-warning-soft",
              )}
            >
              <Badge
                variant="outline"
                className={a.severity === "HIGH" ? "text-destructive" : "text-warning"}
              >
                {a.severity.toLowerCase()}
              </Badge>
              <span className="font-medium">{a.full_name}</span>
              <span>{eventLabel[a.kind] ?? a.kind}</span>
              {a.duration_ms != null && (
                <span className="text-muted-foreground">
                  {duration(Math.round(a.duration_ms / 1000))}
                </span>
              )}
              <span className="text-muted-foreground">
                at {new Date(a.occurred_at).toLocaleTimeString()}
              </span>
              <Link to={`${base}/results/${a.attempt_id}`} className="ml-auto underline">
                Review
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Seconds since `since` (ms), ticking every second, for the countdown between refreshes. */
function useSecondsSince(since: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return since ? Math.max(0, Math.floor((now - since) / 1000)) : 0;
}

const actionText: Record<Action, { title: string; button: string; explain: string }> = {
  extend: {
    title: "Give extra time",
    button: "Extend",
    explain: "The student sees the new time within seconds. It can't go past the window's end.",
  },
  "force-submit": {
    title: "Submit this attempt now?",
    button: "Submit now",
    explain: "The attempt ends now with the answers saved so far, and is graded as usual.",
  },
  void: {
    title: "Void this attempt?",
    button: "Void",
    explain: "The attempt is cancelled and never graded. The student may start the exam again.",
  },
};

function ActionDialog({
  row,
  action,
  onClose,
  onDone,
}: {
  row: Row;
  action: Action;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const queryClient = useQueryClient();
  const [minutes, setMinutes] = useState("10");
  const [reason, setReason] = useState("");
  const text = actionText[action];
  const run = useMutation({
    mutationFn: async () => {
      const path = { params: { path: { attempt_id: row.attempt_id! } } };
      const body = { reason: reason.trim() };
      if (action === "extend")
        return unwrap(
          await api.POST("/api/v1/attempts/{attempt_id}/extend", {
            ...path,
            body: { ...body, minutes: Number(minutes) },
          }),
        );
      if (action === "force-submit")
        return unwrap(
          await api.POST("/api/v1/attempts/{attempt_id}/force-submit", { ...path, body }),
        );
      return unwrap(await api.POST("/api/v1/attempts/{attempt_id}/void", { ...path, body }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["exams"] });
      onDone(
        action === "extend"
          ? `${row.full_name} got ${minutes} more minutes.`
          : action === "force-submit"
            ? `${row.full_name}'s attempt was submitted.`
            : `${row.full_name}'s attempt was voided.`,
      );
    },
  });
  const minutesOk = /^\d+$/.test(minutes) && Number(minutes) >= 1 && Number(minutes) <= 120;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{text.title}</DialogTitle>
          <DialogDescription>
            {row.full_name}. {text.explain}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          {action === "extend" && (
            <div className="space-y-1">
              <Label htmlFor="minutes">Extra minutes (1 to 120)</Label>
              <Input
                id="minutes"
                inputMode="numeric"
                value={minutes}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="reason">Reason (kept in the audit log)</Label>
            <Input
              id="reason"
              value={reason}
              placeholder="e.g. Power cut in lab 2"
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </div>
        {run.isError && <FormMessage tone="error">{errorText(run.error)}</FormMessage>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant={action === "void" ? "destructive" : "default"}
            disabled={
              reason.trim().length < 3 || (action === "extend" && !minutesOk) || run.isPending
            }
            onClick={() => run.mutate()}
          >
            <Busy busy={run.isPending}>{text.button}</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
