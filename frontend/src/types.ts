export type Strategy = "direct" | "single" | "multi" | "agent" | "refuse";

export type ToolRisk = "read" | "external" | "write" | "destructive";

export interface Citation {
  citation_id: string;
  kind: "knowledge" | "tool";
  document_id: string;
  title: string;
  chunk_id: string;
  section: string | null;
  locator: string;
  excerpt: string;
}

export interface ActionProposal {
  action_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  risk: ToolRisk;
  summary: string;
}

export type ToolExecutionStatus = "ok" | "fallback" | "failed" | "unavailable" | "denied" | "timeout";

export interface ToolTraceItem {
  step_id: number;
  name: string;
  arguments: Record<string, unknown>;
  success: boolean;
  status?: ToolExecutionStatus;
  risk: ToolRisk;
  latency_ms: number;
  error: string | null;
  fallback_from: string | null;
  executed_tool?: string | null;
  failure_kind?: string | null;
  idempotent: boolean;
}

export interface PlanStep {
  step_id: number;
  goal: string;
  tool_name: string | null;
  arguments: Record<string, unknown>;
  needs_retrieval: boolean;
}

export interface AgentPlan {
  steps: PlanStep[];
  rationale: string;
}

export interface CriticIssue {
  code: string;
  message: string;
  severity: "blocking" | "warning";
  action: "accept" | "retrieve" | "plan" | "clarify";
  tool: string | null;
  topic: string | null;
}

export interface CriticResult {
  passed: boolean;
  issues: CriticIssue[];
  next_action: "accept" | "retrieve" | "plan" | "clarify";
  gap_query: string | null;
  checked: string[];
}

export interface RetrievalDetail {
  rewritten_queries: string[];
  top_k: number;
  knowledge_hits: number;
  reranked: Citation[];
  rounds: number;
}

export interface ChatResponse {
  answer: string;
  session_id: string;
  trace_id: string;
  intent: string | null;
  complexity: string | null;
  strategy: Strategy | null;
  execution_status: "completed" | "pending_confirmation" | "refused" | "error";
  plan: AgentPlan | null;
  critic_result: CriticResult | null;
  critic_round: number;
  citations: Citation[];
  pending_action: ActionProposal | null;
  refused: boolean;
  error_code: string | null;
  evidence_sufficient: boolean;
  evidence_gaps: string[];
  tool_trace: ToolTraceItem[];
  retrieval_detail: RetrievalDetail | null;
  latency: { total_ms: number };
}

export interface ChatRequest {
  message: string;
  session_id?: string;
  user_id: string;
  confirm_action_id?: string;
}

export interface Capabilities {
  database: string;
  cache: string;
  vector_store: string;
  retriever: string;
  reranker: string;
  llm: string;
  degraded: boolean;
  ops_backend?: string;
  pending_store?: string;
  hosts?: number;
}

/** A node the graph actually executed. This is the fix for the old UI that
 * silently dropped `node` events and could not show the agent's work. */
export interface NodeEvent {
  seq: number;
  node: string;
  intent?: string;
  strategy?: Strategy;
  tool_trace?: ToolTraceItem[];
  evidence_sufficient?: boolean;
  evidence_gaps?: string[];
}

export type StreamEvent =
  | { event: "started"; trace_id: string }
  | {
      event: "node";
      node: string;
      intent?: string;
      strategy?: Strategy;
      tool_trace?: ToolTraceItem[];
      evidence_sufficient?: boolean;
      evidence_gaps?: string[];
    }
  | { event: "token"; text: string }
  | { event: "answer"; data: ChatResponse }
  | { event: "done"; trace_id: string };

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  state: "complete" | "streaming" | "error" | "stopped";
  citations?: Citation[];
  pendingAction?: ActionProposal | null;
  strategy?: Strategy | null;
  traceId?: string;
  latencyMs?: number;
  evidenceSufficient?: boolean;
  evidenceGaps?: string[];
  toolTrace?: ToolTraceItem[];
  retrievalDetail?: RetrievalDetail | null;
  nodes?: NodeEvent[];
  executionStatus?: ChatResponse["execution_status"];
  plan?: AgentPlan | null;
  criticResult?: CriticResult | null;
  criticRound?: number;
}

export interface Conversation {
  id: string;
  title: string;
  updatedAt: number;
  sessionId?: string;
  messages: Message[];
}

export interface HostProfile {
  host_id: string;
  display_name: string;
  os_name: string;
  os_version: string;
  kernel: string;
  arch: string;
  labels: string[];
}

export interface ServiceRow {
  service: string;
  manager: string;
  state: string;
  enabled: boolean;
  exit_code: number | null;
  restart_count: number;
  last_error: string | null;
  last_start_at?: string;
  last_failure_at?: string;
  stop_reason?: string;
}

export interface PackageRow {
  name: string;
  version: string;
  release: string;
  arch: string;
  install_time: string;
  vendor: string;
}

export interface KnowledgeDocument {
  document_id: string;
  title: string;
  category: string;
  source_type: string;
  source_note: string;
  source_url: string;
  system: string;
  applicable_version: string;
  doc_format: string;
  updated_at: string;
  chunk_count: number;
}

export interface KnowledgeChunk {
  chunk_id: string;
  document_id: string;
  section: string | null;
  chunk_index: number;
  content: string;
}

export interface KnowledgeDetail {
  found: boolean;
  document_id: string;
  document?: KnowledgeDocument;
  chunks?: KnowledgeChunk[];
}

export interface ToolDescriptor {
  name: string;
  risk: ToolRisk;
  description: string;
  parameters: Record<string, unknown>;
  enabled: boolean;
  read_only: boolean;
  requires_confirmation: boolean;
  source: string;
}

export interface DiagnosisRecord {
  trace_id: string;
  session_id: string;
  user_id: string;
  query: string;
  intent: string | null;
  strategy: string | null;
  answer: string;
  citations: Citation[];
  tool_trace: ToolTraceItem[];
  retrieval: RetrievalDetail | Record<string, never>;
  evidence_sufficient: boolean;
  evidence_gaps: string[];
  refused: boolean;
  latency: { total_ms?: number };
  created_at: string;
  execution_status: ChatResponse["execution_status"];
  plan: AgentPlan | null;
  critic_result: CriticResult | null;
  critic_round: number;
}

export interface HostOverview {
  host_id: string;
  system: {
    os_name: string;
    os_version: string;
    kernel: string;
    arch: string;
    uptime: string;
    simulated: string;
  };
  resources: {
    cpu: { usage_pct: number; load_1: number; load_5: number; load_15: number; cores: number };
    memory: { usage_pct: number; total_kb: number; available_kb: number; swap_used_kb: number };
  };
  top_processes: { pid: number; name: string; cpu_pct: number; mem_pct: number; rss_kb?: number }[];
  disks: { mount: string; use_pct: number; size_kb: number; avail_kb: number }[];
  inode_use_pct: number | null;
  services: ServiceRow[];
  packages: PackageRow[];
  error_logs: {
    service: string | null;
    source: string;
    entries: {
      ts?: string;
      level?: string;
      msg?: string;
      unit?: string;
      error_type?: string;
    }[];
    truncated?: boolean;
    simulated?: boolean;
  };
  simulated: boolean;
  note: string;
}
