"use client";

import * as React from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { Film, GripVertical } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { useTransition } from "@/hooks/use-clearcut";
import { moneyRange } from "@/lib/format";
import {
  CLOSED_STAGES,
  LAYER_LABEL,
  PIPELINE_STAGES,
  STAGE_ACCENT,
  STAGE_LABEL,
} from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { Board, BoardCard as BoardCardType, Stage } from "@/lib/types";

function CardBody({ card, dragging }: { card: BoardCardType; dragging?: boolean }) {
  const { task } = card;
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-l-4 border-border bg-card p-3 shadow-sm",
        STAGE_ACCENT[task.stage],
        dragging && "rotate-1 shadow-lg",
      )}
    >
      <div className="flex items-start gap-2">
        {card.asset_thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={card.asset_thumbnail_url}
            alt=""
            className="h-10 w-16 shrink-0 rounded object-cover"
            loading="lazy"
          />
        ) : (
          <div className="flex h-10 w-16 shrink-0 items-center justify-center rounded bg-muted text-muted-foreground">
            <Film className="size-4" />
          </div>
        )}
        <p className="line-clamp-2 min-w-0 flex-1 text-sm font-medium">
          {card.asset_title ?? "Untitled asset"}
        </p>
        <GripVertical className="size-4 shrink-0 text-muted-foreground" />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="secondary" className="text-[10px]">
          {LAYER_LABEL[task.layer]}
        </Badge>
        {task.rightsholder ? (
          <span className="min-w-0 truncate text-xs text-muted-foreground">
            {task.rightsholder.name}
          </span>
        ) : (
          <span className="text-xs text-amber-700 dark:text-amber-300">Unassigned</span>
        )}
      </div>

      <div className="flex items-center justify-between text-xs tabular-nums text-muted-foreground">
        <span>{moneyRange(task.estimate_low, task.estimate_high)}</span>
        {task.quoted_amount && <span>quoted</span>}
      </div>
    </div>
  );
}

function DraggableCard({
  card,
  onOpen,
}: {
  card: BoardCardType;
  onOpen: (card: BoardCardType) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: card.task.id,
    data: { card },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={() => onOpen(card)}
      // select-none: without it a drag highlights the card's text instead.
      className={cn("cursor-grab touch-none select-none", isDragging && "opacity-40")}
    >
      <CardBody card={card} />
    </div>
  );
}

function Column({
  stage,
  cards,
  activeAllowed,
  isDragging,
  onOpen,
}: {
  stage: Stage;
  cards: BoardCardType[];
  activeAllowed: boolean;
  isDragging: boolean;
  onOpen: (card: BoardCardType) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: stage });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex w-72 shrink-0 flex-col gap-2 rounded-xl border border-border bg-muted/40 p-2 transition-colors",
        isDragging && !activeAllowed && "opacity-40",
        isOver && activeAllowed && "border-foreground/40 bg-accent",
      )}
    >
      <div className="flex items-center justify-between px-1 py-1">
        <h3 className="text-sm font-semibold">{STAGE_LABEL[stage]}</h3>
        <Badge variant="muted">{cards.length}</Badge>
      </div>

      <div className="board-scroll flex max-h-[62vh] flex-col gap-2 overflow-y-auto pr-0.5">
        {cards.map((card) => (
          <DraggableCard key={card.task.id} card={card} onOpen={onOpen} />
        ))}
        {cards.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-muted-foreground">Empty</p>
        )}
      </div>
    </div>
  );
}

/** Drag a card to a column to request that transition; the server still enforces the rules. */
export function KanbanBoard({
  projectId,
  board,
  onOpenCard,
}: {
  projectId: string;
  board: Board;
  onOpenCard: (card: BoardCardType) => void;
}) {
  const move = useTransition(projectId);
  const [active, setActive] = React.useState<BoardCardType | null>(null);
  const sensors = useSensors(
    // A few pixels of travel keeps click-to-open working on the same card.
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 180, tolerance: 6 } }),
    // Space picks a card up, arrows move between columns, space drops it.
    useSensor(KeyboardSensor),
  );

  const columns: Stage[] = [...PIPELINE_STAGES, ...CLOSED_STAGES];

  const onDragStart = (event: DragStartEvent) => {
    setActive((event.active.data.current as { card: BoardCardType }).card);
  };

  const onDragEnd = (event: DragEndEvent) => {
    const card = active;
    setActive(null);
    if (!card || !event.over) return;

    const to = event.over.id as Stage;
    if (to === card.task.stage) return;

    if (!card.task.allowed_transitions.includes(to)) {
      toast.error(`Cannot move to ${STAGE_LABEL[to].toLowerCase()}`, {
        description: card.task.allowed_transitions.length
          ? `From ${STAGE_LABEL[card.task.stage].toLowerCase()} you can go to: ${card.task.allowed_transitions
              .map((s) => STAGE_LABEL[s].toLowerCase())
              .join(", ")}.`
          : "This task is closed.",
      });
      return;
    }

    move.mutate(
      { taskId: card.task.id, to },
      { onSuccess: () => toast.success(`Moved to ${STAGE_LABEL[to].toLowerCase()}`) },
    );
  };

  return (
    <DndContext
      sensors={sensors}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setActive(null)}
    >
      <div className="board-scroll flex gap-3 overflow-x-auto pb-3">
        {columns.map((stage) => (
          <Column
            key={stage}
            stage={stage}
            cards={board[stage] ?? []}
            isDragging={active !== null}
            activeAllowed={
              active === null ||
              stage === active.task.stage ||
              active.task.allowed_transitions.includes(stage)
            }
            onOpen={onOpenCard}
          />
        ))}
      </div>

      <DragOverlay dropAnimation={null}>
        {active && (
          <div className="w-72">
            <CardBody card={active} dragging />
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
