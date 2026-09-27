"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { AlertTriangle, FileText, Mail, Plus } from "lucide-react";
import { toast } from "sonner";

import { PacketDrawer } from "@/components/packet-drawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreatePacket,
  usePacketGroups,
  usePackets,
  usePdfStatus,
} from "@/hooks/use-clearcut";
import { absoluteTime, relativeTime } from "@/lib/format";
import { KIND_LABEL, LAYER_LABEL, TEMPLATE_LABEL } from "@/lib/labels";
import type { PacketGroup } from "@/lib/types";

export default function OutreachPage() {
  const { id } = useParams<{ id: string }>();
  const { data: groups, isLoading } = usePacketGroups(id);
  const { data: packets } = usePackets(id);
  const { data: pdf } = usePdfStatus();
  const createPacket = useCreatePacket(id);
  const [openPacketId, setOpenPacketId] = React.useState<string | null>(null);

  const build = (group: PacketGroup) =>
    createPacket.mutate(
      { task_ids: group.task_ids, template: group.suggested_template },
      {
        onSuccess: (packet) => {
          setOpenPacketId(packet.id);
          toast.success(`Draft letter to ${packet.rightsholder.name}`);
        },
      },
    );

  if (isLoading) return <Skeleton className="h-96 w-full" />;

  const ungrouped = (groups ?? []).length === 0;

  return (
    <div className="flex flex-col gap-6">
      {pdf && !pdf.available && (
        <Card className="border-amber-300/60 bg-amber-50/50 dark:border-amber-900/60 dark:bg-amber-950/20">
          <CardContent className="flex gap-3 p-4 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-700 dark:text-amber-300" />
            <div>
              <p className="font-medium">PDF export is unavailable on this machine.</p>
              <p className="mt-1 text-muted-foreground">{pdf.install_hint}</p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---------------------------------------------------------- to build */}
      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-sm font-semibold">Ready to approach</h2>
          <p className="text-xs text-muted-foreground">
            Tasks are bundled by the licensing desk that receives the letter, which may be a
            parent of the rightsholder on the task.
          </p>
        </div>

        {ungrouped ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              Nothing is ready for outreach yet. Assign a rightsholder and approve the budget
              on a task, and its desk will appear here.
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {groups!.map((group) => (
              <Card key={group.rightsholder_id}>
                <CardContent className="flex flex-col gap-3 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{group.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {KIND_LABEL[group.kind]} ·{" "}
                        {group.licensing_email ?? (
                          <span className="text-amber-700 dark:text-amber-400">
                            no licensing contact on file
                          </span>
                        )}
                      </p>
                    </div>
                    <Badge variant="secondary">
                      {group.task_ids.length} task{group.task_ids.length === 1 ? "" : "s"}
                    </Badge>
                  </div>

                  <div className="flex flex-wrap gap-1">
                    {group.layers.map((layer) => (
                      <Badge key={layer} variant="outline" className="text-[11px]">
                        {LAYER_LABEL[layer]}
                      </Badge>
                    ))}
                    {group.is_placeholder && (
                      <Badge variant="muted" className="text-[11px]">
                        Unverified contact
                      </Badge>
                    )}
                  </div>

                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {group.asset_titles.join(" · ") || "Untitled material"}
                  </p>

                  <div className="flex items-center gap-2">
                    <Button size="sm" disabled={createPacket.isPending} onClick={() => build(group)}>
                      <Plus /> Draft letter
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {TEMPLATE_LABEL[group.suggested_template] ?? group.suggested_template}
                    </span>
                    {group.existing_packet_ids.length > 0 && (
                      <Badge variant="muted" className="text-[11px]">
                        {group.existing_packet_ids.length} already drafted
                      </Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------ packets */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Packets</h2>

        {!packets || packets.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center text-sm text-muted-foreground">
              No packets yet.
            </CardContent>
          </Card>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Recipient</th>
                  <th className="px-3 py-2 text-left font-medium">Template</th>
                  <th className="px-3 py-2 text-right font-medium">Items</th>
                  <th className="px-3 py-2 text-right font-medium">Links</th>
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {packets.map((packet) => {
                  const live = packet.context_views.filter((v) => v.status === "active").length;
                  return (
                    <tr
                      key={packet.id}
                      onClick={() => setOpenPacketId(packet.id)}
                      className="cursor-pointer hover:bg-accent/50"
                    >
                      <td className="px-3 py-2">
                        <span className="font-medium">{packet.rightsholder.name}</span>
                        <span className="block text-xs text-muted-foreground">
                          {packet.recipient_email ?? "No address"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {TEMPLATE_LABEL[packet.template] ?? packet.template}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {packet.items.length}
                        {packet.excerpts.length > 0 && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            +{packet.excerpts.length} excerpt
                            {packet.excerpts.length === 1 ? "" : "s"}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {live > 0 ? (
                          <span className="inline-flex items-center gap-1">
                            <Mail className="size-3.5 text-muted-foreground" /> {live}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {/* Finalizing only freezes the letter. Delivery is a separate call
                            that can be refused or fail, so "Sent" must not be inferred from
                            the packet's own status in a clearance-record product. */}
                        {packet.status !== "finalized" ? (
                          <Badge variant="outline">Draft</Badge>
                        ) : packet.sent_at ? (
                          <Badge variant="secondary" title={absoluteTime(packet.sent_at)}>
                            <Mail className="mr-1 size-3" /> Sent {relativeTime(packet.sent_at)}
                          </Badge>
                        ) : (
                          <Badge
                            variant="muted"
                            title={absoluteTime(packet.finalized_at ?? packet.updated_at)}
                          >
                            <FileText className="mr-1 size-3" /> Ready to send
                          </Badge>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <PacketDrawer
        projectId={id}
        packetId={openPacketId}
        onOpenChange={(open) => !open && setOpenPacketId(null)}
      />
    </div>
  );
}
