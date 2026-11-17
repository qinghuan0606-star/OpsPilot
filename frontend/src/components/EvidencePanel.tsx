import { AlertTriangle, CheckCircle2, ChevronRight, Wrench } from "lucide-react";
import type { Citation, Message, RetrievalDetail, ToolTraceItem } from "../types";

function citationKindLabel(kind: string): string {
  return kind === "tool" ? "工具证据" : "知识证据";
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) {
    return <p className="muted">本次没有可展示的引用。</p>;
  }
  return (
    <ul className="evidence-list">
      {citations.map((item) => (
        <li key={item.citation_id}>
          <span className={`evidence-kind ${item.kind}`}>{citationKindLabel(item.kind)}</span>
          <div>
            <strong>{item.title}</strong>
            <p className="evidence-locator">{item.locator || item.document_id}</p>
            <p className="evidence-excerpt">{item.excerpt}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

function toolStatusLabel(item: ToolTraceItem): string {
  if (item.status === "unavailable") return "不可用";
  if (item.status === "denied") return "被拒绝";
  if (item.status === "timeout") return "超时";
  if (item.status === "fallback") return "降级";
  if (item.status === "failed" || !item.success) return "失败";
  return "成功";
}

export function ToolTrace({ items }: { items: ToolTraceItem[] }) {
  if (!items.length) return <p className="muted">本次没有调用运维工具。</p>;
  return (
    <ul className="trace-list">
      {items.map((item) => (
        <li key={`${item.step_id}-${item.name}`}>
          <span className={`trace-status ${item.success && item.status !== "fallback" ? "ok" : "fail"}`}>
            {item.success && item.status !== "fallback" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
          </span>
          <div>
            <strong>
              {item.step_id}. {item.name}
              <span className={`risk-badge ${item.risk}`}>{item.risk}</span>
              <span className="pill">{toolStatusLabel(item)}</span>
            </strong>
            <p className="evidence-locator">
              {JSON.stringify(item.arguments)}
              {item.latency_ms ? ` · ${Math.round(item.latency_ms)}ms` : ""}
              {item.idempotent ? " · 幂等复用" : ""}
              {item.fallback_from ? ` · 由 ${item.fallback_from} 降级` : ""}
            </p>
            {item.error && <p className="evidence-excerpt">错误：{item.error}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function PlanPanel({ plan }: { plan: Message["plan"] }) {
  if (!plan || plan.steps.length === 0) {
    return <p className="muted">本次没有生成工具计划（直接回答、纯知识检索或需要澄清）。</p>;
  }
  return (
    <div className="plan-panel">
      {plan.rationale && <p className="evidence-excerpt">{plan.rationale}</p>}
      <ol className="plan-list">
        {plan.steps.map((step) => (
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
    </div>
  );
}

function CriticPanel({ result }: { result: Message["criticResult"] }) {
  if (!result) return <p className="muted">本次没有 Critic 结果（直接回答或未进入诊断链路）。</p>;
  return (
    <div className="critic-panel">
      <div className="kv-row">
        <span>检查结果</span>
        <strong className={result.passed ? "ok" : "warn"}>
          {result.passed ? "通过" : `未通过 · ${result.next_action}`}
        </strong>
      </div>
      {result.checked.length > 0 && (
        <p className="evidence-excerpt">检查项：{result.checked.join(" / ")}</p>
      )}
      {result.issues.length === 0 ? (
        <p className="muted">没有发现阻断性问题。</p>
      ) : (
        <ul className="gap-list">
          {result.issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>
              [{issue.severity}] {issue.code}：{issue.message}
              {issue.tool ? `（${issue.tool}）` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RetrievalPanel({ detail }: { detail: RetrievalDetail }) {
  return (
    <div className="retrieval-panel">
      <div className="kv-row"><span>检索轮次</span><strong>{detail.rounds}</strong></div>
      <div className="kv-row"><span>命中片段</span><strong>{detail.knowledge_hits}</strong></div>
      <div className="kv-row"><span>重写查询</span><strong>{detail.rewritten_queries.length || 0}</strong></div>
      {detail.rewritten_queries.length > 0 && (
        <p className="evidence-excerpt">{detail.rewritten_queries.join(" ｜ ")}</p>
      )}
      {detail.reranked.length > 0 && (
        <ul className="ranked-list">
          {detail.reranked.slice(0, 5).map((item, index) => (
            <li key={item.citation_id}>
              <span className="rank-index">{index + 1}</span>
              <span>{item.title}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The right-hand inspector of the workbench: everything the agent actually did. */
export function EvidencePanel({ message }: { message: Message }) {
  const nodes = message.nodes ?? [];
  return (
    <aside className="inspector">
      <section>
        <h3>工作流节点</h3>
        {nodes.length === 0 ? <p className="muted">尚未收到节点事件。</p> : (
          <ul className="node-list">
            {nodes.map((node) => (
              <li key={node.seq}>
                <ChevronRight size={13} />
                <span>{node.node}</span>
                {node.strategy && <span className="pill">{node.strategy}</span>}
                {node.tool_trace && node.tool_trace.length > 0 && (
                  <span className="pill tool">{node.tool_trace.length} 次工具调用</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3>策略与证据</h3>
        <div className="kv-row"><span>策略路由</span><strong>{message.strategy ?? "未知"}</strong></div>
        <div className="kv-row"><span>证据充分性</span>
          <strong className={message.evidenceSufficient === false ? "warn" : "ok"}>
            {message.evidenceSufficient === false ? "不足" : "充分"}
          </strong>
        </div>
        {(message.evidenceGaps ?? []).length > 0 && (
          <ul className="gap-list">
            {(message.evidenceGaps ?? []).map((gap) => <li key={gap}>{gap}</li>)}
          </ul>
        )}
        {message.retrievalDetail && <RetrievalPanel detail={message.retrievalDetail} />}
      </section>

      <section>
        <h3>执行状态</h3>
        <div className="kv-row"><span>最终状态</span><strong>{message.executionStatus ?? "completed"}</strong></div>
        {message.criticRound ? <div className="kv-row"><span>Critic 修正轮次</span><strong>{message.criticRound}</strong></div> : null}
      </section>

      <section>
        <h3>Planner 任务计划</h3>
        <PlanPanel plan={message.plan} />
      </section>

      <section>
        <h3>Critic 检查</h3>
        <CriticPanel result={message.criticResult} />
      </section>

      <section>
        <h3><Wrench size={14} /> 工具调用</h3>
        <ToolTrace items={message.toolTrace ?? []} />
      </section>

      <section>
        <h3>引用来源</h3>
        <CitationList citations={message.citations ?? []} />
      </section>

      {message.traceId && (
        <section>
          <h3>Trace</h3>
          <code className="trace-id">{message.traceId}</code>
        </section>
      )}
    </aside>
  );
}
