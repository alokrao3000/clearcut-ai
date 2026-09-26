"use client";

import * as React from "react";
import {
  Check,
  Copy,
  Eye,
  FileDown,
  Link2,
  Lock,
  ScrollText,
  Send,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { ExcerptPicker } from "@/components/excerpt-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useCreateContextView,
  useDeleteExcerpt,
  useFinalizePacket,
  useOutreachTemplates,
  usePacket,
  usePdfStatus,
  useRevokeContextView,
  useUpdatePacket,
  useViewAccesses,
} from "@/hooks/use-clearcut";
import { api } from "@/lib/api";
import { absoluteTime, moneyRange, relativeTime } from "@/lib/format";
import {
  ACCESS_OUTCOME_LABEL,
  LAYER_LABEL,
  STAGE_LABEL,
  TEMPLATE_LABEL,
  VIEW_STATUS_BADGE,
} from "@/lib/labels";
import type { ContextViewCreated, Packet } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PacketDrawer({
  projectId,
  packetId,
  onOpenChange,
}: {
  projectId: string;
  packetId: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: packet, isLoading } = usePacket(packetId);

  return (
    <Sheet open={Boolean(packetId)} onOpenChange={onOpenChange}>
      <SheetContent className="sm:max-w-2xl">
        {isLoading || !packet ? (
          <Skeleton className="h-full w-full" />
        ) : (
          // Keyed on the packet: a different packet gets a fresh form rather than an
          // effect that resets the draft after the first render.
          <PacketBody key={packet.id} projectId={projectId} packet={packet} />
        )}
      </SheetContent>
    </Sheet>
  );
}

