/** Shared wire types mirroring backend/app/schemas/common.py (contract C-2, C-3). Owner: P1. */

export const MEMORY_TYPES = [
  "decision",
  "security_constraint",
  "convention",
  "api_contract",
  "incident",
  "failed_approach",
  "deployment",
  "preference",
] as const;
export type MemoryType = (typeof MEMORY_TYPES)[number];
export type RecordStatus = "active" | "superseded" | "retracted";
export type RetainState = "pending" | "retained" | "failed" | "retag_pending";
export type ConfidenceBand = "high" | "medium" | "low";

export type RecordRef = {
  id: string;
  pill: string;
  type: MemoryType;
  title: string;
  statement: string;
  area: string;
  importance: number;
  status: RecordStatus;
  confidence_band: ConfidenceBand;
  decided_at: string;
  tentative: boolean;
};

export type MemoryRecordOut = RecordRef & {
  project_id: string;
  rationale: string | null;
  applies_to: string[];
  confidence: number;
  stated_by: "human" | "agent" | "both";
  source_session_id: string | null;
  evidence_quote: string | null;
  supersedes_record_id: string | null;
  superseded_by_record_id: string | null;
  hindsight_document_id: string;
  retain_state: RetainState;
  source: "extracted" | "manual" | "seed";
  approved_by: string | null;
  approved_at: string | null;
  review_due_at: string | null;
  evidence_count: number;
};

/** Minimal project shape; P2 owns the full schema. */
export type ProjectSummary = {
  id: string;
  name: string;
  bank_status?: "provisioning" | "ready" | "error";
  hindsight_bank_id?: string;
};
