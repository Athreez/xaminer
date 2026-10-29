import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Link, useSearchParams } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

import { actionText, dayStart } from "./lib";
import { formatDateTime, unwrap } from "@/lib/api";
import {
  Busy,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeader,
  TableCard,
} from "@/components/page";

type Entry = components["schemas"]["AuditEntry"];

const ALL = "all";
const FILTERS = ["actor_id", "action", "target_type", "target_id", "from", "to"] as const;

function itemLink(entry: Entry): string | null {
  if (!entry.target_id) return null;
  if (entry.target_type === "user") return `/admin/users/${entry.target_id}`;
  if (entry.target_type === "group") return `/admin/groups/${entry.target_id}`;
  return null;
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return `${value.length} ${value.length === 1 ? "item" : "items"}`;
  if (typeof value === "string") return value.length > 80 ? `${value.slice(0, 80)}…` : value;
  return JSON.stringify(value);
}

/** The changed fields as "field: old → new" lines (other shapes shown as-is). */
function Changes({ changes }: { changes: Entry["changes"] }) {
  if (!changes) return null;
  return (
    <ul className="space-y-0.5">
      {Object.entries(changes).map(([field, value]) => {
        const pair = value as { old?: unknown; new?: unknown } | null;
        const isDiff = pair && typeof pair === "object" && "old" in pair && "new" in pair;
        return (
          <li key={field}>
            <span className="text-muted-foreground">{field.replaceAll("_", " ")}:</span>{" "}
            {isDiff ? `${show(pair.old)} → ${show(pair.new)}` : show(value)}
          </li>
        );
      })}
    </ul>
  );
}

/** Audit log search (FRONTEND_SPEC § 5.1, PRD AUD-03). Filters live in the address bar. */
export function AuditPage() {
  const [params, setParams] = useSearchParams();
  const filter = Object.fromEntries(FILTERS.map((f) => [f, params.get(f) ?? undefined])) as Record<
    (typeof FILTERS)[number],
    string | undefined
  >;
  const anyFilter = FILTERS.some((f) => filter[f]);

  function setFilter(name: (typeof FILTERS)[number], value: string | undefined) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(name, value);
      else next.delete(name);
      return next;
    });
  }

  const actions = useQuery({
    queryKey: ["audit-actions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/audit-logs/actions")),
  });

  const log = useInfiniteQuery({
    queryKey: ["audit", filter],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/audit-logs", {
          params: {
            query: {
              actor_id: filter.actor_id,
              action: filter.action,
              target_type: filter.target_type,
              target_id: filter.target_id,
              from: filter.from ? dayStart(filter.from) : undefined,
              to: filter.to ? dayStart(filter.to, 1) : undefined, // the whole "to" day
              cursor: pageParam,
              limit: 50,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = log.data?.pages.flatMap((page) => page.data) ?? [];
  const actorName = rows.find((r) => r.actor?.id === filter.actor_id)?.actor?.full_name;

  return (
    <section>
      <PageHeader
        title="Audit log"
        description="Every important change and security event in your institution. Entries can't be edited or deleted."
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="audit-action">Action</Label>
          <Select
            value={filter.action ?? ALL}
            onValueChange={(v) => setFilter("action", v === ALL ? undefined : v)}
          >
            <SelectTrigger id="audit-action" className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All actions</SelectItem>
              {(actions.data ?? []).map((action) => (
                <SelectItem key={action} value={action}>
                  {actionText(action)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="date"
            className="w-40"
            value={filter.from ?? ""}
            max={filter.to}
            onChange={(e) => setFilter("from", e.target.value || undefined)}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="date"
            className="w-40"
            value={filter.to ?? ""}
            min={filter.from}
            onChange={(e) => setFilter("to", e.target.value || undefined)}
          />
        </div>
        {anyFilter && (
          <Button variant="ghost" onClick={() => setParams({})}>
            Clear filters
          </Button>
        )}
      </div>

      {(filter.actor_id || filter.target_id) && (
        <div className="mb-4 flex flex-wrap gap-2">
          {filter.actor_id && (
            <FilterChip
              label={`Done by ${actorName ?? "this user"}`}
              onClear={() => setFilter("actor_id", undefined)}
            />
          )}
          {filter.target_id && (
            <FilterChip
              label={`Changes to this ${filter.target_type ?? "item"}`}
              onClear={() => {
                setFilter("target_id", undefined);
                setFilter("target_type", undefined);
              }}
            />
          )}
        </div>
      )}

      {log.isPending ? (
        <LoadingRows rows={8} />
      ) : log.isError ? (
        <ErrorState error={log.error} onRetry={() => void log.refetch()} />
      ) : rows.length === 0 ? (
        anyFilter ? (
          <EmptyState title="No entries match these filters">
            <Button variant="outline" size="sm" onClick={() => setParams({})}>
              Clear filters
            </Button>
          </EmptyState>
        ) : (
          <EmptyState title="Nothing has been logged yet" />
        )
      ) : (
        <>
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Item</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((entry) => {
                  const link = itemLink(entry);
                  return (
                    <TableRow key={entry.id} className="align-top">
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        {formatDateTime(entry.created_at)}
                      </TableCell>
                      <TableCell>
                        {entry.actor ? (
                          <button
                            type="button"
                            className="text-left hover:underline"
                            title="Show only this user's actions"
                            onClick={() => setFilter("actor_id", entry.actor?.id)}
                          >
                            {entry.actor.full_name}
                          </button>
                        ) : (
                          <span className="text-muted-foreground">
                            {entry.actor_role === "PLATFORM" ? "Platform admin" : "Not logged in"}
                          </span>
                        )}
                        {entry.actor_role && entry.actor_role !== "PLATFORM" && (
                          <Badge variant="outline" className="ml-2">
                            {entry.actor_role.toLowerCase()}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {actionText(entry.action)}
                      </TableCell>
                      <TableCell>
                        {entry.target_type ? (
                          link ? (
                            <Link to={link} className="hover:underline">
                              {entry.target_type}
                            </Link>
                          ) : (
                            entry.target_type
                          )
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="max-w-md text-sm whitespace-normal">
                        <Changes changes={entry.changes} />
                        {(entry.ip || entry.request_id) && (
                          <details className="text-muted-foreground mt-1 text-xs">
                            <summary className="cursor-pointer">Request</summary>
                            <dl className="mt-1 space-y-0.5">
                              {entry.ip && <div>IP: {entry.ip}</div>}
                              {entry.user_agent && <div>Browser: {entry.user_agent}</div>}
                              {entry.request_id && <div>Request ID: {entry.request_id}</div>}
                            </dl>
                          </details>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableCard>
          {log.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={log.isFetchingNextPage}
                onClick={() => void log.fetchNextPage()}
              >
                <Busy busy={log.isFetchingNextPage}>Load more</Busy>
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FilterChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="bg-selection-soft text-selection inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm">
      {label}
      <button type="button" aria-label={`Remove filter: ${label}`} onClick={onClear}>
        <X className="size-3.5" />
      </button>
    </span>
  );
}
