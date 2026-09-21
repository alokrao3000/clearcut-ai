const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

/** Money arrives as a Decimal string; render em dash when the server has no number. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? USD.format(n) : "—";
}

export function moneyRange(
  low: string | null | undefined,
  high: string | null | undefined,
): string {
  if (!low && !high) return "Not estimated";
  if (low === high) return money(low);
  return `${money(low)} – ${money(high)}`;
}

export function duration(seconds: number | null | undefined): string {
  if (!seconds && seconds !== 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s.toString().padStart(2, "0")}s` : `${s}s`;
}

export function relativeTime(iso: string): string {
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  const diff = Date.now() - then.getTime();
  const mins = Math.round(diff / 60000);
  if (Number.isNaN(mins)) return iso;
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return then.toLocaleDateString();
}

export function absoluteTime(iso: string): string {
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
