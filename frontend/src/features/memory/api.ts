/** Memory queries. Owner: P3. */
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { MemoryRecordOut } from "../../api/types";

export type RecordDetail = MemoryRecordOut & {
  retained_content: string;
  version_chain: string[];
  evidence: { session_id: string | null; quote: string; added_at?: string }[];
};

export type TimelineEvent = {
  id: string;
  event_type: string;
  status: string;
  record_id: string | null;
  record_title: string | null;
  detail: Record<string, unknown>;
  created_at: string;
};

export function useRecords(projectId: string, params: Record<string, string>) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  return useQuery({
    queryKey: ["memories", projectId, qs],
    queryFn: () => api.get<MemoryRecordOut[]>(`/projects/${projectId}/memories${qs ? `?${qs}` : ""}`),
  });
}

export function useRecord(projectId: string, recordId: string) {
  return useQuery({
    queryKey: ["memory", projectId, recordId],
    queryFn: () => api.get<RecordDetail>(`/projects/${projectId}/memories/${recordId}`),
  });
}

export function useTimeline(projectId: string) {
  return useQuery({
    queryKey: ["timeline", projectId],
    queryFn: () => api.get<TimelineEvent[]>(`/projects/${projectId}/timeline`),
  });
}
