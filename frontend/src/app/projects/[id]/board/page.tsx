"use client";

import * as React from "react";
import { useParams } from "next/navigation";

import { KanbanBoard } from "@/components/kanban-board";
import { TaskDrawer } from "@/components/task-drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { useBoard } from "@/hooks/use-clearcut";

export default function BoardPage() {
  const { id } = useParams<{ id: string }>();
  const { data: board, isLoading } = useBoard(id);
  const [openTaskId, setOpenTaskId] = React.useState<string | null>(null);

  const cards = React.useMemo(
    () => (board ? Object.values(board).flat() : []),
    [board],
  );
  const openCard = cards.find((c) => c.task.id === openTaskId) ?? null;

  if (isLoading || !board) return <Skeleton className="h-[60vh] w-full" />;

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Drag a card to request a transition. Columns dim when the move is not allowed from
        where the task is now.
      </p>

      <KanbanBoard
        projectId={id}
        board={board}
        onOpenCard={(card) => setOpenTaskId(card.task.id)}
      />

      <TaskDrawer
        projectId={id}
        task={openCard?.task ?? null}
        assetTitle={openCard?.asset_title}
        onOpenChange={(open) => !open && setOpenTaskId(null)}
      />
    </div>
  );
}
