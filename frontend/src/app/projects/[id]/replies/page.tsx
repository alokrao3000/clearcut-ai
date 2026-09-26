"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, Check, Inbox, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useApplyProposal,
  useInbox,
  useProposals,
  useRejectProposal,
} from "@/hooks/use-clearcut";
import { money, relativeTime } from "@/lib/format";
import {
  LAYER_LABEL,
  PROPOSAL_STATUS_LABEL,
  REPLY_KIND_BADGE,
  REPLY_KIND_LABEL,
  STAGE_LABEL,
} from "@/lib/labels";
import type { ProposedChange } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function RepliesPage() {
  const { id } = useParams<{ id: string }>();
  const { data: pending, isLoading } = useProposals(id, "pending");
  const { data: messages } = useInbox(id);

  if (isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <Card className="border-sky-300/60 bg-sky-50/50 dark:border-sky-900/60 dark:bg-sky-950/20">
        <CardContent className="flex gap-3 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-sky-700 dark:text-sky-300" />
          <p>
            Readings come from a language model and move nothing on their own. Check each one
            against the rightsholder&apos;s own words before confirming — a misread fee becomes a
            number in your budget.
          </p>
        </CardContent>
      </Card>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-sm font-semibold">Awaiting confirmation</h2>
          <p className="text-xs text-muted-foreground">
            {pending?.length ?? 0} proposed change{pending?.length === 1 ? "" : "s"} from replies.
          </p>
        </div>

        {!pending || pending.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              Nothing waiting. Replies appear here once they arrive and have been read.
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-3">
            {pending.map((change) => (
              <ProposalCard key={change.id} projectId={id} change={change} />
            ))}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Inbox</h2>
        {!messages || messages.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              No replies yet.
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-3">
            {messages.map((message) => (
              <Card key={message.id}>
                <CardContent className="flex flex-col gap-2 p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {message.from_name ?? message.from_email}
                        {message.rightsholder_name && (
                          <span className="ml-2 font-normal text-muted-foreground">
                            {message.rightsholder_name}
                          </span>
                        )}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {message.subject ?? "(no subject)"} · {relativeTime(message.received_at)}
                      </p>
                    </div>
                    {message.intent ? (
                      <Badge
                        className={cn("border-transparent", REPLY_KIND_BADGE[message.intent.kind])}
                      >
                        {REPLY_KIND_LABEL[message.intent.kind] ?? message.intent.kind}
                      </Badge>
                    ) : (
                      <Badge variant="muted">
                        <Inbox className="mr-1 size-3" />
                        {message.status === "failed" ? "Could not be read" : "Not read"}
                      </Badge>
                    )}
                  </div>

                  {message.intent && (
                    <p className="text-sm">
                      {message.intent.summary}{" "}
                      <span className="text-xs text-muted-foreground">
                        ({Math.round(message.intent.confidence * 100)}% confident,{" "}
                        {message.intent.model})
                      </span>
                    </p>
                  )}
                  {!message.intent && message.error && (
                    <p className="text-xs text-muted-foreground">{message.error}</p>
                  )}

                  <details className="text-sm">
                    <summary className="cursor-pointer text-xs text-muted-foreground">
                      Show the reply
                    </summary>
                    <p className="mt-2 whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                      {message.text_body}
                    </p>
                  </details>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ProposalCard({ projectId, change }: { projectId: string; change: ProposedChange }) {
  const apply = useApplyProposal(projectId);
  const reject = useRejectProposal(projectId);
  // The parsed figure is a starting point; the producer reads the quote themselves.
  const [amount, setAmount] = React.useState(change.quoted_amount ?? "");

  const needsAmount = Boolean(change.blocked_reason?.includes("No fee named"));
  const blocked = Boolean(change.blocked_reason) && !needsAmount;

  return (
    <Card className={cn(blocked && "border-dashed opacity-90")}>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate font-medium">{change.asset_title ?? "Untitled material"}</p>
            <p className="text-xs text-muted-foreground">
              {change.layer ? LAYER_LABEL[change.layer] : "—"} · {STAGE_LABEL[change.from_stage]}
              {change.to_stage && ` → ${STAGE_LABEL[change.to_stage]}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={cn("border-transparent", REPLY_KIND_BADGE[change.kind])}>
              {REPLY_KIND_LABEL[change.kind] ?? change.kind}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {Math.round(change.confidence * 100)}%
            </span>
          </div>
        </div>

        {change.quote_text && (
          <blockquote className="border-l-2 border-border pl-3 text-sm italic">
            “{change.quote_text}”
          </blockquote>
        )}
        {change.note && <p className="text-xs text-muted-foreground">{change.note}</p>}

        {change.blocked_reason && (
          <p className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            {change.blocked_reason}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {change.to_stage && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Fee</span>
              <Input
                value={amount}
                inputMode="decimal"
                placeholder="0.00"
                className="h-8 w-32"
                onChange={(e) => setAmount(e.target.value)}
              />
              {change.currency && (
                <span className="text-xs text-muted-foreground">{change.currency}</span>
              )}
            </div>
          )}

          <Button
            size="sm"
            disabled={apply.isPending || blocked}
            title={blocked ? (change.blocked_reason ?? "") : undefined}
            onClick={() =>
              apply.mutate(
                { id: change.id, quotedAmount: amount === "" ? null : amount },
                { onSuccess: () => toast.success("Applied — the task has moved") },
              )
            }
          >
            <Check /> Confirm
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={reject.isPending}
            onClick={() =>
              reject.mutate(
                { id: change.id },
                { onSuccess: () => toast.success("Rejected — nothing changed") },
              )
            }
          >
            <X /> Reject
          </Button>
          <span className="text-xs text-muted-foreground">
            {PROPOSAL_STATUS_LABEL[change.status]} · {relativeTime(change.created_at)}
          </span>
        </div>

        {change.quoted_amount && (
          <p className="text-xs text-muted-foreground">
            Parsed figure: {money(change.quoted_amount)}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
