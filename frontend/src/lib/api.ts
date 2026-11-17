import type {
  Capabilities,
  ChatRequest,
  DiagnosisRecord,
  HostOverview,
  HostProfile,
  KnowledgeDetail,
  KnowledgeDocument,
  PackageRow,
  ServiceRow,
  StreamEvent,
  ToolDescriptor,
} from "../types";
import { SseDecoder } from "./sse";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) throw new Error(`请求失败（HTTP ${response.status}）`);
  return (await response.json()) as T;
}

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/health`, { signal });
    return response.ok;
  } catch {
    return false;
  }
}

export async function getCapabilities(signal?: AbortSignal): Promise<Capabilities | null> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/capabilities`, { signal });
    return response.ok ? ((await response.json()) as Capabilities) : null;
  } catch {
    return null;
  }
}

export const getHosts = (signal?: AbortSignal) =>
  getJson<{ hosts: HostProfile[]; count: number; backend: string }>("/api/v1/ops/hosts", signal);

export const getHostOverview = (hostId: string, signal?: AbortSignal) =>
  getJson<HostOverview>(`/api/v1/ops/hosts/${encodeURIComponent(hostId)}/overview`, signal);

export const getServices = (hostId: string, signal?: AbortSignal) =>
  getJson<{ host_id: string; services: ServiceRow[]; count: number }>(
    `/api/v1/ops/services?host_id=${encodeURIComponent(hostId)}`,
    signal,
  );

export const getPackages = (hostId: string, signal?: AbortSignal) =>
  getJson<{ host_id: string; packages: PackageRow[]; count: number }>(
    `/api/v1/ops/packages?host_id=${encodeURIComponent(hostId)}`,
    signal,
  );

export const getKnowledgeDocuments = (signal?: AbortSignal) =>
  getJson<{ documents: KnowledgeDocument[]; count: number }>(
    "/api/v1/ops/knowledge/documents",
    signal,
  );

export const getKnowledgeDocument = (documentId: string, signal?: AbortSignal) =>
  getJson<KnowledgeDetail>(
    `/api/v1/ops/knowledge/documents/${encodeURIComponent(documentId)}`,
    signal,
  );

export const getToolCatalog = (signal?: AbortSignal) =>
  getJson<{ count: number; tools: ToolDescriptor[]; write_tools_enabled: boolean }>(
    "/api/v1/ops/tools",
    signal,
  );

export const getDiagnoses = (limit = 20, signal?: AbortSignal) =>
  getJson<{ items: DiagnosisRecord[]; count: number }>(
    `/api/v1/diagnoses?limit=${limit}`,
    signal,
  );

export const getDiagnosis = (traceId: string, signal?: AbortSignal) =>
  getJson<{ found: boolean; trace_id: string; item?: DiagnosisRecord }>(
    `/api/v1/diagnoses/${encodeURIComponent(traceId)}`,
    signal,
  );

export async function streamChat(
  payload: ChatRequest,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    let message =
      response.status >= 500 ? "服务暂时不可用，请稍后重试。" : `请求失败（HTTP ${response.status}）`;
    try {
      const error: unknown = await response.json();
      if (typeof error === "object" && error !== null && "message" in error) {
        const detail = String(error.message);
        message = detail === "internal error" ? "服务暂时不可用，请稍后重试。" : detail;
      }
    } catch {
      /* Use the HTTP status when no JSON error body is available. */
    }
    throw new Error(message);
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new SseDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decoder.feed(value)) onEvent(event);
    }
    for (const event of decoder.finish()) onEvent(event);
  } finally {
    reader.releaseLock();
  }
}
