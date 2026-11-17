import { useEffect, useState } from "react";
import { getDiagnoses } from "../lib/api";
import type { DiagnosisRecord } from "../types";

/** Agent execution records: the node/tool timeline of every persisted run. */
export function TracesPage() {
  const [items, setItems] = useState<DiagnosisRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    getDiagnoses(30, controller.signal)
      .then((payload) => setItems(payload.items))
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <div className="page">
      <header className="page-header">
        <h2>Agent 执行记录</h2>
        <p>
          按后端持久化的工具轨迹还原执行过程：谁被调用、参数是什么、耗时、是否降级、是否幂等复用。
          流式响应中的 <code>node</code> 事件在工作台右侧实时展示，本页用于事后回溯。
        </p>
      </header>
      {error && (
        <div className="service-banner" role="status">
          <strong>执行记录不可用</strong>
          <span>{error}</span>
        </div>
      )}
      {loading && !error && <p className="muted">正在加载执行记录…</p>}
      {items.length === 0 && !error && !loading && (
        <p className="muted">还没有执行记录，先去工作台问一个运维问题。</p>
      )}
      {items.map((item) => (
        <article key={item.trace_id} className="trace-card">
          <header>
            <div>
              <h3>{item.query}</h3>
              <p className="muted">
                {item.created_at.replace("T", " ").slice(0, 19)} · 策略 {item.strategy ?? "—"} ·
                Trace <code>{item.trace_id}</code>
              </p>
            </div>
            <span className={item.evidence_sufficient ? "state ok" : "state warn"}>
              {item.evidence_sufficient ? "证据充分" : "证据不足"}
            </span>
          </header>
          <div className="trace-summary">
            <span className={`state ${item.execution_status === "completed" ? "ok" : "warn"}`}>
              {item.execution_status}
            </span>
            <span className="muted">Critic 修正轮次 {item.critic_round}</span>
          </div>

          <section>
            <h4>Planner 计划</h4>
            {item.plan && item.plan.steps.length > 0 ? (
              <ol className="plan-list">
                {item.plan.steps.map((step) => (
                  <li key={step.step_id}>
                    <strong>{step.step_id}. {step.goal}</strong>
                    <span className="evidence-locator">
                      {step.tool_name ?? "无需工具"}
                      {step.needs_retrieval ? " · 同时检索知识" : ""}
                      {Object.keys(step.arguments).length ? ` · ${JSON.stringify(step.arguments)}` : ""}
                    </span>
                  </li>
                ))}
              </ol>
            ) : <p className="muted">没有计划明细（直接回答或需要澄清）。</p>}
          </section>

          <section>
            <h4>Critic 检查</h4>
            {item.critic_result ? (
              <>
                <div className="kv-row"><span>结果</span><strong className={item.critic_result.passed ? "ok" : "warn"}>{item.critic_result.passed ? "通过" : "未通过"}</strong></div>
                {item.critic_result.issues.length > 0 ? (
                  <ul className="gap-list">
                    {item.critic_result.issues.map((issue, index) => (
                      <li key={`${issue.code}-${index}`}>[{issue.severity}] {issue.code}：{issue.message}</li>
                    ))}
                  </ul>
                ) : <p className="muted">没有阻断性问题。</p>}
              </>
            ) : <p className="muted">没有 Critic 明细，可能是旧记录或未进入诊断链路。</p>}
          </section>

          {item.tool_trace.length === 0 ? (
            <p className="muted">本次没有工具调用（知识问答 / 直接回答 / 拒答）。</p>
          ) : (
            <ol className="timeline">
              {item.tool_trace.map((tool) => (
                <li key={`${tool.step_id}-${tool.name}`}>
                  <span className={`timeline-dot ${tool.success ? "ok" : "fail"}`} />
                  <div>
                    <strong>
                      {tool.step_id}. {tool.name}
                      <span className={`risk-badge ${tool.risk}`}>{tool.risk}</span>
                      <span className="pill">{tool.status ?? (tool.success ? "ok" : "failed")}</span>
                    </strong>
                    <p className="evidence-locator">
                      {JSON.stringify(tool.arguments)}
                      {tool.latency_ms ? ` · ${Math.round(tool.latency_ms)}ms` : ""}
                      {tool.idempotent ? " · 幂等复用" : ""}
                      {tool.fallback_from ? ` · 由 ${tool.fallback_from} 降级` : ""}
                    </p>
                    {tool.error && <p className="evidence-excerpt">错误：{tool.error}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </article>
      ))}
      <p className="muted">
        说明：本页从 diagnosis_runs 与 diagnosis_traces 读取计划、Critic 和工具轨迹；
        逐节点事件仍在工作台 SSE 中实时展示，未逐条落库。
      </p>
    </div>
  );
}
