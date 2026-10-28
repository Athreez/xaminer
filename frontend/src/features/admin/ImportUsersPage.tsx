import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileUp } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";
import { Link } from "react-router";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { FormMessage } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

import { errorText, unwrap } from "./lib";
import { Busy, PageHeader, TableCard } from "./shared";

type Result = components["schemas"]["ImportResult"];
type Row = components["schemas"]["ImportRow"];

const MAX_BYTES = 1_000_000;
const TEMPLATE =
  "email,full name,role,roll no\nravi@college.edu,Ravi Kumar,Student,CSE-001\nasha@college.edu,Asha Rao,Teacher,\n";

const statusStyle: Record<Row["status"], { label: string; className: string }> = {
  READY: { label: "Ready", className: "bg-success-soft text-success border-success/30" },
  IMPORTED: { label: "Imported", className: "bg-success-soft text-success border-success/30" },
  SKIPPED: { label: "Skipped", className: "bg-muted text-muted-foreground border-border" },
  ERROR: { label: "Error", className: "bg-danger-soft text-destructive border-destructive/30" },
};

/** CSV import: upload → preview with row errors → import valid rows → summary (FRONTEND_SPEC § 5.1). */
export function ImportUsersPage() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<{ name: string; text: string } | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [errorsOnly, setErrorsOnly] = useState(false);

  const run = useMutation({
    mutationFn: async ({ text, dryRun }: { text: string; dryRun: boolean }) =>
      unwrap(await api.POST("/api/v1/users/import", { body: { csv: text, dry_run: dryRun } })),
    onSuccess: (result) => {
      if (!result.dry_run) void queryClient.invalidateQueries({ queryKey: ["users"] });
      setErrorsOnly(result.failed > 0 && result.dry_run);
    },
  });
  const result = run.data;

  async function onPick(event: ChangeEvent<HTMLInputElement>) {
    const picked = event.target.files?.[0];
    event.target.value = ""; // picking the same file again still triggers a change
    if (!picked) return;
    run.reset();
    setFile(null);
    if (picked.size > MAX_BYTES) {
      setFileError("The file is larger than 1 MB. Split it into smaller files.");
      return;
    }
    setFileError(null);
    const text = await picked.text();
    setFile({ name: picked.name, text });
    run.mutate({ text, dryRun: true });
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "xaminer-users.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  const rows = (result?.rows ?? []).filter((r) => !errorsOnly || r.status === "ERROR");

  return (
    <section className="max-w-5xl">
      <Link
        to="/admin/users"
        className="text-muted-foreground mb-4 inline-flex items-center gap-1 text-sm hover:underline"
      >
        <ArrowLeft className="size-4" /> All users
      </Link>
      <PageHeader
        title="Import users"
        description="Add many teachers and students at once from a CSV file. Each new user gets an invitation email."
        actions={
          <Button variant="outline" onClick={downloadTemplate}>
            <Download /> Template
          </Button>
        }
      />

      <div className="bg-card shadow-card mb-6 rounded-xl border p-6">
        <p className="text-sm">
          Columns: <strong>email</strong>, <strong>full name</strong>, <strong>role</strong> (Admin,
          Teacher or Student) and <strong>roll no</strong> (optional). The first line must name the
          columns. Up to 2,000 users and 1 MB per file. Spreadsheets can save as CSV.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            aria-label="CSV file"
            onChange={(e) => void onPick(e)}
          />
          <Button
            variant={file ? "outline" : "default"}
            disabled={run.isPending}
            onClick={() => input.current?.click()}
          >
            <FileUp /> {file ? "Choose another file" : "Choose CSV file"}
          </Button>
          {file && <span className="text-muted-foreground text-sm">{file.name}</span>}
        </div>
      </div>

      <div className="space-y-4">
        {fileError && <FormMessage tone="error">{fileError}</FormMessage>}
        {run.isError && <FormMessage tone="error">{errorText(run.error)}</FormMessage>}
        {run.isPending && (
          <p className="text-muted-foreground text-sm">
            <Busy busy>{run.variables?.dryRun ? "Checking the file…" : "Importing…"}</Busy>
          </p>
        )}
      </div>

      {result && !run.isPending && (
        <>
          {result.dry_run ? (
            <div className="mb-4 flex flex-wrap items-center gap-4">
              <Summary result={result} />
              <Button
                className="ml-auto"
                disabled={result.ready === 0 || !file}
                onClick={() => file && run.mutate({ text: file.text, dryRun: false })}
              >
                Import {result.ready} {result.ready === 1 ? "user" : "users"}
              </Button>
            </div>
          ) : (
            <div className="mb-4 space-y-3">
              <FormMessage tone="success">
                Imported {result.ready} {result.ready === 1 ? "user" : "users"}. Invitation emails
                are on their way.
                {result.skipped > 0 && ` ${result.skipped} already had an account.`}
                {result.failed > 0 && ` ${result.failed} rows had errors and were not imported.`}
              </FormMessage>
              <Button variant="outline" asChild>
                <Link to="/admin/users">Go to users</Link>
              </Button>
            </div>
          )}

          {result.failed > 0 && (
            <label className="mb-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={errorsOnly}
                onChange={(e) => setErrorsOnly(e.target.checked)}
              />
              Show only rows with errors
            </label>
          )}
          <TableCard>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">Line</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Roll no.</TableHead>
                  <TableHead>Problem</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.row}
                    className={cn(row.status === "ERROR" && "bg-danger-soft/40")}
                  >
                    <TableCell className="text-muted-foreground tabular-nums">{row.row}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={statusStyle[row.status].className}>
                        {statusStyle[row.status].label}
                      </Badge>
                    </TableCell>
                    <TableCell>{row.email || "—"}</TableCell>
                    <TableCell>{row.full_name || "—"}</TableCell>
                    <TableCell className="capitalize">{row.role.toLowerCase() || "—"}</TableCell>
                    <TableCell>{row.roll_no ?? "—"}</TableCell>
                    <TableCell className="text-sm whitespace-normal">{row.message ?? ""}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableCard>
        </>
      )}
    </section>
  );
}

function Summary({ result }: { result: Result }) {
  const items = [
    { label: "Ready to import", value: result.ready, className: "text-success" },
    { label: "Already have an account", value: result.skipped, className: "text-muted-foreground" },
    { label: "Errors", value: result.failed, className: "text-destructive" },
  ];
  return (
    <dl className="flex gap-6">
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-muted-foreground text-xs">{item.label}</dt>
          <dd className={cn("text-2xl font-semibold tabular-nums", item.className)}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
