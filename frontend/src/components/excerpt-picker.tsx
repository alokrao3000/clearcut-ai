"use client";

import * as React from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useAddExcerpt, useScenes, useScripts } from "@/hooks/use-clearcut";

/**
 * Picking an excerpt is a deliberate act of disclosure, so the flow makes the selection
 * explicit: choose a scene, then highlight the passage. Selecting nothing shares the whole
 * scene, which the dialog says out loud rather than leaving to be discovered.
 */
export function ExcerptPicker({
  projectId,
  packetId,
  open,
  onOpenChange,
}: {
  projectId: string;
  packetId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: scripts, isLoading: loadingScripts } = useScripts(projectId, open);
  const [scriptId, setScriptId] = React.useState<string | null>(null);
  const [sceneId, setSceneId] = React.useState<string | null>(null);
  // The scene id travels with the highlight, so switching scenes discards it during
  // render rather than in an effect that would briefly show a stale selection.
  const [selection, setSelection] = React.useState<
    { sceneId: string; start: number; end: number } | null
  >(null);
  const add = useAddExcerpt(projectId);
  const textRef = React.useRef<HTMLTextAreaElement>(null);

  const effectiveScriptId = scriptId ?? scripts?.[0]?.id ?? null;
  const { data: scenes, isLoading: loadingScenes } = useScenes(effectiveScriptId);
  const scene = scenes?.find((s) => s.id === sceneId) ?? scenes?.[0] ?? null;

  const range = selection && selection.sceneId === scene?.id ? selection : null;

  const captureSelection = () => {
    const el = textRef.current;
    if (!el) return;
    const { selectionStart, selectionEnd } = el;
    setSelection(
      scene && selectionEnd > selectionStart
        ? { sceneId: scene.id, start: selectionStart, end: selectionEnd }
        : null,
    );
  };

  const submit = () => {
    if (!scene) return;
    add.mutate(
      {
        packetId,
        body: { scene_id: scene.id, ...(range ? { start: range.start, end: range.end } : {}) },
      },
      {
        onSuccess: () => {
          toast.success("Excerpt shared");
          onOpenChange(false);
          setSelection(null);
        },
      },
    );
  };

  const selectedLength = range ? range.end - range.start : (scene?.text.length ?? 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Share a script excerpt</DialogTitle>
          <DialogDescription>
            Highlight the passage to share. It is frozen at this moment and rendered as a
            watermarked image, so later edits to the scene cannot widen what a link already
            discloses.
          </DialogDescription>
        </DialogHeader>

        {loadingScripts ? (
          <Skeleton className="h-64 w-full" />
        ) : !scripts || scripts.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No scripts uploaded to this project yet.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="script">Script</Label>
                <Select
                  value={effectiveScriptId ?? undefined}
                  onValueChange={(id) => {
                    setScriptId(id);
                    setSceneId(null);
                  }}
                >
                  <SelectTrigger id="script">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {scripts.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.filename}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="scene">Scene</Label>
                <Select
                  value={scene?.id ?? undefined}
                  disabled={loadingScenes || !scenes?.length}
                  onValueChange={setSceneId}
                >
                  <SelectTrigger id="scene">
                    <SelectValue placeholder="Choose a scene" />
                  </SelectTrigger>
                  <SelectContent>
                    {(scenes ?? []).map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.index + 1}. {s.heading}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {loadingScenes ? (
              <Skeleton className="h-56 w-full" />
            ) : scene ? (
              <div className="flex flex-col gap-2">
                <Label htmlFor="scene-text">Scene text</Label>
                <textarea
                  id="scene-text"
                  ref={textRef}
                  readOnly
                  value={scene.text}
                  onMouseUp={captureSelection}
                  onKeyUp={captureSelection}
                  className="h-56 w-full resize-none rounded-md border border-border bg-muted/30 p-3 font-mono text-xs leading-relaxed outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
                <p className="text-xs text-muted-foreground">
                  {range
                    ? `Sharing the highlighted ${selectedLength} characters.`
                    : `Nothing highlighted — the whole scene (${selectedLength} characters) will be shared.`}
                </p>
              </div>
            ) : null}
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button disabled={!scene || add.isPending} onClick={submit}>
            Share excerpt
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
