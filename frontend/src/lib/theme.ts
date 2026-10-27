/**
 * Light / dark mode (FRONTEND_SPEC.md § 3.1). Follows the device setting unless the user picks one.
 * The choice is a per-browser convenience in localStorage (may be unavailable: then "system").
 * Proctored exam screens force light, because the screen lights the student's face.
 */

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "xaminer-theme";
const listeners = new Set<() => void>();

export function getThemeChoice(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // storage blocked (private mode, policy): fall back to the device setting
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

let forcedLight = false;

export function applyTheme(): void {
  const choice = getThemeChoice();
  const dark = !forcedLight && (choice === "dark" || (choice === "system" && systemPrefersDark()));
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function setThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // not saved; still applied for this page
  }
  applyTheme();
  listeners.forEach((notify) => notify());
}

/** Used by the proctored exam screen: light no matter what, until released. */
export function forceLightTheme(force: boolean): void {
  forcedLight = force;
  applyTheme();
}

export function onThemeChange(notify: () => void): () => void {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => getThemeChoice() === "system" && applyTheme());
