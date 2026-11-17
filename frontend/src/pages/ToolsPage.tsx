import { useEffect, useState } from "react";
import { getToolCatalog } from "../lib/api";
import type { ToolDescriptor } from "../types";

export function ToolsPage() {
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    getToolCatalog(controller.signal)
      .then((payload) => {
        setTools(payload.tools);
        setWriteEnabled(payload.write_tools_enabled);
      })
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  return (
    <div className="page">
      <header className="page-header">
        <h2>运维工具管理</h2>
        <p>
          工具由后端注册表 <code>describe()</code> 输出，含风险等级与参数 JSON Schema。
          当前全部运行在 Mock 后端，不接触任何真实主机；<code>restart_service</code> 需要人工确认。
        </p>
      </header>
      {error && (
        <div className="service-banner" role="status">
          <strong>工具目录不可用</strong>
          <span>{error}</span>
        </div>
      )}
      {loading && !error && <p className="muted">正在加载工具目录…</p>}
      {!loading && !error && (
        <div className="tool-policy">
          <span className="pill">只读工具直接执行</span>
          <span className={`pill ${writeEnabled ? "tool" : ""}`}>
            {writeEnabled ? "写工具已启用：restart_service 需人工确认" : "写工具未启用：restart_service 未注册"}
          </span>
          <span className="muted">权限由后端注册表和工具执行层共同控制，前端不能绕过。</span>
        </div>
      )}
      {tools.length === 0 && !loading && !error && <p className="muted">当前注册表为空。</p>}
      <div className="card-grid">
        {tools.map((tool) => (
          <article key={tool.name} className="tool-card">
            <header>
              <h3>{tool.name}</h3>
              <span className={`risk-badge ${tool.risk}`}>{tool.risk}</span>
              <span className={`pill ${tool.requires_confirmation ? "tool" : ""}`}>
                {tool.requires_confirmation ? "需人工确认" : tool.read_only ? "只读" : "外部调用"}
              </span>
            </header>
            <p>{tool.description}</p>
            <div className="kv-row"><span>启用状态</span><strong>{tool.enabled ? "已启用" : "已停用"}</strong></div>
            <details>
              <summary>参数 Schema</summary>
              <pre>{JSON.stringify(tool.parameters, null, 2)}</pre>
            </details>
          </article>
        ))}
      </div>
      <p className="muted">
        风险说明：read 只读；write 有副作用但可回滚；destructive 必须人工确认；
        external 通过 MCP 调用，标注为模拟数据。任何写操作都不能在前端绕过确认直接执行。
      </p>
    </div>
  );
}
