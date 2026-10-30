// Recovering when an open tab outlives a deploy of the app.

/** After a new version is deployed, an open tab asks for page files that no longer exist. */
export function isStaleChunk(error: unknown): boolean {
  const text = error instanceof Error ? error.message : String(error);
  return /dynamically imported module|Importing a module script failed|error loading dynamically/i.test(
    text,
  );
}

const RELOADED = "xaminer:reloaded-for-update";

/**
 * Loads a lazy page; if its file is gone because the app was updated, reloads the page once to
 * pick up the new version (a second failure within a minute is shown as an error).
 */
export async function loadPage<T>(load: () => Promise<T>): Promise<T> {
  try {
    const page = await load();
    sessionStorage.removeItem(RELOADED);
    return page;
  } catch (error) {
    const last = Number(sessionStorage.getItem(RELOADED) ?? 0);
    if (isStaleChunk(error) && Date.now() - last > 60_000) {
      sessionStorage.setItem(RELOADED, String(Date.now()));
      window.location.reload();
      return new Promise<T>(() => {}); // the reload takes over
    }
    throw error;
  }
}
