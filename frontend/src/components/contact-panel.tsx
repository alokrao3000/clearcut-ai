"use client";

import * as React from "react";
import {
  ExternalLink,
  Mail,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useResolveContacts, useTaskContacts } from "@/hooks/use-clearcut";
import { moneyRange } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { ContactOption, RecommendedContact, ResearchLead } from "@/lib/types";

function Meter({
  label,
  value,
  hint,
}: {
  label: string;
  value: number;
  hint?: string;
}) {
  const tone =
    value >= 80 ? "bg-emerald-500" : value >= 60 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex flex-col gap-1" title={hint}>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="tabular-nums font-medium">{Math.round(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
    </div>
  );
}

function OptionRow({ option, muted }: { option: ContactOption; muted?: boolean }) {
  const [open, setOpen] = React.useState(false);
  const components = option.reliability_breakdown?.components ?? {};

  return (
    <div className={cn("rounded-lg border border-border p-3", muted && "opacity-70")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{option.name}</span>
          <span className="block truncate text-xs text-muted-foreground">
            {option.contact.licensing_email ?? "no licensing intake on file"}
          </span>
        </span>
        <span className="shrink-0 text-right text-xs tabular-nums">
          {moneyRange(option.cost_low, option.cost_high)}
        </span>
      </button>

      <div className="mt-2 grid grid-cols-2 gap-3">
        <Meter label="Can grant it" value={option.identity} hint="Confidence they own this right" />
        <Meter label="Will respond" value={option.reliability} hint="Standing, verification, contactability" />
      </div>

      {option.blockers.map((blocker) => (
        <p key={blocker} className="mt-2 flex gap-1.5 text-xs text-amber-700 dark:text-amber-300">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          {blocker}
        </p>
      ))}

      {open && (
        <div className="mt-3 flex flex-col gap-2 border-t border-border pt-2">
          {Object.entries(components).map(([name, component]) => (
            <div key={name} className="flex items-baseline justify-between gap-3 text-xs">
              <span className="text-muted-foreground">{component.note}</span>
              <span className="shrink-0 tabular-nums">
                {Math.round(component.score)}
                <span className="text-muted-foreground"> ×{component.weight}</span>
              </span>
            </div>
          ))}
          {option.evidence.map((item) => (
            <p key={item.excerpt} className="text-xs text-muted-foreground">
              <Badge variant="outline" className="mr-1.5 text-[10px]">
                {item.claim_type.replace(/_/g, " ")}
              </Badge>
              &ldquo;{item.excerpt}&rdquo;{" "}
              <span className="opacity-70">({item.source_field})</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function Recommended({ pick }: { pick: RecommendedContact }) {
  return (
    <div className="rounded-lg border border-emerald-500/40 bg-emerald-50/40 p-3 dark:bg-emerald-950/20">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-700 dark:text-emerald-300" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{pick.name}</p>
          {pick.contact.licensing_email && (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Mail className="size-3" />
              {pick.contact.licensing_email}
              {pick.contact.is_placeholder && (
                <Badge variant="outline" className="text-[10px]">
                  unverified
                </Badge>
              )}
            </p>
          )}
        </div>
        <span className="shrink-0 text-right text-xs tabular-nums">
          {moneyRange(pick.cost_low, pick.cost_high)}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <Meter label="Can grant it" value={pick.identity} />
        <Meter label="Will respond" value={pick.reliability} />
      </div>

      <ul className="mt-3 flex flex-col gap-1">
        {(pick.why ?? pick.reasons).map((reason) => (
          <li key={reason} className="text-xs text-muted-foreground">
            • {reason}
          </li>
        ))}
      </ul>

      {pick.cheaper_alternative && (
        <p className="mt-2 flex gap-1.5 rounded-md bg-muted/60 p-2 text-xs">
          <Wallet className="mt-0.5 size-3.5 shrink-0" />
          <span>
            <span className="font-medium">{pick.cheaper_alternative.name}</span> is cheaper at{" "}
            {moneyRange(pick.cheaper_alternative.cost_low, pick.cheaper_alternative.cost_high)}, but
            scores {Math.round(pick.cheaper_alternative.reliability)} on reliability.
          </span>
        </p>
      )}
    </div>
  );
}

function Leads({ leads }: { leads: ResearchLead[] }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        Nothing in the directory is a credible owner. These registries are where this gets
        settled by hand:
      </p>
      {leads.map((lead) => (
        <a
          key={lead.source}
          href={lead.url}
          target="_blank"
          rel="noreferrer noopener"
          className="group rounded-lg border border-border p-2.5 hover:bg-accent/60"
        >
          <span className="flex items-center gap-1.5 text-sm font-medium">
            {lead.label}
            <ExternalLink className="size-3 opacity-0 transition-opacity group-hover:opacity-70" />
            {lead.automatable && (
              <Badge variant="secondary" className="text-[10px]">
                key configured
              </Badge>
            )}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{lead.why}</span>
        </a>
      ))}
    </div>
  );
}

export function ContactPanel({ projectId, taskId }: { projectId: string; taskId: string }) {
  const { data, isLoading } = useTaskContacts(taskId, true);
  const resolve = useResolveContacts(projectId);
  const [showAll, setShowAll] = React.useState(false);

  if (isLoading) return <Skeleton className="h-28" />;

  const options = data?.options ?? [];
  const recommended = data?.recommended ?? null;
  const others = options.filter((o) => o.rightsholder_id !== recommended?.rightsholder_id);

  return (
    <div className="flex flex-col gap-3">
      {recommended ? (
        <Recommended pick={recommended} />
      ) : (
        <Leads leads={data?.research_leads ?? []} />
      )}

      {others.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="w-fit text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            {showAll ? "Hide" : `Show ${others.length} other option${others.length === 1 ? "" : "s"}`}
          </button>
          {showAll && (
            <div className="flex flex-col gap-2">
              {others.map((option) => (
                <OptionRow key={option.rightsholder_id} option={option} muted={!!option.blockers.length} />
              ))}
            </div>
          )}
        </>
      )}

      <Button
        variant="ghost"
        size="sm"
        className="w-fit text-muted-foreground"
        disabled={resolve.isPending}
        onClick={() =>
          resolve.mutate(taskId, { onSuccess: () => toast.success("Contacts re-ranked") })
        }
      >
        <RefreshCw /> Re-run
      </Button>
    </div>
  );
}
