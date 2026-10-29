import { useInfiniteQuery } from "@tanstack/react-query";
import { Eye, Lock, Plus, Search, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { api } from "@/api/client";
import {
  Busy,
  EmptyState,
  ErrorState,
  LoadingRows,
  PageHeader,
  TableCard,
} from "@/components/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { formatDateTime, unwrap, useDebounced } from "@/lib/api";

import { EDITABLE_TYPES, typeLabel, type QuestionType } from "./lib";

const ALL = "all";
type Owner = "all" | "mine" | "shared";

/** Question bank (FRONTEND_SPEC § 5.2, PRD QB-01). Filters live in the address bar. */
export function QuestionBankPage() {
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") as QuestionType | null) ?? undefined;
  const owner = (params.get("owner") as Owner | null) ?? "all";
  const archived = params.get("archived") === "true";
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [tagText, setTagText] = useState(params.get("tag") ?? "");
  const q = useDebounced(search.trim(), 300);
  const tag = useDebounced(tagText.trim().toLowerCase(), 300);

  useEffect(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of [
          ["q", q],
          ["tag", tag],
        ] as const) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  }, [q, tag, setParams]);

  function setParam(name: string, value: string | undefined) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value && value !== ALL) next.set(name, value);
      else next.delete(name);
      return next;
    });
  }

  function clearFilters() {
    setSearch("");
    setTagText("");
    setParams({});
  }

  const filtered = Boolean(type || q || tag || owner !== "all" || archived);
  const questions = useInfiniteQuery({
    queryKey: ["questions", { type, owner, archived, q, tag }],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/questions", {
          params: {
            query: {
              type,
              owner,
              archived,
              q: q || undefined,
              tag: tag || undefined,
              cursor: pageParam,
              limit: 50,
            },
          },
        }),
      ),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = questions.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <section>
      <PageHeader
        title="Questions"
        description="Your questions and the ones colleagues share with the institution."
        actions={
          <Button asChild>
            <Link to="new">
              <Plus /> New question
            </Link>
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            aria-label="Search question text and tags"
            placeholder="Search text and tags"
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={type ?? ALL} onValueChange={(v) => setParam("type", v)}>
          <SelectTrigger className="w-44" aria-label="Type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All types</SelectItem>
            {[...EDITABLE_TYPES, "CODING" as const].map((t) => (
              <SelectItem key={t} value={t}>
                {typeLabel[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={owner} onValueChange={(v) => setParam("owner", v)}>
          <SelectTrigger className="w-44" aria-label="Owner">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Mine and shared</SelectItem>
            <SelectItem value="mine">Only mine</SelectItem>
            <SelectItem value="shared">Shared by others</SelectItem>
          </SelectContent>
        </Select>
        <Input
          aria-label="Tag"
          placeholder="Tag"
          className="w-36"
          value={tagText}
          onChange={(e) => setTagText(e.target.value)}
        />
        <Button
          variant={archived ? "default" : "outline"}
          aria-pressed={archived}
          onClick={() => setParam("archived", archived ? undefined : "true")}
        >
          Archived
        </Button>
      </div>

      {questions.isPending ? (
        <LoadingRows />
      ) : questions.isError ? (
        <ErrorState error={questions.error} onRetry={() => void questions.refetch()} />
      ) : rows.length === 0 ? (
        filtered ? (
          <EmptyState title="No questions match these filters">
            <Button variant="outline" size="sm" onClick={clearFilters}>
              Clear filters
            </Button>
          </EmptyState>
        ) : (
          <EmptyState title="No questions yet">
            <Button size="sm" asChild>
              <Link to="new">
                <Plus /> Write your first question
              </Link>
            </Button>
          </EmptyState>
        )
      ) : (
        <>
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Tags</TableHead>
                  <TableHead>Owner</TableHead>
                  <TableHead className="text-right">Points</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Preview</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((question) => (
                  <TableRow key={question.id}>
                    <TableCell className="max-w-md">
                      <Link
                        to={question.id}
                        className="line-clamp-2 font-medium whitespace-normal hover:underline"
                      >
                        {question.title || "(no text)"}
                      </Link>
                      <span className="text-muted-foreground mt-0.5 flex items-center gap-1 text-xs">
                        {question.visibility === "INSTITUTION" ? (
                          <>
                            <Users className="size-3" /> Shared
                          </>
                        ) : (
                          <>
                            <Lock className="size-3" /> Private
                          </>
                        )}
                        {question.version_no > 1 && ` · Version ${question.version_no}`}
                        {question.is_locked && " · Used in a published exam"}
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{typeLabel[question.type]}</TableCell>
                    <TableCell className="whitespace-normal">
                      <span className="flex flex-wrap gap-1">
                        {question.tags.map((t) => (
                          <Badge
                            key={t}
                            variant="outline"
                            className="cursor-pointer"
                            onClick={() => setTagText(t)}
                          >
                            {t}
                          </Badge>
                        ))}
                      </span>
                    </TableCell>
                    <TableCell>{question.is_mine ? "You" : question.owner.full_name}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {Number(question.points)}
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {formatDateTime(question.updated_at)}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon-sm" asChild>
                        <Link
                          to={`${question.id}/preview`}
                          aria-label={`Preview "${question.title}" as a student`}
                        >
                          <Eye />
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableCard>
          {questions.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={questions.isFetchingNextPage}
                onClick={() => void questions.fetchNextPage()}
              >
                <Busy busy={questions.isFetchingNextPage}>Load more</Busy>
              </Button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
