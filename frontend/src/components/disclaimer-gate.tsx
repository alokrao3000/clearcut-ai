"use client";

import { ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAcceptDisclaimer, useDisclaimer } from "@/hooks/use-clearcut";

/**
 * Mirrors the server-side gate: every mutating endpoint returns 428 until the
 * current user has accepted the current disclaimer version. The dialog cannot be
 * dismissed, because dismissing it would leave every write failing.
 */
export function DisclaimerGate() {
  const { data, isLoading, isError } = useDisclaimer();
  const accept = useAcceptDisclaimer();

  const open = !isLoading && !isError && data?.accepted === false;

  return (
    <Dialog open={open}>
      <DialogContent
        hideClose
        className="max-w-xl"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <div className="mb-1 flex size-10 items-center justify-center rounded-full bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            <ShieldAlert className="size-5" />
          </div>
          <DialogTitle>Before you continue</DialogTitle>
          <DialogDescription>
            Version {data?.version} · required before any change can be saved
          </DialogDescription>
        </DialogHeader>

        <p className="text-sm leading-relaxed text-foreground/90">{data?.text}</p>

        <DialogFooter>
          <Button
            onClick={() => accept.mutate()}
            disabled={accept.isPending}
            className="w-full sm:w-auto"
          >
            {accept.isPending ? "Recording…" : "I understand"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
