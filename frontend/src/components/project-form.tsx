"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateProject, useUpdateProject } from "@/hooks/use-clearcut";
import { SCOPE_LABEL, TIER_LABEL } from "@/lib/labels";
import {
  DISTRIBUTION_SCOPES,
  PRODUCTION_TIERS,
  type DistributionScope,
  type ProductionTier,
  type Project,
} from "@/lib/types";

interface ScopeFieldsProps {
  name: string;
  scope: DistributionScope;
  tier: ProductionTier;
  onName: (v: string) => void;
  onScope: (v: DistributionScope) => void;
  onTier: (v: ProductionTier) => void;
}

function ScopeFields({ name, scope, tier, onName, onScope, onTier }: ScopeFieldsProps) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="project-name">Project name</Label>
        <Input
          id="project-name"
          value={name}
          onChange={(e) => onName(e.target.value)}
          placeholder="Untitled feature"
          autoFocus
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="project-scope">Distribution scope</Label>
        <Select value={scope} onValueChange={(v) => onScope(v as DistributionScope)}>
          <SelectTrigger id="project-scope">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DISTRIBUTION_SCOPES.map((s) => (
              <SelectItem key={s} value={s}>
                {SCOPE_LABEL[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="project-tier">Production tier</Label>
        <Select value={tier} onValueChange={(v) => onTier(v as ProductionTier)}>
          <SelectTrigger id="project-tier">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRODUCTION_TIERS.map((t) => (
              <SelectItem key={t} value={t}>
                {TIER_LABEL[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <p className="text-xs text-muted-foreground">
        Scope and tier drive the budget matrix. Changing them re-estimates every task whose
        budget is not yet approved.
      </p>
    </div>
  );
}

export function NewProjectDialog() {
  const router = useRouter();
  const create = useCreateProject();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [scope, setScope] = React.useState<DistributionScope>("worldwide_streaming");
  const [tier, setTier] = React.useState<ProductionTier>("sag_moderate_low");

  const submit = () => {
    if (!name.trim()) {
      toast.error("Give the project a name");
      return;
    }
    create.mutate(
      { name: name.trim(), distribution_scope: scope, production_tier: tier },
      {
        onSuccess: (project) => {
          setOpen(false);
          setName("");
          router.push(`/projects/${project.id}`);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus /> New project
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            Set the release plan up front so estimates are meaningful from the first ingest.
          </DialogDescription>
        </DialogHeader>

        <ScopeFields
          name={name}
          scope={scope}
          tier={tier}
          onName={setName}
          onScope={setScope}
          onTier={setTier}
        />

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create project"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function EditProjectDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Content is unmounted while closed, so each open re-seeds from the
          freshly fetched project. */}
      <EditProjectForm project={project} onDone={() => onOpenChange(false)} />
    </Dialog>
  );
}

function EditProjectForm({
  project,
  onDone,
}: {
  project: Project;
  onDone: () => void;
}) {
  const update = useUpdateProject(project.id);
  const [name, setName] = React.useState(project.name);
  const [scope, setScope] = React.useState<DistributionScope>(project.distribution_scope);
  const [tier, setTier] = React.useState<ProductionTier>(project.production_tier);

  const scopeChanged =
    scope !== project.distribution_scope || tier !== project.production_tier;

  const submit = () => {
    update.mutate(
      { name: name.trim() || project.name, distribution_scope: scope, production_tier: tier },
      {
        onSuccess: () => {
          onDone();
          toast.success(
            scopeChanged ? "Scope updated — unapproved budgets re-estimated" : "Project updated",
          );
        },
      },
    );
  };

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Project scope</DialogTitle>
        <DialogDescription>
          Approved budgets are never recalculated silently — only unapproved tasks move.
        </DialogDescription>
      </DialogHeader>

      <ScopeFields
        name={name}
        scope={scope}
        tier={tier}
        onName={setName}
        onScope={setScope}
        onTier={setTier}
      />

      <DialogFooter>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button onClick={submit} disabled={update.isPending}>
          {update.isPending ? "Saving…" : "Save changes"}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}
