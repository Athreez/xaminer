// Runs before the page draws so dark-mode users never see a white flash. Kept in sync with
// src/lib/theme.ts (same storage key and rules).
(function () {
  var choice = "system";
  try {
    choice = localStorage.getItem("xaminer-theme") || "system";
  } catch {
    // storage blocked: follow the device setting
  }
  var dark =
    choice === "dark" ||
    (choice === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
})();
