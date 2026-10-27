import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { getThemeChoice, onThemeChange, setThemeChoice, type ThemeChoice } from "@/lib/theme";

const NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<ThemeChoice, string> = {
  system: "Theme: device setting",
  light: "Theme: light",
  dark: "Theme: dark",
};

/** Cycles device setting -> light -> dark. Always labelled, never icon-only for screen readers. */
export function ThemeToggle() {
  const choice = useSyncExternalStore(onThemeChange, getThemeChoice);
  const Icon = choice === "dark" ? Moon : choice === "light" ? Sun : Monitor;
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`${LABEL[choice]}. Switch to ${LABEL[NEXT[choice]].toLowerCase()}`}
      title={LABEL[choice]}
      onClick={() => setThemeChoice(NEXT[choice])}
    >
      <Icon />
    </Button>
  );
}
