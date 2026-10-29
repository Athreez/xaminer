import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { errorText } from "@/lib/api";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {description && <p className="text-muted-foreground mt-1">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}

/** LOADING: grey bars in the shape of the table that is coming. */
export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

/** EMPTY and EMPTY_FILTERED: a reason and the action that fixes it. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="bg-card rounded-xl border border-dashed px-6 py-12 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="text-muted-foreground mt-2 text-sm">{children}</div>}
    </div>
  );
}

/** ERROR: a plain message and Retry. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="bg-danger-soft border-destructive/40 flex items-center gap-3 rounded-xl border px-4 py-3"
    >
      <AlertTriangle className="text-destructive size-5 shrink-0" />
      <p className="text-destructive flex-1 text-sm">{errorText(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

/** ACTION_PENDING: the button keeps its size and shows a spinner. */
export function Busy({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <>
      {busy && <Loader2 className="animate-spin" aria-hidden />}
      {children}
    </>
  );
}

/** NOT_FOUND inside the admin layout: same message whether missing or not ours. */
export function NotFoundBlock({ what, back }: { what: string; back: string }) {
  return (
    <EmptyState title={`This ${what} doesn't exist, or you don't have access to it.`}>
      <Button variant="outline" size="sm" asChild>
        <Link to={back}>Go back</Link>
      </Button>
    </EmptyState>
  );
}

/** "Are you sure?" for actions that are hard to undo. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={busy}>
            <Busy busy={busy}>{confirmLabel}</Busy>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Table wrapper with the card look used on every admin page. */
export function TableCard({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("bg-card shadow-card overflow-hidden rounded-xl border", className)}>
      {children}
    </div>
  );
}
