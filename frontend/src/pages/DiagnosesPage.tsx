import { useEffect, useState } from "react";
import { getDiagnoses, getDiagnosis } from "../lib/api";
import type { DiagnosisRecord } from "../types";

function strategyLabel(strategy: string | null): string {
  return strategy ? strategy.toUpperCase() : "—";
}

export function DiagnosesPage() {
  const [items, setItems] = useState<DiagnosisRecord[]>([]);
  const [selected, setSelected] = useState<DiagnosisRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getDiagnoses(30, controller.signal)
      .then((payload) => setItems(payload.items))
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function openDetail(item: DiagnosisRecord) {
    setSelected(item);
    setDetailError(null);
    setDetailLoading(true);
    try {
      const payload = await getDiagnosis(item.trace_id);
      if (!payload.found || !payload.item) {
        setDetailError("后端未找到该诊断记录。");
      } else {
        setSelected(payload.item);
      }
    } catch (exc: unknown) {
      setDetailError(exc instanceof Error ? exc.message : "详情加载失败");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <h2>故障诊断记录</h2>
        <p>
          每次问答都落库到 <code>diagnosis_runs</code>，记录策略、证据充分性、工具调用与引用，
          便于复盘与责任追溯。
        </p>
      </header>
      {error && (
        <div className="service-banner" role="status">
          <strong>诊断记录不可用</strong>
          <span>{error}</span>
        </div>
      )}
      {loading && !error && <p className="muted">正在加载诊断记录…</p>}
      {items.length === 0 && !error && !loading && <p className="muted">还没有记录，先去工作台问一个运维问题。</p>}
      <table className="data-table clickable">
        <thead>
          <tr>
            <th>时间</th>
            <th>问题</th>
            <th>策略</th>
            <th>证据</th>
            <th>工具</th>
            <th>Trace</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.trace_id} onClick={() => void openDetail(item)}>
              <td>{item.created_at.replace("T", " ").slice(0, 19)}</td>
              <td>{item.query}</td>
              <td>{strategyLabel(item.strategy)}</td>
              <td>
                <span className={item.evidence_sufficient ? "state ok" : "state warn"}>
                  {item.evidence_sufficient ? "充分" : "不足"}
                </span>
              </td>
              <td>{item.tool_trace.length}</td>
              <td>
                <code>{item.trace_id.slice(0, 12)}…</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && (
        <section className="detail-panel">
          <header>
            <h3>诊断详情</h3>
            <button className="cancel-button" onClick={() => setSelected(null)}>关闭</button>
          </header>
          <div className="kv-row"><span>问题</span><strong>{selected.query}</strong></div>
          <div className="kv-row"><span>策略</span><strong>{strategyLabel(selected.strategy)}</strong></div>
          <div className="kv-row"><span>Trace</span><code>{selected.trace_id}</code></div>
          <div className="kv-row"><span>执行状态</span><strong>{selected.execution_status}</strong></div>
          {detailLoading && <p className="muted">正在读取详情…</p>}
          {detailError && <p className="muted warn">详情接口：{detailError}</p>}
          {(selected.evidence_gaps ?? []).length > 0 && (
            <ul className="gap-list">
              {selected.evidence_gaps.map((gap) => <li key={gap}>{gap}</li>)}
            </ul>
          )}
          <pre className="answer-block">{selected.answer}</pre>
          <h4>Planner 任务计划</h4>
          {selected.plan && selected.plan.steps.length > 0 ? (
            <ol className="plan-list">
              {selected.plan.steps.map((step) => (
                <li key={step.step_id}>
                  <strong>{step.step_id}. {step.goal}</strong>
                  <span className="evidence-locator">
                    {step.tool_name ?? "无需工具"} {JSON.stringify(step.arguments)}
                  </span>
                </li>
              ))}
            </ol>
          ) : <p className="muted">没有计划明细。</p>}

          <h4>Critic 检查</h4>
          {selected.critic_result ? (
            <div>
              <div className="kv-row"><span>结果</span><strong className={selected.critic_result.passed ? "ok" : "warn"}>{selected.critic_result.passed ? "通过" : "未通过"}</strong></div>
              {(selected.critic_result.issues ?? []).length > 0 ? (
                <ul className="gap-list">
                  {selected.critic_result.issues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`}>[{issue.severity}] {issue.code}：{issue.message}</li>
                  ))}
                </ul>
              ) : <p className="muted">未发现问题。</p>}
            </div>
          ) : <p className="muted">该记录没有 Critic 明细。</p>}

          <h4>工具调用</h4>
          <ul className="trace-list">
            {selected.tool_trace.map((tool) => (
              <li key={`${tool.step_id}-${tool.name}`}>
                <span className={`trace-status ${tool.success ? "ok" : "fail"}`}>
                  {tool.success ? "成功" : "失败"}
                </span>
                <span>
                  {tool.name} {JSON.stringify(tool.arguments)}
                </span>
              </li>
            ))}
          </ul>
          <h4>引用</h4>
          <ul className="evidence-list">
            {selected.citations.map((citation) => (
              <li key={citation.citation_id}>
                <span className={`evidence-kind ${citation.kind}`}>{citation.kind}</span>
                <div>
                  <strong>{citation.title}</strong>
                  <p className="evidence-locator">{citation.locator}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
