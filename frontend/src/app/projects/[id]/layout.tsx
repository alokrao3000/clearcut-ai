"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname, useParams } from "next/navigation";
import { ChevronLeft, Settings2 } from "lucide-react";

import { EditProjectDialog } from "@/components/project-form";
import { BudgetStrip } from "@/components/budget-strip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useProject } from "@/hooks/use-clearcut";
import { SCOPE_LABEL, TIER_LABEL } from "@/lib/labels";
import { cn } from "@/lib/utils";

const TABS = [
  { slug: "", label: "Assets" },
  { slug: "tasks", label: "Tasks" },
  { slug: "board", label: "Board" },
  { slug: "budget", label: "Budget" },
  { slug: "outreach", label: "Outreach" },
  { slug: "replies", label: "Replies" },
  { slug: "ledger", label: "Ledger" },
] as const;

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { data: project, isLoading, isError } = useProject(id);
  const [editing, setEditing] = React.useState(false);

  const base = `/projects/${id}`;
  const active = pathname === base ? "" : pathname.slice(base.length + 1).split("/")[0];

  if (isError) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-sm text-muted-foreground">This project could not be loaded.</p>
        <Button asChild variant="outline">
          <Link href="/">
            <ChevronLeft /> All projects
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        <Link
          href="/"
          className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" /> All projects
        </Link>

        <div className="flex flex-wrap items-center gap-3">
          {isLoading || !project ? (
            <Skeleton className="h-8 w-56" />
          ) : (
            <>
              <h1 className="text-2xl font-semibold tracking-tight">{project.name}</h1>
              <Badge variant="secondary">{SCOPE_LABEL[project.distribution_scope]}</Badge>
              <Badge variant="outline">{TIER_LABEL[project.production_tier]}</Badge>
              <Button
                variant="ghost"
                size="sm"
                className="text-muted-foreground"
                onClick={() => setEditing(true)}
              >
                <Settings2 /> Scope
              </Button>
            </>
          )}
        </div>
      </div>

      <BudgetStrip projectId={id} />

      <nav className="flex gap-1 border-b border-border">
        {TABS.map((tab) => {
          const href = tab.slug ? `${base}/${tab.slug}` : base;
          const isActive = active === tab.slug;
          return (
            <Link
              key={tab.slug || "assets"}
              href={href}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      {children}

      {project && (
        <EditProjectDialog project={project} open={editing} onOpenChange={setEditing} />
      )}
    </div>
  );
}
