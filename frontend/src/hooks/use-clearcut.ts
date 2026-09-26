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
  contacts: (taskId: string) => ["contacts", taskId] as const,
  rightsholders: (q: string, layer?: Layer, kind?: RightsholderKind) =>
    ["rightsholders", q, layer ?? null, kind ?? null] as const,
  packetGroups: (id: string) => ["packet-groups", id] as const,
  packets: (id: string) => ["packets", id] as const,
  packet: (id: string) => ["packet", id] as const,
  templates: ["outreach-templates"] as const,
  pdfStatus: ["pdf-status"] as const,
  accesses: (viewId: string) => ["view-accesses", viewId] as const,
  scripts: (id: string) => ["scripts", id] as const,
  scenes: (scriptId: string) => ["scenes", scriptId] as const,
  thread: (packetId: string) => ["thread", packetId] as const,
  inbox: (id: string) => ["inbox", id] as const,
  proposals: (id: string, status: string) => ["proposals", id, status] as const,
  ledger: (id: string) => ["ledger", id] as const,
};

/** Any write can touch tasks, the board and the budget, so refresh the project view as a unit.
 *  Packet grouping reads task stage and assignment, so it moves with them. */
function invalidateProject(qc: QueryClient, projectId: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.assets(projectId) }),
    qc.invalidateQueries({ queryKey: keys.tasks(projectId) }),
    qc.invalidateQueries({ queryKey: keys.board(projectId) }),
    qc.invalidateQueries({ queryKey: keys.budget(projectId) }),
    qc.invalidateQueries({ queryKey: keys.packetGroups(projectId) }),
    qc.invalidateQueries({ queryKey: keys.ledger(projectId) }),
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

export function useTaskContacts(taskId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.contacts(taskId),
    queryFn: () => api.taskContacts(taskId),
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

export function useResolveContacts(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.resolveContacts,
    onSuccess: async (_resolution, taskId) => {
      qc.setQueryData(keys.contacts(taskId), _resolution);
      await invalidateProject(qc, projectId);
    },
    onError: (e) => reportError(e, "Could not work out who to contact"),
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

// ---------------------------------------------------------------- outreach (M4)

export function useOutreachTemplates() {
  return useQuery({
    queryKey: keys.templates,
    queryFn: api.outreachTemplates,
    staleTime: Infinity,
  });
}

/** Whether this host can render PDFs. Cached hard — it cannot change while the API runs. */
export function usePdfStatus() {
  return useQuery({ queryKey: keys.pdfStatus, queryFn: api.pdfStatus, staleTime: Infinity });
}

export function usePacketGroups(projectId: string) {
  return useQuery({
    queryKey: keys.packetGroups(projectId),
    queryFn: () => api.packetGroups(projectId),
  });
}

export function usePackets(projectId: string) {
  return useQuery({
    queryKey: keys.packets(projectId),
    queryFn: () => api.listPackets(projectId),
  });
}

export function usePacket(packetId: string | null) {
  return useQuery({
    queryKey: keys.packet(packetId ?? ""),
    queryFn: () => api.getPacket(packetId!),
    enabled: Boolean(packetId),
  });
}

export function useViewAccesses(viewId: string | null) {
  return useQuery({
    queryKey: keys.accesses(viewId ?? ""),
    queryFn: () => api.contextViewAccesses(viewId!),
    enabled: Boolean(viewId),
  });
}

export function useScripts(projectId: string, enabled = true) {
  return useQuery({
    queryKey: keys.scripts(projectId),
    queryFn: () => api.listScripts(projectId),
    enabled,
  });
}

export function useScenes(scriptId: string | null) {
  return useQuery({
    queryKey: keys.scenes(scriptId ?? ""),
    queryFn: () => api.listScenes(scriptId!),
    enabled: Boolean(scriptId),
  });
}

/** Packet writes touch the packet, the project's packet list and the grouping. */
function invalidatePackets(qc: QueryClient, projectId: string, packetId?: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.packets(projectId) }),
    qc.invalidateQueries({ queryKey: keys.packetGroups(projectId) }),
    ...(packetId ? [qc.invalidateQueries({ queryKey: keys.packet(packetId) })] : []),
  ]);
}

export function useCreatePacket(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof api.createPacket>[1]) =>
      api.createPacket(projectId, body),
    onSuccess: (packet) => invalidatePackets(qc, projectId, packet.id),
    onError: (e) => reportError(e, "Could not build the packet"),
  });
}

