"use client";

import * as React from "react";
import { Check, Loader2, Search, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { useRightsholderSearch } from "@/hooks/use-clearcut";
import { KIND_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import type { Layer, RightsholderBrief } from "@/lib/types";

/**
 * Directory search, filtered to the kinds of entity that can plausibly own this layer
 * (the backend applies LAYER_KINDS when `layer` is passed).
 */
export function RightsholderPicker({
  layer,
  current,
  disabled,
  disabledReason,
  onSelect,
  onClear,
  pending,
}: {
  layer: Layer;
  current: RightsholderBrief | null;
  disabled?: boolean;
  disabledReason?: string;
  onSelect: (id: string) => void;
  onClear: () => void;
  pending?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [q, setQ] = React.useState("");
  const [debounced, setDebounced] = React.useState("");

  React.useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 200);
    return () => clearTimeout(t);
  }, [q]);

  const { data: results, isFetching } = useRightsholderSearch(
    debounced,
    layer,
    undefined,
    open,
  );

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            disabled={disabled || pending}
            title={disabled ? disabledReason : undefined}
            className="max-w-full justify-start gap-2"
          >
            {pending ? <Loader2 className="animate-spin" /> : <Search />}
            <span className="truncate">
              {current ? current.name : "Assign a rightsholder"}
            </span>
          </Button>
        </PopoverTrigger>

        <PopoverContent className="w-80 p-0" align="start">
          <div className="border-b border-border p-2">
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search the directory…"
              autoFocus
              className="h-8"
            />
          </div>

          <div className="max-h-72 overflow-y-auto p-1">
            {isFetching && (
              <p className="px-2 py-3 text-xs text-muted-foreground">Searching…</p>
            )}
            {!isFetching && results?.length === 0 && (
              <p className="px-2 py-3 text-xs text-muted-foreground">
                Nothing matches. Entities are added through the directory API for now.
              </p>
            )}
            {results?.map((rh) => (
              <button
                key={rh.id}
                type="button"
                onClick={() => {
                  onSelect(rh.id);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-start gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent",
                  current?.id === rh.id && "bg-accent",
                )}
              >
                <Check
                  className={cn(
                    "mt-0.5 size-4 shrink-0",
                    current?.id === rh.id ? "opacity-100" : "opacity-0",
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{rh.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {KIND_LABEL[rh.kind]}
                    {rh.contact.licensing_email ? ` · ${rh.contact.licensing_email}` : ""}
                  </span>
                </span>
                {rh.is_placeholder && (
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    unverified
                  </Badge>
                )}
              </button>
            ))}
          </div>
        </PopoverContent>
      </Popover>

      {current && !disabled && (
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={onClear}
          disabled={pending}
        >
          <X /> Unassign
        </Button>
      )}
    </div>
  );
}
