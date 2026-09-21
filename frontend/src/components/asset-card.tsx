"use client";

import * as React from "react";
import {
  AlertTriangle,
  ExternalLink,
  Film,
  Layers,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { StageBadge } from "@/components/stage-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  useAddLayer,
  useDeleteAsset,
  useRemapAsset,
  useUpdateAsset,
} from "@/hooks/use-clearcut";
import { duration, hostOf, moneyRange } from "@/lib/format";
import { LAYER_LABEL } from "@/lib/labels";
import { LAYERS, type Asset, type Layer, type Task } from "@/lib/types";

function IngestBadge({ asset }: { asset: Asset }) {
  if (asset.ingest_status === "complete") {
    return <Badge variant="outline">{asset.platform.replace(/_/g, " ")}</Badge>;
  }
  return (
    <Badge
      variant="muted"
      className="gap-1 bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      title={asset.ingest_error ?? undefined}
    >
      <AlertTriangle className="size-3" />
      {asset.ingest_status === "partial" ? "needs manual entry" : "ingest failed"}
    </Badge>
  );
}

function EditAssetDialog({
  projectId,
  asset,
  open,
  onOpenChange,
}: {
  projectId: string;
  asset: Asset;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts the content when closed, so the form re-seeds from the
          latest asset every time it is opened. */}
      <AssetForm projectId={projectId} asset={asset} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function AssetForm({
  projectId,
  asset,
  onDone,
}: {
  projectId: string;
  asset: Asset;
  onDone: () => void;
}) {
  const update = useUpdateAsset(projectId);
  const [title, setTitle] = React.useState(asset.title ?? "");
  const [owner, setOwner] = React.useState(asset.owner_name ?? "");
  const [published, setPublished] = React.useState(asset.published_at ?? "");
  const [keywords, setKeywords] = React.useState(asset.inferred_keywords.join(", "));
  const [notes, setNotes] = React.useState(asset.user_notes ?? "");
  const [seconds, setSeconds] = React.useState(
    asset.usage_seconds === null ? "" : String(asset.usage_seconds),
  );
  const [remap, setRemap] = React.useState(true);

  const submit = () => {
    const usage = seconds.trim() ? Number(seconds) : null;
    if (usage !== null && (!Number.isFinite(usage) || usage < 1)) {
      toast.error("Planned usage must be a whole number of seconds");
      return;
    }
    update.mutate(
      {
        assetId: asset.id,
        body: {
          title: title.trim() || null,
          owner_name: owner.trim() || null,
          published_at: published.trim() || null,
          inferred_keywords: keywords
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean),
          user_notes: notes.trim() || null,
          usage_seconds: usage === null ? null : Math.round(usage),
          remap,
        },
      },
      {
        onSuccess: () => {
          onDone();
          toast.success(remap ? "Saved and re-matched" : "Saved");
        },
      },
    );
  };

  return (
    <DialogContent className="max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>Correct asset metadata</DialogTitle>
        <DialogDescription>
          Edits never touch the frozen ingest snapshot — the original payload stays on record.
        </DialogDescription>
      </DialogHeader>

      <div className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="asset-title">Title</Label>
          <Input
            id="asset-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="asset-owner">Owner / channel</Label>
          <Input
            id="asset-owner"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            placeholder="Who posted or owns it"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="asset-published">Published</Label>
            <Input
              id="asset-published"
              value={published}
              onChange={(e) => setPublished(e.target.value)}
              placeholder="1998-04-12"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="asset-seconds">Planned usage (seconds)</Label>
            <Input
              id="asset-seconds"
              inputMode="numeric"
              value={seconds}
              onChange={(e) => setSeconds(e.target.value)}
            />
          </div>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="asset-keywords">Keywords</Label>
          <Input
            id="asset-keywords"
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="comma, separated"
          />
          <p className="text-xs text-muted-foreground">
            The matcher scores owner, title and keywords against the directory.
          </p>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="asset-notes">How it is used</Label>
          <Textarea
            id="asset-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={remap}
            onChange={(e) => setRemap(e.target.checked)}
            className="size-4 rounded border-input"
          />
          Re-run rights matching on auto-mapped layers
        </label>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function AssetCard({
  projectId,
  asset,
  onOpenTask,
}: {
  projectId: string;
  asset: Asset;
  onOpenTask: (task: Task) => void;
}) {
  const [editing, setEditing] = React.useState(false);
  const addLayer = useAddLayer(projectId);
  const remap = useRemapAsset(projectId);
  const remove = useDeleteAsset(projectId);

  const missingLayers = LAYERS.filter((l) => !asset.tasks.some((t) => t.layer === l));

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-4 p-4 sm:flex-row">
        <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-lg bg-muted sm:w-56">
          {asset.thumbnail_url ? (
            // Arbitrary third-party hosts: skip the image optimizer rather than
            // maintain an allowlist of every archive and platform domain.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={asset.thumbnail_url}
              alt=""
              className="size-full object-cover"
              loading="lazy"
            />
          ) : (
            <div className="flex size-full items-center justify-center text-muted-foreground">
              <Film className="size-6" />
            </div>
          )}
          {asset.duration_seconds !== null && (
            <span className="absolute bottom-1 right-1 rounded bg-black/75 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums">
              {duration(asset.duration_seconds)}
            </span>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <h3 className="truncate font-medium">
                {asset.title ?? "Untitled — add a title so matching can work"}
              </h3>
              <p className="truncate text-sm text-muted-foreground">
                {asset.owner_name ?? "Unknown owner"} · {hostOf(asset.raw_source)}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button variant="ghost" size="icon" asChild title="Open source">
                <a href={asset.raw_source} target="_blank" rel="noreferrer noopener">
                  <ExternalLink />
                </a>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title="Edit metadata"
                onClick={() => setEditing(true)}
              >
                <Pencil />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title="Re-run rights matching"
                disabled={remap.isPending}
                onClick={() =>
                  remap.mutate(asset.id, { onSuccess: () => toast.success("Re-matched") })
                }
              >
                <RefreshCw />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                title="Remove asset"
                className="hover:text-destructive"
                onClick={() => {
                  if (!window.confirm("Remove this asset and all of its clearance tasks?")) {
                    return;
                  }
                  remove.mutate(asset.id, {
                    onSuccess: () => toast.success("Asset removed"),
                  });
                }}
              >
                <Trash2 />
              </Button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            <IngestBadge asset={asset} />
            {asset.usage_seconds !== null && (
              <Badge variant="muted">{asset.usage_seconds}s planned</Badge>
            )}
            {asset.inferred_keywords.slice(0, 4).map((k) => (
              <Badge key={k} variant="muted" className="font-normal">
                {k}
              </Badge>
            ))}
          </div>

          {asset.user_notes && (
            <p className="text-sm italic text-muted-foreground">{asset.user_notes}</p>
          )}

          <div className="mt-1 flex flex-col divide-y divide-border rounded-lg border border-border">
            {asset.tasks.map((task) => (
              <button
                key={task.id}
                type="button"
                onClick={() => onOpenTask(task)}
                className="flex flex-wrap items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/60"
              >
                <Layers className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="w-40 shrink-0 font-medium">{LAYER_LABEL[task.layer]}</span>
                <StageBadge stage={task.stage} />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {task.rightsholder?.name ?? "Unassigned"}
                  {task.mapping_confidence !== null && task.mapping_method !== "manual"
                    ? ` · ${Math.round(task.mapping_confidence)}`
                    : ""}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {moneyRange(task.estimate_low, task.estimate_high)}
                </span>
              </button>
            ))}

            {missingLayers.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-2">
                <Select
                  value=""
                  onValueChange={(layer) =>
                    addLayer.mutate(
                      { assetId: asset.id, layer: layer as Layer },
                      {
                        onSuccess: () =>
                          toast.success(`Added ${LAYER_LABEL[layer as Layer].toLowerCase()}`),
                      },
                    )
                  }
                >
                  <SelectTrigger className="h-8 w-56 text-xs">
                    <SelectValue placeholder="Split out another right…" />
                  </SelectTrigger>
                  <SelectContent>
                    {missingLayers.map((layer) => (
                      <SelectItem key={layer} value={layer}>
                        {LAYER_LABEL[layer]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>
      </div>

      <EditAssetDialog
        projectId={projectId}
        asset={asset}
        open={editing}
        onOpenChange={setEditing}
      />
    </Card>
  );
}

export function AssetCardSkeleton() {
  return (
    <Card>
      <CardContent className="flex gap-4 p-4">
        <div className="aspect-video w-56 animate-pulse rounded-lg bg-muted" />
        <div className="flex flex-1 flex-col gap-3 py-1">
          <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
          <div className="h-3 w-1/3 animate-pulse rounded bg-muted" />
          <div className="h-16 w-full animate-pulse rounded bg-muted" />
        </div>
      </CardContent>
    </Card>
  );
}
