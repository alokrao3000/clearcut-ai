import { Badge } from "@/components/ui/badge";
import { STAGE_BADGE, STAGE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { Stage } from "@/lib/types";

export function StageBadge({ stage, className }: { stage: Stage; className?: string }) {
  return (
    <Badge variant="muted" className={cn(STAGE_BADGE[stage], className)}>
      {STAGE_LABEL[stage]}
    </Badge>
  );
}
