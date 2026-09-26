"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, FileDown, FileText, ShieldCheck, Table2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useExportSummary, usePdfStatus } from "@/hooks/use-clearcut";
import { api } from "@/lib/api";
import { downloadAuthed, openAuthed } from "@/lib/download";
import { absoluteTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { reportError } from "@/hooks/use-clearcut";

/** Actor types, in the order a reviewer cares about them. */
const ACTOR_ORDER = ["user", "system", "scraper", "llm"];

const ACTOR_HINT: Record<string, string> = {
  user: "A named person",
  system: "The matcher and budget matrix",
  scraper: "Metadata fetched from a source",
  llm: "A language model's reading",
};

export default function RecordPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading } = useExportSummary(id);
  const { data: pdf } = usePdfStatus();
  const [busy, setBusy] = React.useState(false);

  // Exports go through an authenticated fetch, so failures surface here rather than as a
  // tab full of JSON.
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      reportError(error, "Could not produce that export");
    } finally {
      setBusy(false);
    }
  };

  if (isLoading || !data) return <Skeleton className="h-96 w-full" />;

  const clean = data.reconciliation.available && data.reconciliation.unmatched === 0;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h2 className="text-sm font-semibold">Clearance record</h2>
        <p className="text-xs text-muted-foreground">
          What an errors-and-omissions reviewer asks for: per item, who decided what, on what
          basis, and when. Generated {absoluteTime(data.generated_at)}.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Rights tracked" value={data.tasks} hint={`${data.unassigned} still unassigned`} />
        <Stat label="Signed" value={data.signed} hint="Agreed fee recorded" />
        <Stat
          label="Human-assigned"
          value={data.assigned_by_a_person}
          hint={`${data.assigned_automatically} assigned by the matcher`}
        />
        <Stat label="Ledger entries" value={data.ledger_entries} hint="Field-level changes" />
      </div>

      <Card
        className={cn(
          clean
            ? "border-emerald-300/60 bg-emerald-50/40 dark:border-emerald-900/60 dark:bg-emerald-950/20"
            : "border-amber-300/60 bg-amber-50/50 dark:border-amber-900/60 dark:bg-amber-950/20",
        )}
      >
        <CardContent className="flex gap-3 p-4 text-sm">
          {clean ? (
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-emerald-700 dark:text-emerald-300" />
          ) : (
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" />
          )}
          <div>
            <p className="font-medium">Independent database check</p>
            <p className="mt-1 text-muted-foreground">{data.reconciliation.note}</p>
          </div>
        </CardContent>
      </Card>

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Who and what made the changes</h3>
        <p className="text-xs text-muted-foreground">
          Every entry records its actor, so an automated decision is distinguishable from a
          human one.
        </p>
        <div className="flex flex-wrap gap-2">
          {ACTOR_ORDER.filter((a) => data.actor_breakdown[a]).map((actor) => (
            <Card key={actor} className="min-w-44 flex-1">
              <CardContent className="p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium capitalize">{actor}</span>
                  <span className="tabular-nums">{data.actor_breakdown[actor]}</span>
                </div>
                <p className="mt-0.5 text-[11px] text-muted-foreground">{ACTOR_HINT[actor]}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Export</h3>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => run(() => openAuthed(api.exportReportUrl(id, "html")))}>
            <FileText /> Printable report
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !pdf?.available}
            title={pdf?.available ? undefined : (pdf?.install_hint ?? "")}
            onClick={() => run(() => downloadAuthed(api.exportReportUrl(id, "pdf")))}
          >
            <FileDown /> {pdf?.available ? "Report PDF" : "PDF unavailable"}
          </Button>
          <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => run(() => downloadAuthed(api.exportRightsCsvUrl(id)))}>
            <Table2 /> Rights CSV
          </Button>
          <Button variant="outline" size="sm" disabled={busy}
                  onClick={() => run(() => downloadAuthed(api.exportLedgerCsvUrl(id)))}>
            <Table2 /> Full ledger CSV
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          The printable report shows the most recent ledger entries; the CSV carries all
          {" "}
          {data.ledger_entries}.
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Progress by stage</h3>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.by_stage).map(([stage, count]) => (
            <Badge key={stage} variant="outline">
              {stage} · {count}
            </Badge>
          ))}
        </div>
      </section>

      <p className="text-xs leading-snug text-muted-foreground">
        {data.disclaimer_text} Disclaimer version {data.disclaimer_version}.
      </p>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint: string }) {
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
