"use client";

import * as React from "react";
import { useParams } from "next/navigation";

import { AssetCard, AssetCardSkeleton } from "@/components/asset-card";
import { IngestBox } from "@/components/ingest-box";
import { TaskDrawer } from "@/components/task-drawer";
import { Card, CardContent } from "@/components/ui/card";
import { useAssets } from "@/hooks/use-clearcut";
import type { Task } from "@/lib/types";

export default function AssetsPage() {
  const { id } = useParams<{ id: string }>();
  const { data: assets, isLoading } = useAssets(id);
  const [openTaskId, setOpenTaskId] = React.useState<string | null>(null);

  // Look the task up on every render so the drawer shows server state, not a stale copy.
  const openTask =
    assets?.flatMap((a) => a.tasks).find((t) => t.id === openTaskId) ?? null;
  const openAsset = assets?.find((a) => a.id === openTask?.asset_id);

  return (
    <div className="flex flex-col gap-5">
      <IngestBox projectId={id} />

      {isLoading && (
        <div className="flex flex-col gap-4">
          <AssetCardSkeleton />
          <AssetCardSkeleton />
        </div>
      )}

      {assets?.length === 0 && (
        <Card>
          <CardContent className="p-10 text-center">
            <p className="font-medium">No assets yet</p>
            <p className="text-sm text-muted-foreground">
              Paste a YouTube, Vimeo or Internet Archive link above to create the first one.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-4">
        {assets?.map((asset) => (
          <AssetCard
            key={asset.id}
            projectId={id}
            asset={asset}
            onOpenTask={(task: Task) => setOpenTaskId(task.id)}
          />
        ))}
      </div>

      <TaskDrawer
        projectId={id}
        task={openTask}
        assetTitle={openAsset?.title ?? openAsset?.raw_source}
        onOpenChange={(open) => !open && setOpenTaskId(null)}
      />
    </div>
  );
}
