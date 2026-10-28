import { useId, type ReactNode } from "react";

import { Label } from "@/components/ui/label";

/** Labelled field with its error linked for screen readers. */
export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: (props: {
    id: string;
    "aria-invalid"?: boolean;
    "aria-describedby"?: string;
  }) => ReactNode;
}) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": error ? errorId : undefined,
      })}
      {error && (
        <p id={errorId} className="text-destructive text-sm">
          {error}
        </p>
      )}
    </div>
  );
}

/** A message box for the whole form (errors and confirmations). Announced to screen readers. */
export function FormMessage({
  tone,
  children,
}: {
  tone: "error" | "info" | "success";
  children: ReactNode;
}) {
  const styles = {
    error: "bg-danger-soft border-destructive/40 text-destructive",
    info: "bg-selection-soft border-selection/40 text-selection-foreground",
    success: "bg-success-soft border-success/40 text-success",
  }[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-xl border px-4 py-3 text-sm ${styles}`}
    >
      {children}
    </div>
  );
}
