"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, api } from "@/lib/api";
import type { Layer, RightsholderKind, Stage } from "@/lib/types";

export const keys = {
  disclaimer: ["disclaimer"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  assets: (id: string) => ["assets", id] as const,
  tasks: (id: string) => ["tasks", id] as const,
  board: (id: string) => ["board", id] as const,
  budget: (id: string) => ["budget", id] as const,
  history: (taskId: string) => ["history", taskId] as const,
  rightsholders: (q: string, layer?: Layer, kind?: RightsholderKind) =>
    ["rightsholders", q, layer ?? null, kind ?? null] as const,
};

/** Any write can touch tasks, the board and the budget, so refresh the project view as a unit. */
function invalidateProject(qc: QueryClient, projectId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.assets(projectId) }),
    qc.invalidateQueries({ queryKey: keys.tasks(projectId) }),
    qc.invalidateQueries({ queryKey: keys.board(projectId) }),
    qc.invalidateQueries({ queryKey: keys.budget(projectId) }),
  ]);
}

/** Surfaces the backend's own message: 428 disclaimer, 409 workflow rule, 422 validation. */
export function reportError(error: unknown, fallback = "Something went wrong") {
  if (error instanceof ApiError) {
    if (error.isDisclaimerRequired) {
      toast.error("Accept the disclaimer first", { description: error.message });
      return;
    }
    toast.error(error.isWorkflowError ? "Not allowed by the workflow" : fallback, {
      description: error.message,
    });
    return;
  }
  toast.error(fallback, {
    description: error instanceof Error ? error.message : String(error),
  });
}

// ------------------------------------------------------------------ queries

export function useDisclaimer() {
  return useQuery({
    queryKey: keys.disclaimer,
    queryFn: api.getDisclaimer,
    staleTime: Infinity,
  });
}

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.listProjects });
}

export function useProject(id: string) {
  return useQuery({ queryKey: keys.project(id), queryFn: () => api.getProject(id) });
}

export function useAssets(projectId: string) {
  return useQuery({
    queryKey: keys.assets(projectId),
    queryFn: () => api.listAssets(projectId),
  });
}

export function useTasks(projectId: string) {
  return useQuery({
    queryKey: keys.tasks(projectId),
    queryFn: () => api.listTasks(projectId),
  });
}

export function useBoard(projectId: string) {
  return useQuery({
    queryKey: keys.board(projectId),
    queryFn: () => api.board(projectId),
  });
}

export function useBudget(projectId: string) {
  return useQuery({
    queryKey: keys.budget(projectId),
    queryFn: () => api.budget(projectId),
  });
}

export function useTaskHistory(taskId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.history(taskId),
    queryFn: () => api.taskHistory(taskId),
    enabled,
  });
}

export function useRightsholderSearch(
  q: string,
  layer?: Layer,
  kind?: RightsholderKind,
  enabled = true,
) {
  return useQuery({
    queryKey: keys.rightsholders(q, layer, kind),
    queryFn: () => api.searchRightsholders({ q: q || undefined, layer, kind, limit: 25 }),
    enabled,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------- mutations

export function useAcceptDisclaimer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.acceptDisclaimer,
    onSuccess: (data) => qc.setQueryData(keys.disclaimer, data),
    onError: (e) => reportError(e, "Could not record your acceptance"),
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
    onError: (e) => reportError(e, "Could not create the project"),
  });
}

export function useUpdateProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.updateProject>[1]) =>
      api.updateProject(projectId, body),
    onSuccess: async (project) => {
      qc.setQueryData(keys.project(projectId), project);
      await qc.invalidateQueries({ queryKey: keys.projects });
      // Changing scope or tier re-runs the budget matrix on the server.
      await invalidateProject(qc, projectId);
    },
    onError: (e) => reportError(e, "Could not update the project"),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
    onError: (e) => reportError(e, "Could not delete the project"),
  });
}

export function useIngest(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (items: { url: string; notes?: string | null; usage_seconds?: number | null }[]) =>
      api.ingest(projectId, items),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Ingest failed"),
  });
}

export function useUpdateAsset(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      assetId,
      body,
    }: {
      assetId: string;
      body: Parameters<typeof api.updateAsset>[1];
    }) => api.updateAsset(assetId, body),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not save the asset"),
  });
}

export function useDeleteAsset(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteAsset,
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not remove the asset"),
  });
}

export function useAddLayer(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ assetId, layer }: { assetId: string; layer: Layer }) =>
      api.addLayer(assetId, layer),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not add the layer"),
  });
}

export function useRemapAsset(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.remapAsset,
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not re-run rights matching"),
  });
}

export function useUpdateTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      body,
    }: {
      taskId: string;
      body: Parameters<typeof api.updateTask>[1];
    }) => api.updateTask(taskId, body),
    onSuccess: async (_task, { taskId }) => {
      await invalidateProject(qc, projectId);
      await qc.invalidateQueries({ queryKey: keys.history(taskId) });
    },
    onError: (e) => reportError(e, "Could not save the task"),
  });
}

export function useTransition(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, to, reason }: { taskId: string; to: Stage; reason?: string }) =>
      api.transition(taskId, to, reason),
    onSuccess: async (_task, { taskId }) => {
      await invalidateProject(qc, projectId);
      await qc.invalidateQueries({ queryKey: keys.history(taskId) });
    },
    onError: (e) => reportError(e, "Could not move the task"),
  });
}

export function useEstimateTask(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.estimateTask,
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not estimate the task"),
  });
}

export function useReestimateProject(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.reestimateProject(projectId),
    onSuccess: () => invalidateProject(qc, projectId),
    onError: (e) => reportError(e, "Could not re-run the budget matrix"),
  });
}
