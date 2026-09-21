"use client";

import * as React from "react";
import { Calculator, Mail, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { AuditHistory } from "@/components/audit-history";
import { RightsholderPicker } from "@/components/rightsholder-picker";
import { StageBadge } from "@/components/stage-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import {
  useEstimateTask,
  useTaskHistory,
  useTransition,
  useUpdateTask,
} from "@/hooks/use-clearcut";
import { money, moneyRange } from "@/lib/format";
import { LAYER_LABEL, STAGE_LABEL } from "@/lib/labels";
import type { Stage, Task } from "@/lib/types";

/** Mirrors workflow.REASSIGNABLE on the server. */
const REASSIGNABLE: Stage[] = ["sourced", "rights_mapped", "budget_approved"];

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

export function TaskDrawer({
  projectId,
  task,
  assetTitle,
  onOpenChange,
}: {
  projectId: string;
  task: Task | null;
  assetTitle?: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet open={task !== null} onOpenChange={onOpenChange}>
      <SheetContent className="gap-0 overflow-y-auto">
        {task && (
          // Keyed so opening a different task mounts a fresh form instead of
          // carrying the previous task's unsaved quote and notes across.
          <TaskDrawerBody
            key={task.id}
            projectId={projectId}
            task={task}
            assetTitle={assetTitle}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function TaskDrawerBody({
  projectId,
  task,
  assetTitle,
}: {
  projectId: string;
  task: Task;
  assetTitle?: string | null;
}) {
  const update = useUpdateTask(projectId);
  const move = useTransition(projectId);
  const estimate = useEstimateTask(projectId);
  const history = useTaskHistory(task.id, true);

  const [quoted, setQuoted] = React.useState(task.quoted_amount ?? "");
  const [agreed, setAgreed] = React.useState(task.agreed_amount ?? "");
  const [notes, setNotes] = React.useState(task.notes ?? "");

  const reassignable = REASSIGNABLE.includes(task.stage);
  const breakdown = task.estimate_breakdown;
  const dirty =
    (quoted || "") !== (task.quoted_amount ?? "") ||
    (agreed || "") !== (task.agreed_amount ?? "") ||
    (notes || "") !== (task.notes ?? "");

  const saveFields = () => {
    const body: Record<string, string | null> = {};
    if ((quoted || "") !== (task.quoted_amount ?? "")) body.quoted_amount = quoted || null;
    if ((agreed || "") !== (task.agreed_amount ?? "")) body.agreed_amount = agreed || null;
    if ((notes || "") !== (task.notes ?? "")) body.notes = notes || null;
    if (Object.keys(body).length === 0) return;

    update.mutate(
      { taskId: task.id, body },
      { onSuccess: () => toast.success("Task saved") },
    );
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle className="text-base">{assetTitle ?? "Untitled asset"}</SheetTitle>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Badge variant="secondary">{LAYER_LABEL[task.layer]}</Badge>
          <StageBadge stage={task.stage} />
        </div>
      </SheetHeader>

      <div className="mt-6 flex flex-col gap-6">
        <Section title="Move to">
          {task.allowed_transitions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This task is closed. Nothing left to move.
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {task.allowed_transitions.map((stage) => (
                <Button
                  key={stage}
                  size="sm"
                  variant={stage === "denied" || stage === "dropped" ? "outline" : "default"}
                  disabled={move.isPending}
                  onClick={() =>
                    move.mutate(
                      { taskId: task.id, to: stage },
                      {
                        onSuccess: () =>
                          toast.success(`Moved to ${STAGE_LABEL[stage].toLowerCase()}`),
                      },
                    )
                  }
                >
                  {STAGE_LABEL[stage]}
                </Button>
              ))}
            </div>
          )}
        </Section>

        <Separator />

        <Section title="Rightsholder">
          <RightsholderPicker
            layer={task.layer}
            current={task.rightsholder}
            disabled={!reassignable}
            disabledReason={`Rightsholder is locked once a task reaches ${STAGE_LABEL[task.stage].toLowerCase()}.`}
            pending={update.isPending}
            onSelect={(id) =>
              update.mutate({
                taskId: task.id,
                body: { rightsholder_id: id, reason: "Manual assignment from the task drawer" },
              })
            }
            onClear={() =>
              update.mutate({
                taskId: task.id,
                body: { rightsholder_id: null, reason: "Unassigned from the task drawer" },
              })
            }
          />

          {task.mapping_method && (
            <p className="text-xs text-muted-foreground">
              Matched by {task.mapping_method}
              {task.mapping_confidence !== null
                ? ` · confidence ${Math.round(task.mapping_confidence)}`
                : ""}
            </p>
          )}

          {task.contact?.licensing_email && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Mail className="size-3.5" />
              {task.contact.licensing_email}
              {task.contact.via_name && task.contact.via_rightsholder_id !== task.rightsholder?.id
                ? ` (via ${task.contact.via_name})`
                : ""}
              {task.contact.is_placeholder && (
                <Badge variant="outline" className="ml-1 text-[10px]">
                  unverified
                </Badge>
              )}
            </p>
          )}

          {task.mapping_candidates.length > 0 && !task.rightsholder && (
            <div className="mt-1 flex flex-col gap-1.5 rounded-lg border border-border p-2">
              <p className="flex items-center gap-1.5 text-xs font-medium">
                <Sparkles className="size-3.5" /> Match candidates
              </p>
              {task.mapping_candidates.map((candidate) => (
                <button
                  key={candidate.rightsholder_id}
                  type="button"
                  disabled={!reassignable || update.isPending}
                  onClick={() =>
                    update.mutate({
                      taskId: task.id,
                      body: {
                        rightsholder_id: candidate.rightsholder_id,
                        reason: `Accepted matcher candidate (score ${Math.round(candidate.score)})`,
                      },
                    })
                  }
                  className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent disabled:opacity-50"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{candidate.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      matched &ldquo;{candidate.matched_alias}&rdquo; against &ldquo;
                      {candidate.matched_query}&rdquo;
                    </span>
                  </span>
                  <Badge variant="muted">{Math.round(candidate.score)}</Badge>
                </button>
              ))}
            </div>
          )}
        </Section>

        <Separator />

        <Section
          title="Estimate"
          action={
            <Button
              variant="ghost"
              size="sm"
              disabled={estimate.isPending}
              onClick={() =>
                estimate.mutate(task.id, {
                  onSuccess: () => toast.success("Estimate refreshed"),
                })
              }
            >
              <Calculator /> Re-run
            </Button>
          }
        >
          <p className="text-xl font-semibold tabular-nums">
            {moneyRange(task.estimate_low, task.estimate_high)}
          </p>
          {breakdown?.summary && (
            <p className="text-sm text-muted-foreground">{breakdown.summary}</p>
          )}
          {breakdown?.formula && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-muted/60 p-3 text-xs">
              <dt className="text-muted-foreground">Base range</dt>
              <dd className="text-right tabular-nums">
                {money(breakdown.base_low)} – {money(breakdown.base_high)}
              </dd>
              <dt className="text-muted-foreground">Units</dt>
              <dd className="text-right tabular-nums">
                {breakdown.units} {breakdown.unit?.replace(/_/g, " ")}
              </dd>
              <dt className="text-muted-foreground">Distribution</dt>
              <dd className="text-right tabular-nums">×{breakdown.distribution_multiplier}</dd>
              <dt className="text-muted-foreground">Tier</dt>
              <dd className="text-right tabular-nums">×{breakdown.tier_factor}</dd>
              <dt className="text-muted-foreground">Rate basis</dt>
              <dd className="text-right">{breakdown.rate_basis}</dd>
            </dl>
          )}
          {breakdown?.assumptions?.map((line) => (
            <p key={line} className="text-xs text-amber-700 dark:text-amber-300">
              {line}
            </p>
          ))}
        </Section>

        <Separator />

        <Section title="Money on the table">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="quoted">Quoted</Label>
              <Input
                id="quoted"
                inputMode="decimal"
                value={quoted}
                onChange={(e) => setQuoted(e.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="agreed">Agreed</Label>
              <Input
                id="agreed"
                inputMode="decimal"
                value={agreed}
                onChange={(e) => setAgreed(e.target.value)}
                placeholder="0.00"
              />
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="task-notes">Notes</Label>
            <Textarea
              id="task-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Who you spoke to, what they said."
            />
          </div>
          <Button
            size="sm"
            className="w-fit"
            disabled={!dirty || update.isPending}
            onClick={saveFields}
          >
            {update.isPending ? "Saving…" : "Save"}
          </Button>
          <p className="text-xs text-muted-foreground">
            A quote is required before the task can move to quote received; an agreed fee
            before the deal memo is signed.
          </p>
        </Section>

        <Separator />

        <Section title="History">
          <AuditHistory entries={history.data} isLoading={history.isLoading} />
        </Section>
      </div>
    </>
  );
}
