/**
 * Opening and downloading authenticated files.
 *
 * Once the API required a bearer token, a plain `<a href>` to an API URL stopped working:
 * a browser navigation cannot carry an Authorization header, so every export and preview
 * link came back 401. Putting the token in the query string would fix it and would also
 * write a live credential into browser history, referrer headers and server logs.
 *
 * So the file is fetched with the header like any other request and handed to the browser
 * as a blob instead. The object URL is revoked once the browser has taken it.
 */

import { ApiError } from "@/lib/api";
import { getToken } from "@/lib/auth-store";

// A new tab needs a moment to read the blob before the URL is revoked; a download is
// instantaneous but the same delay costs nothing.
const REVOKE_AFTER_MS = 60_000;

async function fetchAuthed(url: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(url, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = (await res.json())?.detail ?? null;
    } catch {
      detail = await res.text().catch(() => null);
    }
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

function filenameFrom(url: string, fallback: string): string {
  const last = url.split("?")[0].split("/").pop();
  return last && last.includes(".") ? last : fallback;
}

/**
 * Open an authenticated URL in a new tab.
 *
 * The tab is claimed **synchronously**, before the fetch is awaited. A `window.open` after
 * an await has lost the user gesture, so default Chrome and Safari block it — and the
 * promise still resolves, so nothing surfaces the failure. Opening first and setting
 * `location` afterwards keeps the gesture; if the popup was blocked anyway, this falls back
 * to downloading rather than silently doing nothing.
 */
export async function openAuthed(url: string): Promise<void> {
  const tab = window.open("", "_blank", "noopener,noreferrer");
  let blob: Blob;
  try {
    blob = await fetchAuthed(url);
  } catch (error) {
    tab?.close();
    throw error;
  }

  const objectUrl = URL.createObjectURL(blob);
  if (tab && !tab.closed) {
    tab.location = objectUrl;
  } else {
    await saveBlob(blob, filenameFrom(url, "download"));
    URL.revokeObjectURL(objectUrl);
    return;
  }
  setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_AFTER_MS);
}

async function saveBlob(blob: Blob, filename: string): Promise<void> {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_AFTER_MS);
}

/** Save an authenticated URL to disk. A download link needs no popup permission. */
export async function downloadAuthed(url: string, filename?: string): Promise<void> {
  await saveBlob(await fetchAuthed(url), filename ?? filenameFrom(url, "download"));
}