function PacketBody({ projectId, packet }: { projectId: string; packet: Packet }) {
  const { data: templates } = useOutreachTemplates();
  const { data: pdf } = usePdfStatus();
  const update = useUpdatePacket(projectId);
  const finalize = useFinalizePacket(projectId);
  const frozen = packet.status === "finalized";

  const [draft, setDraft] = React.useState({
    subject: packet.subject ?? "",
    recipient_name: packet.recipient_name ?? "",
    recipient_email: packet.recipient_email ?? "",
    intro_note: packet.intro_note ?? "",
  });
  const dirty =
    draft.subject !== (packet.subject ?? "") ||
    draft.recipient_name !== (packet.recipient_name ?? "") ||
    draft.recipient_email !== (packet.recipient_email ?? "") ||
    draft.intro_note !== (packet.intro_note ?? "");

  const save = () =>
    update.mutate(
      {
        packetId: packet.id,
        body: {
          subject: draft.subject || null,
          recipient_name: draft.recipient_name || null,
          recipient_email: draft.recipient_email || null,
          intro_note: draft.intro_note || null,
        },
      },
      { onSuccess: () => toast.success("Saved") },
    );

  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex flex-wrap items-center gap-2">
          {packet.rightsholder.name}
          {frozen ? (
            <Badge variant="secondary">
              <Lock className="mr-1 size-3" /> Finalized
            </Badge>
          ) : (
            <Badge variant="outline">Draft</Badge>
          )}
        </SheetTitle>
        <SheetDescription>
          {packet.contact.is_placeholder
            ? "This contact is unverified placeholder data — check it before sending anything."
            : `Addressed to ${packet.contact.licensing_email ?? "no address on file"}`}
        </SheetDescription>
      </SheetHeader>

      <div className="-mx-6 flex-1 overflow-y-auto px-6">
        <div className="flex flex-col gap-6 pb-6">
          {/* ------------------------------------------------------- letter */}
          <section className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="template">Template</Label>
              <Select
                value={packet.template}
                disabled={frozen}
                onValueChange={(template) =>
                  update.mutate({ packetId: packet.id, body: { template } })
                }
              >
                <SelectTrigger id="template">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(templates ?? []).map((t) => (
                    <SelectItem key={t.name} value={t.name}>
                      {TEMPLATE_LABEL[t.name] ?? t.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {templates?.find((t) => t.name === packet.template)?.description}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Attention of" id="recipient_name">
                <Input
                  id="recipient_name"
                  value={draft.recipient_name}
                  disabled={frozen}
                  placeholder="Licensing desk"
                  onChange={(e) => setDraft({ ...draft, recipient_name: e.target.value })}
                />
              </Field>
              <Field label="Email" id="recipient_email">
                <Input
                  id="recipient_email"
                  value={draft.recipient_email}
                  disabled={frozen}
                  onChange={(e) => setDraft({ ...draft, recipient_email: e.target.value })}
                />
              </Field>
            </div>

            <Field label="Subject" id="subject">
              <Input
                id="subject"
                value={draft.subject}
                disabled={frozen}
                onChange={(e) => setDraft({ ...draft, subject: e.target.value })}
              />
            </Field>

            <Field label="Additional note" id="intro_note">
              <Textarea
                id="intro_note"
                rows={3}
                value={draft.intro_note}
                disabled={frozen}
                placeholder="Anything specific to this request — a deadline, a budget constraint, a prior conversation."
                onChange={(e) => setDraft({ ...draft, intro_note: e.target.value })}
              />
            </Field>

            {dirty && !frozen && (
              <div className="flex gap-2">
                <Button size="sm" disabled={update.isPending} onClick={save}>
                  <Check /> Save changes
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setDraft({
                      subject: packet.subject ?? "",
                      recipient_name: packet.recipient_name ?? "",
                      recipient_email: packet.recipient_email ?? "",
                      intro_note: packet.intro_note ?? "",
                    })
                  }
                >
                  Discard
                </Button>
              </div>
            )}
          </section>

          <Separator />

          {/* -------------------------------------------------------- items */}
          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold">Material requested</h3>
            <div className="rounded-lg border border-border">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-border">
                  {packet.items.map((item) => (
                    <tr key={item.task_id}>
                      <td className="px-3 py-2">
                        <span className="line-clamp-1">{item.asset_title ?? "Untitled"}</span>
                        <span className="text-xs text-muted-foreground">
                          {LAYER_LABEL[item.layer]} · {STAGE_LABEL[item.stage]}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right text-xs tabular-nums text-muted-foreground">
                        {moneyRange(item.estimate_low, item.estimate_high)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted-foreground">
              Estimates are shown here only. They are deliberately left out of the letter —
              quoting your own range to a licensing desk anchors the negotiation against you.
            </p>
          </section>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={api.packetPreviewUrl(packet.id, true)} target="_blank" rel="noreferrer">
                <Eye /> Preview letter
              </a>
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!pdf?.available}
              title={pdf?.available ? undefined : (pdf?.install_hint ?? "")}
              asChild={pdf?.available}
            >
              {pdf?.available ? (
                <a href={api.packetPdfUrl(packet.id)} target="_blank" rel="noreferrer">
                  <FileDown /> Download PDF
                </a>
              ) : (
                <span>
                  <FileDown /> PDF unavailable
                </span>
              )}
            </Button>
            {!frozen && (
              <Button
                size="sm"
                disabled={finalize.isPending || packet.items.length === 0}
                onClick={() =>
                  finalize.mutate(
                    { packetId: packet.id, transitionTasks: true },
                    {
                      onSuccess: () =>
                        toast.success("Letter frozen; tasks moved to outreach sent"),
                    },
                  )
                }
              >
                <Send /> Finalize &amp; mark sent
              </Button>
            )}
          </div>

          <Separator />

          <ExcerptSection projectId={projectId} packet={packet} />

          <Separator />

          <ContextViewSection projectId={projectId} packet={packet} />
        </div>
      </div>
    </>
  );
}

function Field({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

// ------------------------------------------------------------------ excerpts

function ExcerptSection({ projectId, packet }: { projectId: string; packet: Packet }) {
  const remove = useDeleteExcerpt(projectId);
  const [picking, setPicking] = React.useState(false);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Script context</h3>
          <p className="text-xs text-muted-foreground">
            The screenplay is never shared. Only passages you pick here appear in a context
            link, and only as watermarked images.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setPicking(true)}>
          <ScrollText /> Add excerpt
        </Button>
      </div>

      {packet.excerpts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No excerpts shared.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {packet.excerpts.map((excerpt) => (
            <li
              key={excerpt.id}
              className="flex items-start gap-3 rounded-lg border border-border p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-muted-foreground">{excerpt.label}</p>
                <p className="mt-1 line-clamp-3 font-mono text-xs leading-relaxed">
                  {excerpt.text}
                </p>
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="text-muted-foreground"
                onClick={() =>
                  remove.mutate(
                    { excerptId: excerpt.id, packetId: packet.id },
                    { onSuccess: () => toast.success("Excerpt withdrawn") },
                  )
                }
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <ExcerptPicker
        projectId={projectId}
        packetId={packet.id}
        open={picking}
        onOpenChange={setPicking}
      />
    </section>
  );
}

// ------------------------------------------------------------- context views

function ContextViewSection({ projectId, packet }: { projectId: string; packet: Packet }) {
  const create = useCreateContextView(projectId);
  const revoke = useRevokeContextView(projectId);
  const [recipient, setRecipient] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [issued, setIssued] = React.useState<ContextViewCreated | null>(null);
  const [openLog, setOpenLog] = React.useState<string | null>(null);

  const issue = () => {
    if (!recipient.trim()) {
      toast.error("Name the recipient — the link is watermarked with it");
      return;
    }
    create.mutate(
      {
        packetId: packet.id,
        body: { recipient_name: recipient.trim(), recipient_email: email.trim() || null },
      },
      {
        onSuccess: (view) => {
          setIssued(view);
          setRecipient("");
          setEmail("");
        },
      },
    );
  };

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold">Secure context links</h3>
        <p className="text-xs text-muted-foreground">
          Each link is specific to one recipient, expires in 14 days, and is logged on every
          open. The URL is shown once — it is stored only as a hash.
        </p>
      </div>

      {issued && (
        <div className="flex flex-col gap-2 rounded-lg border border-amber-300/70 bg-amber-50/60 p-3 dark:border-amber-900/70 dark:bg-amber-950/20">
          <p className="text-xs font-medium">
            Copy this now — it cannot be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 font-mono text-xs">
              {issued.url}
            </code>
            <Button
              size="sm"
              variant="outline"
              onClick={async () => {
                await navigator.clipboard.writeText(issued.url);
                toast.success("Link copied");
              }}
            >
              <Copy /> Copy
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setIssued(null)}>
              <X />
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div className="flex min-w-40 flex-1 flex-col gap-1.5">
          <Label htmlFor="cv-name">Recipient</Label>
          <Input
            id="cv-name"
            value={recipient}
            placeholder="Jane Doe"
            onChange={(e) => setRecipient(e.target.value)}
          />
        </div>
        <div className="flex min-w-40 flex-1 flex-col gap-1.5">
          <Label htmlFor="cv-email">Email (optional)</Label>
          <Input
            id="cv-email"
            value={email}
            placeholder="jane@example.com"
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <Button size="sm" disabled={create.isPending} onClick={issue}>
          <Link2 /> Issue link
        </Button>
      </div>

      {packet.context_views.length > 0 && (
        <ul className="flex flex-col gap-2">
          {packet.context_views.map((view) => (
            <li key={view.id} className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {view.recipient_name}
                    {view.recipient_email && (
                      <span className="ml-1 font-normal text-muted-foreground">
                        {view.recipient_email}
                      </span>
                    )}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    <code className="font-mono">{view.token_hint}…</code> · opened{" "}
                    {view.access_count}×
                    {view.last_accessed_at
                      ? `, last ${relativeTime(view.last_accessed_at)}`
                      : ""}{" "}
                    · expires {absoluteTime(view.expires_at)}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge className={cn("border-transparent", VIEW_STATUS_BADGE[view.status])}>
                    {view.status}
                  </Badge>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => setOpenLog(openLog === view.id ? null : view.id)}
                  >
                    Log
                  </Button>
                  {view.status === "active" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      onClick={() =>
                        revoke.mutate(
                          { viewId: view.id, packetId: packet.id },
                          { onSuccess: () => toast.success("Link revoked") },
                        )
                      }
                    >
                      Revoke
                    </Button>
                  )}
                </div>
              </div>
              {openLog === view.id && <AccessLog viewId={view.id} />}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AccessLog({ viewId }: { viewId: string }) {
  const { data, isLoading } = useViewAccesses(viewId);

  if (isLoading) return <Skeleton className="mt-3 h-20 w-full" />;
  if (!data || data.length === 0) {
    return <p className="mt-3 text-xs text-muted-foreground">Never opened.</p>;
  }

  return (
    <ul className="mt-3 flex flex-col gap-1 border-t border-border pt-3">
      {data.map((row) => (
        <li key={row.id} className="flex items-baseline gap-2 text-xs">
          <span
            className={cn(
              "shrink-0 font-medium",
              row.outcome === "ok" ? "text-foreground" : "text-rose-700 dark:text-rose-400",
            )}
          >
            {ACCESS_OUTCOME_LABEL[row.outcome] ?? row.outcome}
          </span>
          <span className="text-muted-foreground">{absoluteTime(row.at)}</span>
          {row.client_ip && <span className="text-muted-foreground">{row.client_ip}</span>}
          <span className="truncate text-muted-foreground">{row.user_agent}</span>
        </li>
      ))}
    </ul>
  );
}