export function useUpdatePacket(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      packetId,
      body,
    }: {
      packetId: string;
      body: Parameters<typeof api.updatePacket>[1];
    }) => api.updatePacket(packetId, body),
    onSuccess: (packet) => invalidatePackets(qc, projectId, packet.id),
    onError: (e) => reportError(e, "Could not save the packet"),
  });
}

export function useDeletePacket(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deletePacket,
    onSuccess: () => invalidatePackets(qc, projectId),
    onError: (e) => reportError(e, "Could not delete the packet"),
  });
}

export function useFinalizePacket(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, transitionTasks }: { packetId: string; transitionTasks: boolean }) =>
      api.finalizePacket(packetId, transitionTasks),
    onSuccess: async (packet) => {
      // Finalizing moves the tasks, so the board and budget move with it.
      await invalidateProject(qc, projectId);
      await invalidatePackets(qc, projectId, packet.id);
    },
    onError: (e) => reportError(e, "Could not finalize the packet"),
  });
}

export function useAddExcerpt(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      packetId,
      body,
    }: {
      packetId: string;
      body: Parameters<typeof api.addExcerpt>[1];
    }) => api.addExcerpt(packetId, body),
    onSuccess: (_excerpt, { packetId }) => invalidatePackets(qc, projectId, packetId),
    onError: (e) => reportError(e, "Could not share that excerpt"),
  });
}

export function useDeleteExcerpt(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ excerptId }: { excerptId: string; packetId: string }) =>
      api.deleteExcerpt(excerptId),
    onSuccess: (_void, { packetId }) => invalidatePackets(qc, projectId, packetId),
    onError: (e) => reportError(e, "Could not withdraw the excerpt"),
  });
}

export function useCreateContextView(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      packetId,
      body,
    }: {
      packetId: string;
      body: Parameters<typeof api.createContextView>[1];
    }) => api.createContextView(packetId, body),
    onSuccess: (_view, { packetId }) => invalidatePackets(qc, projectId, packetId),
    onError: (e) => reportError(e, "Could not issue the link"),
  });
}

export function useRevokeContextView(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ viewId }: { viewId: string; packetId: string }) =>
      api.revokeContextView(viewId),
    onSuccess: (_view, { packetId }) => invalidatePackets(qc, projectId, packetId),
    onError: (e) => reportError(e, "Could not revoke the link"),
  });
}

// ---------------------------------------------------------------- mail loop (M5)

export function usePacketThread(packetId: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.thread(packetId ?? ""),
    queryFn: () => api.packetThread(packetId!),
    enabled: Boolean(packetId) && enabled,
    // A thread that does not exist yet is a 404, not an error worth retrying.
    retry: false,
  });
}

export function useInbox(projectId: string) {
  return useQuery({ queryKey: keys.inbox(projectId), queryFn: () => api.inbox(projectId) });
}

export function useProposals(projectId: string, status = "pending") {
  return useQuery({
    queryKey: keys.proposals(projectId, status),
    queryFn: () => api.proposedChanges(projectId, status),
  });
}

export function useLedger(projectId: string) {
  return useQuery({ queryKey: keys.ledger(projectId), queryFn: () => api.ledger(projectId) });
}

/** A reply decision moves a task, so the whole project view and the queues refresh together. */
function invalidateReplies(qc: QueryClient, projectId: string) {
  return Promise.all([
    invalidateProject(qc, projectId),
    qc.invalidateQueries({ queryKey: keys.inbox(projectId) }),
    qc.invalidateQueries({ queryKey: ["proposals", projectId] }),
  ]);
}

export function useSendPacket(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ packetId, allowUnverified }: { packetId: string; allowUnverified: boolean }) =>
      api.sendPacket(packetId, allowUnverified),
    onSuccess: async (_message, { packetId }) => {
      await qc.invalidateQueries({ queryKey: keys.packets(projectId) });
      await qc.invalidateQueries({ queryKey: keys.packet(packetId) });
      await qc.invalidateQueries({ queryKey: keys.thread(packetId) });
    },
    onError: (e) => reportError(e, "Could not send the packet"),
  });
}

export function useApplyProposal(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      quotedAmount,
      reason,
    }: {
      id: string;
      quotedAmount?: string | null;
      reason?: string;
    }) => api.applyProposal(id, { quoted_amount: quotedAmount ?? null, reason: reason ?? null }),
    onSuccess: () => invalidateReplies(qc, projectId),
    onError: (e) => reportError(e, "Could not apply that change"),
  });
}

export function useRejectProposal(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => api.rejectProposal(id, reason),
    onSuccess: () => invalidateReplies(qc, projectId),
    onError: (e) => reportError(e, "Could not reject that change"),
  });
}
