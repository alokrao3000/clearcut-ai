"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { Calculator, Info } from "lucide-react";
import { toast } from "sonner";

import { TaskDrawer } from "@/components/task-drawer";
import { rowsFromAssets, type TaskRow } from "@/components/task-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAssets, useBudget, useReestimateProject } from "@/hooks/use-clearcut";
import { money, moneyRange } from "@/lib/format";
import { LAYER_LABEL } from "@/lib/labels";
import { LAYERS, type Layer } from "@/lib/types";

const CLOSED = new Set(["denied", "dropped"]);

export default function BudgetPage() {
  const { id } = useParams<{ id: string }>();
  const { data: assets, isLoading } = useAssets(id);
  const { data: totals } = useBudget(id);
  const reestimate = useReestimateProject(id);
  const [openTaskId, setOpenTaskId] = React.useState<string | null>(null);

  const rows = React.useMemo(() => rowsFromAssets(assets), [assets]);
  const active = React.useMemo(() => rows.filter((r) => !CLOSED.has(r.task.stage)), [rows]);
  const openRow = rows.find((r) => r.task.id === openTaskId) ?? null;

  const byLayer = React.useMemo(() => {
    const groups = new Map<Layer, TaskRow[]>();
    for (const row of active) {
      const list = groups.get(row.task.layer) ?? [];
      list.push(row);
      groups.set(row.task.layer, list);
    }
    return LAYERS.filter((l) => groups.has(l)).map((layer) => {
      const items = groups.get(layer)!;
      const low = items.reduce((sum, r) => sum + Number(r.task.estimate_low ?? 0), 0);
      const high = items.reduce((sum, r) => sum + Number(r.task.estimate_high ?? 0), 0);
      return { layer, items, low, high };
    });
  }, [active]);

  const unpriced = active.filter((r) => r.task.estimate_high === null);
  const placeholderCount = active.filter((r) =>
    r.task.estimate_breakdown?.assumptions?.some((a) => a.includes("placeholder")),
  ).length;

  if (isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          disabled={reestimate.isPending}
          onClick={() =>
            reestimate.mutate(undefined, {
              onSuccess: () => toast.success("Budget matrix re-run on unapproved tasks"),
            })
          }
        >
          <Calculator /> {reestimate.isPending ? "Recalculating…" : "Re-run budget matrix"}
        </Button>
        <p className="text-xs text-muted-foreground">
          Approved budgets are left alone — move a task back to rights mapped to re-price it.
        </p>
      </div>

      {placeholderCount > 0 && (
        <Card className="border-amber-300/60 bg-amber-50/50 dark:border-amber-900/60 dark:bg-amber-950/20">
          <CardContent className="flex gap-3 p-4 text-sm">
            <Info className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" />
            <p>
              {placeholderCount} of {active.length} estimates rest on unverified placeholder
              rate cards. Treat every number here as a planning range, never a quote.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Layer / asset</th>
              <th className="px-3 py-2 text-left font-medium">Rightsholder</th>
              <th className="px-3 py-2 text-right font-medium">Estimate</th>
              <th className="px-3 py-2 text-right font-medium">Quoted</th>
              <th className="px-3 py-2 text-right font-medium">Agreed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {byLayer.map(({ layer, items, low, high }) => (
              <React.Fragment key={layer}>
                <tr className="bg-muted/30">
                  <td className="px-3 py-2 font-medium" colSpan={2}>
                    {LAYER_LABEL[layer]}
                    <span className="ml-2 text-xs font-normal text-muted-foreground">
                      {items.length} task{items.length === 1 ? "" : "s"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums">
                    {money(String(low))} – {money(String(high))}
                  </td>
                  <td colSpan={2} />
                </tr>
                {items.map((row) => (
                  <tr
                    key={row.task.id}
                    onClick={() => setOpenTaskId(row.task.id)}
                    className="cursor-pointer hover:bg-accent/50"
                  >
                    <td className="max-w-80 truncate px-3 py-2 pl-8">{row.assetTitle}</td>
                    <td className="max-w-56 truncate px-3 py-2 text-muted-foreground">
                      {row.task.rightsholder?.name ?? "Unassigned"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {moneyRange(row.task.estimate_low, row.task.estimate_high)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {money(row.task.quoted_amount)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {money(row.task.agreed_amount)}
                    </td>
                  </tr>
                ))}
              </React.Fragment>
            ))}

            {active.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-10 text-center text-muted-foreground">
                  Nothing to price yet.
                </td>
              </tr>
            )}
          </tbody>
          {totals && active.length > 0 && (
            <tfoot className="border-t-2 border-border bg-muted/40 font-medium">
              <tr>
                <td className="px-3 py-2" colSpan={2}>
                  Project total
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {moneyRange(totals.estimate_low, totals.estimate_high)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {money(totals.quoted_total)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {money(totals.agreed_total)}
                </td>
              </tr>
              <tr className="text-muted-foreground">
                <td className="px-3 py-2" colSpan={2}>
                  With 15% contingency
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {money(
                    String(
                      Number(totals.estimate_high) + Number(totals.recommended_contingency),
                    ),
                  )}
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {unpriced.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">No rate card yet:</span>
          {unpriced.map((row) => (
            <Badge
              key={row.task.id}
              variant="outline"
              className="cursor-pointer"
              onClick={() => setOpenTaskId(row.task.id)}
            >
              {row.assetTitle.slice(0, 28)} · {LAYER_LABEL[row.task.layer]}
            </Badge>
          ))}
        </div>
      )}

      <TaskDrawer
        projectId={id}
        task={openRow?.task ?? null}
        assetTitle={openRow?.assetTitle}
        onOpenChange={(open) => !open && setOpenTaskId(null)}
      />
    </div>
  );
}
