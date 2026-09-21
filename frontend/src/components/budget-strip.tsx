"use client";

import { AlertTriangle } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useBudget } from "@/hooks/use-clearcut";
import { money, moneyRange } from "@/lib/format";

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="flex min-w-36 flex-col gap-0.5 px-4 py-3">
      <span className="text-xs uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums leading-tight">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}

/** Project-level money at a glance. Estimates are ranges, never quotes. */
export function BudgetStrip({ projectId }: { projectId: string }) {
  const { data, isLoading } = useBudget(projectId);

  if (isLoading) return <Skeleton className="h-20 w-full" />;
  if (!data) return null;

  return (
    <div className="flex flex-wrap items-stretch divide-x divide-border overflow-hidden rounded-xl border border-border bg-card">
      <Stat
        label="Estimate"
        value={moneyRange(data.estimate_low, data.estimate_high)}
        hint={`${data.active_tasks} active task${data.active_tasks === 1 ? "" : "s"}`}
      />
      <Stat
        label="Contingency"
        value={money(data.recommended_contingency)}
        hint="15% recommended"
      />
      <Stat label="Quoted" value={money(data.quoted_total)} />
      <Stat label="Agreed" value={money(data.agreed_total)} />
      {data.unestimated_tasks > 0 && (
        <div className="flex items-center gap-2 px-4 py-3 text-xs text-amber-700 dark:text-amber-300">
          <AlertTriangle className="size-4 shrink-0" />
          {data.unestimated_tasks} task{data.unestimated_tasks === 1 ? " has" : "s have"} no
          rate card yet
        </div>
      )}
    </div>
  );
}
