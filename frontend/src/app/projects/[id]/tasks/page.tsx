"use client";

import * as React from "react";
import { useParams } from "next/navigation";

import { TaskDrawer } from "@/components/task-drawer";
import { TaskTable, rowsFromAssets } from "@/components/task-table";
import { Skeleton } from "@/components/ui/skeleton";
import { useAssets } from "@/hooks/use-clearcut";

export default function TasksPage() {
  const { id } = useParams<{ id: string }>();
  const { data: assets, isLoading } = useAssets(id);
  const [openTaskId, setOpenTaskId] = React.useState<string | null>(null);

  const rows = React.useMemo(() => rowsFromAssets(assets), [assets]);
  const openRow = rows.find((r) => r.task.id === openTaskId) ?? null;

  if (isLoading) return <Skeleton className="h-96 w-full" />;

  return (
    <>
      <TaskTable rows={rows} onOpenTask={(row) => setOpenTaskId(row.task.id)} />
      <TaskDrawer
        projectId={id}
        task={openRow?.task ?? null}
        assetTitle={openRow?.assetTitle}
        onOpenChange={(open) => !open && setOpenTaskId(null)}
      />
    </>
  );
}
