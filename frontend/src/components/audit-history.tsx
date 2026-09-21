"use client";

import { Bot, Cpu, Spline, User } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { absoluteTime, relativeTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";

const ACTOR_ICON = {
  user: User,
  system: Cpu,
  scraper: Spline,
  llm: Bot,
} as const;

const MAX_VALUE_CHARS = 90;

/** Ledger values are raw JSON; an estimate_breakdown blob would swamp the drawer. */
function fieldValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") {
    const json = JSON.stringify(value);
    return json.length > MAX_VALUE_CHARS ? `${json.slice(0, MAX_VALUE_CHARS)}…` : json;
  }
  const text = String(value);
  return text.length > MAX_VALUE_CHARS ? `${text.slice(0, MAX_VALUE_CHARS)}…` : text;
}

/** Field-level diffs from the application audit ledger, oldest first. */
export function AuditHistory({
  entries,
  isLoading,
}: {
  entries: AuditEntry[] | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    );
  }

  if (!entries?.length) {
    return <p className="text-sm text-muted-foreground">No changes recorded yet.</p>;
  }

  return (
    <ol className="flex flex-col gap-3">
      {entries.map((entry) => {
        const Icon = ACTOR_ICON[entry.actor_type] ?? User;
        const changes = Object.entries(entry.changes ?? {});
        return (
          <li key={entry.id} className="flex gap-3 text-sm">
            <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
              <Icon className="size-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="capitalize">
                  {entry.action}
                </Badge>
                <span className="font-mono text-xs text-muted-foreground">
                  {entry.actor_type}:{entry.actor_id}
                </span>
                <span
                  className="ml-auto text-xs text-muted-foreground"
                  title={absoluteTime(entry.at)}
                >
                  {relativeTime(entry.at)}
                </span>
              </div>

              {entry.reason && (
                <p className="mt-1 text-xs italic text-muted-foreground">{entry.reason}</p>
              )}

              {changes.length > 0 && (
                <dl className="mt-1.5 grid gap-1">
                  {changes.map(([field, delta]) => {
                    // The ledger writes updates as [old, new] and inserts as a bare value.
                    const isPair = Array.isArray(delta) && delta.length === 2;
                    const [before, after] = isPair
                      ? (delta as [unknown, unknown])
                      : [undefined, delta];
                    return (
                      <div key={field} className="flex flex-wrap items-baseline gap-1.5">
                        <dt className="font-mono text-xs text-muted-foreground">{field}</dt>
                        <dd className="min-w-0 break-all text-xs">
                          {isPair && before !== null && before !== undefined && (
                            <>
                              <span className="text-muted-foreground line-through">
                                {fieldValue(before)}
                              </span>
                              <span className="mx-1 text-muted-foreground">→</span>
                            </>
                          )}
                          <span className="font-medium">{fieldValue(after)}</span>
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
