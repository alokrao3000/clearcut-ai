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

/** Open an authenticated URL in a new tab. */
export async function openAuthed(url: string): Promise<void> {
  const blob = await fetchAuthed(url);
  const objectUrl = URL.createObjectURL(blob);
  window.open(objectUrl, "_blank", "noopener,noreferrer");
  setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_AFTER_MS);
}

/** Save an authenticated URL to disk. */
export async function downloadAuthed(url: string, filename?: string): Promise<void> {
  const blob = await fetchAuthed(url);
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename ?? filenameFrom(url, "download");
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_AFTER_MS);
}
