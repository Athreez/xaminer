import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Centred card used by login, activation and password reset (FRONTEND_SPEC § 5.0). */
export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between px-6 py-4">
        <span className="text-brand-gradient text-xl font-bold">Xaminer</span>
        <ThemeToggle />
      </header>
      <main className="grid flex-1 place-items-center px-4 pb-16">
        <div className="bg-card shadow-card w-full max-w-md rounded-2xl border p-8">
          <div className="bg-brand-gradient shadow-glow text-primary-foreground mb-5 grid size-12 place-items-center rounded-xl">
            <ShieldCheck className="size-6" />
          </div>
          <h1 className="text-brand-gradient text-2xl font-bold">{title}</h1>
          {subtitle && <div className="text-muted-foreground mt-1">{subtitle}</div>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
    </div>
  );
}

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

export function PasswordInput(
  props: Omit<React.ComponentProps<typeof Input>, "type"> & { autoComplete: string },
) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className="pr-12" />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="absolute top-1/2 right-1.5 -translate-y-1/2"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        onClick={() => setVisible(!visible)}
      >
        {visible ? <EyeOff /> : <Eye />}
      </Button>
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
