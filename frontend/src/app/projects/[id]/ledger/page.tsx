"use client";

import { useParams } from "next/navigation";
import { TrendingDown, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useLedger } from "@/hooks/use-clearcut";
import { money, moneyRange } from "@/lib/format";
import { LAYER_LABEL, LEDGER_BASIS_LABEL, STAGE_LABEL } from "@/lib/labels";
import type { LedgerLine } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function LedgerPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useLedger(id);

  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;
  const { lines, totals } = data;

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Exposure"
          value={money(totals.exposure)}
          hint="The firmest figure per task — signed where signed, quoted where quoted, estimated otherwise"
        />
        <Stat
          label="Still estimated"
          value={money(totals.recommended_contingency)}
          hint="15% contingency, applied only to the part still being guessed"
        />
        <Stat label="Committed" value={money(totals.committed)} hint="Deal memos signed" />
        <Stat
          label="Awaiting reply"
          value={String(totals.awaiting_reply)}
          hint="Tasks sitting at outreach sent"
        />
      </div>

      {totals.priced_tasks > 0 && (
        <Card
          className={cn(
            Number(totals.variance_total) > 0
              ? "border-rose-300/60 bg-rose-50/40 dark:border-rose-900/60 dark:bg-rose-950/20"
              : "border-emerald-300/60 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20",
          )}
        >
          <CardContent className="flex gap-3 p-4 text-sm">
            {Number(totals.variance_total) > 0 ? (
              <TrendingUp className="mt-0.5 size-4 shrink-0 text-rose-700 dark:text-rose-300" />
            ) : (
              <TrendingDown className="mt-0.5 size-4 shrink-0 text-emerald-700 dark:text-emerald-300" />
            )}
            <p>
              Across {totals.priced_tasks} priced task{totals.priced_tasks === 1 ? "" : "s"}, real
              figures come in{" "}
              <strong>
                {money(String(Math.abs(Number(totals.variance_total))))}{" "}
                {Number(totals.variance_total) > 0 ? "above" : "below"}
              </strong>{" "}
              the top of their estimates.{" "}
              {totals.over_estimate_tasks > 0 && (
                <>
                  {totals.over_estimate_tasks} broke the estimate, the worst by{" "}
                  {money(totals.worst_variance)}.
                </>
              )}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Asset / layer</th>
              <th className="px-3 py-2 text-left font-medium">Rightsholder</th>
              <th className="px-3 py-2 text-right font-medium">Estimated</th>
              <th className="px-3 py-2 text-right font-medium">Quoted</th>
              <th className="px-3 py-2 text-right font-medium">Signed</th>
              <th className="px-3 py-2 text-right font-medium">Variance</th>
              <th className="px-3 py-2 text-right font-medium">Holding</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {lines.map((line) => (
              <Row key={line.task_id} line={line} />
            ))}
            {lines.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-10 text-center text-muted-foreground">
                  Nothing to track yet.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot className="border-t-2 border-border bg-muted/40 font-medium">
            <tr>
              <td className="px-3 py-2" colSpan={2}>
                {totals.live_tasks} live
                {totals.closed_tasks > 0 && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {totals.closed_tasks} closed, excluded from totals
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {moneyRange(totals.estimate_low, totals.estimate_high)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{money(totals.quoted_total)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(totals.agreed_total)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(totals.variance_total)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(totals.exposure)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function Row({ line }: { line: LedgerLine }) {
  const variance = line.variance === null ? null : Number(line.variance);
  return (
    <tr className={cn(line.closed && "text-muted-foreground line-through decoration-1")}>
      <td className="max-w-72 px-3 py-2">
        <span className="line-clamp-1">{line.asset_title ?? "Untitled"}</span>
        <span className="text-xs text-muted-foreground">
          {LAYER_LABEL[line.layer]} · {STAGE_LABEL[line.stage]}
        </span>
      </td>
      <td className="max-w-48 truncate px-3 py-2 text-muted-foreground">
        {line.rightsholder_name ?? "Unassigned"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {moneyRange(line.estimate_low, line.estimate_high)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{money(line.quoted)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{money(line.agreed)}</td>
      <td
        className={cn(
          "px-3 py-2 text-right tabular-nums",
          variance !== null &&
            (variance > 0
              ? "text-rose-700 dark:text-rose-400"
              : variance < 0
                ? "text-emerald-700 dark:text-emerald-400"
                : undefined),
        )}
      >
        {variance === null ? "—" : `${variance > 0 ? "+" : ""}${money(line.variance)}`}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {money(line.exposure)}
        <Badge variant="muted" className="ml-2 text-[10px]">
          {LEDGER_BASIS_LABEL[line.basis]}
        </Badge>
      </td>
    </tr>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
        <p className="mt-1 text-xs leading-snug text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}
