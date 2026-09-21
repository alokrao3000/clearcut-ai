"use client";

import Link from "next/link";
import { ArrowRight, FolderOpen, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { NewProjectDialog } from "@/components/project-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteProject, useProjects } from "@/hooks/use-clearcut";
import { relativeTime } from "@/lib/format";
import { SCOPE_LABEL, TIER_LABEL } from "@/lib/labels";

export default function ProjectsPage() {
  const { data: projects, isLoading, isError, error } = useProjects();
  const remove = useDeleteProject();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="text-sm text-muted-foreground">
            Each project carries its own release plan, asset list and clearance board.
          </p>
        </div>
        <NewProjectDialog />
      </div>

      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      )}

      {isError && (
        <Card className="border-destructive/40">
          <CardContent className="p-5 text-sm">
            <p className="font-medium text-destructive">Cannot reach the API.</p>
            <p className="mt-1 text-muted-foreground">
              {error instanceof Error ? error.message : "Unknown error"} — is the backend
              running on port 8000?
            </p>
          </CardContent>
        </Card>
      )}

      {projects?.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-12 text-center">
            <FolderOpen className="size-8 text-muted-foreground" />
            <div>
              <p className="font-medium">No projects yet</p>
              <p className="text-sm text-muted-foreground">
                Create one, then paste the URLs you are thinking of using.
              </p>
            </div>
            <NewProjectDialog />
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {projects?.map((project) => (
          <Card key={project.id} className="group relative transition-shadow hover:shadow-md">
            <CardHeader className="pb-3">
              <CardTitle className="pr-8 text-base">
                <Link href={`/projects/${project.id}`} className="after:absolute after:inset-0">
                  {project.name}
                </Link>
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                Created {relativeTime(project.created_at)}
              </p>
            </CardHeader>
            <CardContent className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{SCOPE_LABEL[project.distribution_scope]}</Badge>
              <Badge variant="outline">{TIER_LABEL[project.production_tier]}</Badge>
              <ArrowRight className="ml-auto size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </CardContent>

            <Button
              variant="ghost"
              size="icon"
              aria-label={`Delete ${project.name}`}
              className="absolute right-2 top-2 z-10 size-8 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100"
              onClick={(e) => {
                e.preventDefault();
                if (
                  !window.confirm(
                    `Delete "${project.name}"? Its assets, tasks and estimates go with it.`,
                  )
                ) {
                  return;
                }
                remove.mutate(project.id, {
                  onSuccess: () => toast.success(`Deleted "${project.name}"`),
                });
              }}
            >
              <Trash2 />
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}
