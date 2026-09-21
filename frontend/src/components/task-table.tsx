"use client";

import * as React from "react";
import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_equalsString,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_text,
  tableFeatures,
  useTable,
  type ColumnFiltersState,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import { StageBadge } from "@/components/stage-badge";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { money, moneyRange, relativeTime } from "@/lib/format";
import { LAYER_LABEL, STAGE_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";
import { STAGES, type Asset, type Stage, type Task } from "@/lib/types";

export interface TaskRow {
  task: Task;
  assetId: string;
  assetTitle: string;
  platform: string;
}

/** One row per clearance task, with its asset's identity flattened in for sorting. */
export function rowsFromAssets(assets: Asset[] | undefined): TaskRow[] {
  return (assets ?? []).flatMap((asset) =>
    asset.tasks.map((task) => ({
      task,
      assetId: asset.id,
      assetTitle: asset.title ?? asset.raw_source,
      platform: asset.platform,
    })),
  );
}

// v9 registers behaviour explicitly: no feature, no state and no API for it.
const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text },
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString, equalsString: filterFn_equalsString },
});

const helper = createColumnHelper<typeof features, TaskRow>();
const numeric = (value: string | null) => (value === null ? 0 : Number(value));

const columns = helper.columns([
  helper.accessor((row) => row.assetTitle, {
    id: "asset",
    header: "Asset",
    cell: ({ row }) => (
      <div className="min-w-0">
        <div className="truncate font-medium">{row.original.assetTitle}</div>
        <div className="text-xs text-muted-foreground">
          {row.original.platform.replace(/_/g, " ")}
        </div>
      </div>
    ),
  }),
  helper.accessor((row) => LAYER_LABEL[row.task.layer], {
    id: "layer",
    header: "Layer",
    cell: ({ getValue }) => <Badge variant="secondary">{getValue()}</Badge>,
  }),
  helper.accessor((row) => row.task.stage, {
    id: "stage",
    header: "Stage",
    filterFn: "equalsString",
    cell: ({ row }) => <StageBadge stage={row.original.task.stage} />,
  }),
  helper.accessor((row) => row.task.rightsholder?.name ?? "", {
    id: "rightsholder",
    header: "Rightsholder",
    cell: ({ row }) => {
      const { rightsholder, mapping_method, mapping_confidence, mapping_candidates } =
        row.original.task;
      if (!rightsholder) {
        return (
          <span className="text-sm text-muted-foreground">
            {mapping_candidates.length > 0
              ? `${mapping_candidates.length} candidate${mapping_candidates.length === 1 ? "" : "s"}`
              : "Unassigned"}
          </span>
        );
      }
      return (
        <div className="min-w-0">
          <div className="truncate text-sm">{rightsholder.name}</div>
          <div className="text-xs text-muted-foreground">
            {mapping_method === "manual"
              ? "manual"
              : `${mapping_method ?? "auto"}${
                  mapping_confidence !== null ? ` · ${Math.round(mapping_confidence)}` : ""
                }`}
          </div>
        </div>
      );
    },
  }),
  helper.accessor((row) => numeric(row.task.estimate_high), {
    id: "estimate",
    header: "Estimate",
    cell: ({ row }) => (
      <span className="tabular-nums">
        {moneyRange(row.original.task.estimate_low, row.original.task.estimate_high)}
      </span>
    ),
  }),
  helper.accessor((row) => numeric(row.task.quoted_amount), {
    id: "quoted",
    header: "Quoted",
    cell: ({ row }) => (
      <span className="tabular-nums">{money(row.original.task.quoted_amount)}</span>
    ),
  }),
  helper.accessor((row) => numeric(row.task.agreed_amount), {
    id: "agreed",
    header: "Agreed",
    cell: ({ row }) => (
      <span className="tabular-nums">{money(row.original.task.agreed_amount)}</span>
    ),
  }),
  helper.accessor((row) => row.task.updated_at, {
    id: "updated",
    header: "Updated",
    cell: ({ getValue }) => (
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {relativeTime(getValue())}
      </span>
    ),
  }),
]);

export function TaskTable({
  rows,
  onOpenTask,
}: {
  rows: TaskRow[];
  onOpenTask: (row: TaskRow) => void;
}) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [stage, setStage] = React.useState<Stage | "all">("all");

  const columnFilters = React.useMemo<ColumnFiltersState>(
    () => (stage === "all" ? [] : [{ id: "stage", value: stage }]),
    [stage],
  );

  const table = useTable({
    features,
    data: rows,
    columns,
    state: { sorting, globalFilter, columnFilters },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    globalFilterFn: "includesString",
    getRowId: (row) => row.task.id,
  });

  const visible = table.getRowModel().rows;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
          placeholder="Filter by asset, layer or rightsholder…"
          className="h-9 max-w-sm"
        />
        <Select value={stage} onValueChange={(v) => setStage(v as Stage | "all")}>
          <SelectTrigger className="h-9 w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All stages</SelectItem>
            {STAGES.map((s) => (
              <SelectItem key={s} value={s}>
                {STAGE_LABEL[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {visible.length} of {rows.length} tasks
        </span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="bg-muted/60">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className="px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"
                    >
                      {header.isPlaceholder ? null : (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            "inline-flex items-center gap-1",
                            header.column.getCanSort() && "hover:text-foreground",
                          )}
                        >
                          <table.FlexRender header={header} />
                          {sorted === "asc" ? (
                            <ArrowUp className="size-3" />
                          ) : sorted === "desc" ? (
                            <ArrowDown className="size-3" />
                          ) : (
                            <ChevronsUpDown className="size-3 opacity-40" />
                          )}
                        </button>
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-border">
            {visible.map((row) => (
              <tr
                key={row.id}
                onClick={() => onOpenTask(row.original)}
                className="cursor-pointer transition-colors hover:bg-accent/50"
              >
                {row.getAllCells().map((cell) => (
                  <td key={cell.id} className="max-w-64 px-3 py-2 align-middle">
                    <table.FlexRender cell={cell} />
                  </td>
                ))}
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-10 text-center text-sm text-muted-foreground"
                >
                  No tasks match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
