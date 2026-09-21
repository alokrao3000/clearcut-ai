"use client";

import * as React from "react";
import { Link2, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useIngest } from "@/hooks/use-clearcut";

const MAX_ITEMS = 50;

/**
 * Batch URL ingest. The notes and planned usage apply to every URL in the paste,
 * which matches how a producer works: one scene, several candidate clips.
 */
export function IngestBox({ projectId }: { projectId: string }) {
  const ingest = useIngest(projectId);
  const [urls, setUrls] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [seconds, setSeconds] = React.useState("");

  const parsed = React.useMemo(
    () =>
      urls
        .split(/[\n,\s]+/)
        .map((u) => u.trim())
        .filter((u) => /^https?:\/\//i.test(u)),
    [urls],
  );

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (parsed.length === 0) {
      toast.error("Paste at least one http(s) URL");
      return;
    }
    if (parsed.length > MAX_ITEMS) {
      toast.error(`The API takes ${MAX_ITEMS} URLs per batch`, {
        description: `You pasted ${parsed.length}. Split the list.`,
      });
      return;
    }

    const usage = seconds.trim() ? Number(seconds) : null;
    if (usage !== null && (!Number.isFinite(usage) || usage < 1)) {
      toast.error("Planned usage must be a whole number of seconds");
      return;
    }

    ingest.mutate(
      parsed.map((url) => ({
        url,
        notes: notes.trim() || null,
        usage_seconds: usage === null ? null : Math.round(usage),
      })),
      {
        onSuccess: (results) => {
          setUrls("");
          const fresh = results.filter((r) => !r.duplicate);
          const dupes = results.length - fresh.length;
          const partial = fresh.filter((r) => r.status !== "complete");

          toast.success(
            `${fresh.length} asset${fresh.length === 1 ? "" : "s"} ingested` +
              (dupes ? `, ${dupes} already in the project` : ""),
            partial.length
              ? {
                  description: `${partial.length} came back without full metadata — fill the fields in by hand.`,
                }
              : undefined,
          );
        },
      },
    );
  };

  return (
    <Card>
      <CardContent className="p-5">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="grid gap-2">
            <Label htmlFor="ingest-urls" className="flex items-center gap-2">
              <Link2 className="size-4" /> Add source URLs
            </Label>
            <Textarea
              id="ingest-urls"
              value={urls}
              onChange={(e) => setUrls(e.target.value)}
              placeholder={"https://www.youtube.com/watch?v=…\nhttps://vimeo.com/…\nhttps://archive.org/details/…"}
              className="min-h-24 font-mono text-xs"
            />
            <p className="text-xs text-muted-foreground">
              One per line. YouTube, Vimeo and Internet Archive resolve through their official
              endpoints; anything else is created from the URL for manual entry.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
            <div className="grid gap-2">
              <Label htmlFor="ingest-notes">How it is used</Label>
              <Input
                id="ingest-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="jukebox in the diner scene"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ingest-seconds">Planned usage (seconds)</Label>
              <Input
                id="ingest-seconds"
                inputMode="numeric"
                value={seconds}
                onChange={(e) => setSeconds(e.target.value)}
                placeholder="40"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Button type="submit" disabled={ingest.isPending}>
              {ingest.isPending && <Loader2 className="animate-spin" />}
              {ingest.isPending
                ? "Fetching metadata…"
                : `Ingest${parsed.length ? ` ${parsed.length} URL${parsed.length === 1 ? "" : "s"}` : ""}`}
            </Button>
            <span className="text-xs text-muted-foreground">
              Each asset is split into its rights layers automatically.
            </span>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
