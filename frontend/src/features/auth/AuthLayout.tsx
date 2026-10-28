import { Eye, EyeOff, ShieldCheck } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
