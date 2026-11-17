import { useEffect, useState } from "react";
import { getCapabilities, getHostOverview, getHosts } from "../lib/api";
import type { Capabilities, HostOverview, HostProfile } from "../types";

function meterClass(pct: number): string {
  if (pct >= 90) return "meter critical";
  if (pct >= 75) return "meter warn";
  return "meter ok";
}

export function MonitoringPage() {
  const [hosts, setHosts] = useState<HostProfile[]>([]);
  const [hostId, setHostId] = useState("");
  const [overview, setOverview] = useState<HostOverview | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHosts(controller.signal)
      .then((payload) => {
        setHosts(payload.hosts);
        setHostId((current) => current || payload.hosts[0]?.host_id || "");
      })
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"));
    void getCapabilities(controller.signal).then(setCapabilities);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!hostId) return;
    const controller = new AbortController();
    setLoading(true);
    getHostOverview(hostId, controller.signal)
      .then(setOverview)
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [hostId]);

  return (
    <div className="page">
      <header className="page-header">
        <h2>系统运行监控</h2>
        <p>
          数据来自 Mock 运维后端（<code>OPS_TOOL_BACKEND</code>），全部为模拟主机快照，
          不对应任何真实服务器；指标不构成生产结论。
        </p>
      </header>
      {error && (
        <div className="service-banner" role="status">
          <strong>监控数据不可用</strong>
          <span>{error}</span>
        </div>
      )}

      {loading && <p className="muted">正在读取主机快照…</p>}
      {!overview && !loading && !error && <p className="muted">当前没有可展示的主机快照。</p>}

      <div className="host-picker">
        {hosts.map((host) => (
          <button
            key={host.host_id}
            className={host.host_id === hostId ? "host-chip active" : "host-chip"}
            onClick={() => setHostId(host.host_id)}
          >
            <strong>{host.host_id}</strong>
            <span>{host.display_name}</span>
          </button>
        ))}
      </div>

      {overview && (
        <>
          <section className="cards-row">
            <article className="stat-card">
              <span>发行版</span>
              <strong>{overview.system.os_name} {overview.system.os_version}</strong>
              <small>内核 {overview.system.kernel}</small>
            </article>
            <article className="stat-card">
              <span>CPU 使用率</span>
              <strong>{overview.resources.cpu.usage_pct}%</strong>
              <div className={meterClass(overview.resources.cpu.usage_pct)}>
                <div style={{ width: `${Math.min(100, overview.resources.cpu.usage_pct)}%` }} />
              </div>
              <small>{overview.resources.cpu.cores} 核 · load 1/5/15：{overview.resources.cpu.load_1} / {overview.resources.cpu.load_5} / {overview.resources.cpu.load_15}</small>
            </article>
            <article className="stat-card">
              <span>内存使用率</span>
              <strong>{overview.resources.memory.usage_pct}%</strong>
              <div className={meterClass(overview.resources.memory.usage_pct)}>
                <div style={{ width: `${Math.min(100, overview.resources.memory.usage_pct)}%` }} />
              </div>
              <small>可用 {Math.round(overview.resources.memory.available_kb / 1024)} MB</small>
            </article>
            <article className="stat-card">
              <span>inode 使用率</span>
              <strong>{overview.inode_use_pct === null ? "—" : `${overview.inode_use_pct}%`}</strong>
              {overview.inode_use_pct !== null && (
                <div className={meterClass(overview.inode_use_pct)}>
                  <div style={{ width: `${Math.min(100, overview.inode_use_pct)}%` }} />
                </div>
              )}
              <small>磁盘容量之外单独统计</small>
            </article>
            <article className="stat-card">
              <span>运行时长</span>
              <strong>{overview.system.uptime || "—"}</strong>
              <small>{overview.system.arch} · simulated={overview.system.simulated}</small>
            </article>
          </section>

          <section>
            <h3>文件系统</h3>
            <table className="data-table">
              <thead>
                <tr><th>挂载点</th><th>使用率</th><th>总量</th><th>可用</th></tr>
              </thead>
              <tbody>
                {overview.disks.map((disk) => (
                  <tr key={disk.mount}>
                    <td>{disk.mount}</td>
                    <td>
                      <div className={meterClass(disk.use_pct)}>
                        <div style={{ width: `${Math.min(100, disk.use_pct)}%` }} />
                      </div>
                      {disk.use_pct}%
                    </td>
                    <td>{Math.round(disk.size_kb / 1024 / 1024)} GB</td>
                    <td>{Math.round(disk.avail_kb / 1024 / 1024)} GB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h3>进程资源</h3>
            {overview.top_processes.length === 0 ? (
              <p className="muted">Mock 快照没有进程级数据。</p>
            ) : (
              <table className="data-table">
                <thead><tr><th>PID</th><th>进程</th><th>CPU %</th><th>内存 %</th><th>RSS</th></tr></thead>
                <tbody>
                  {overview.top_processes.map((proc) => (
                    <tr key={proc.pid}>
                      <td>{proc.pid}</td>
                      <td>{proc.name}</td>
                      <td>{proc.cpu_pct}</td>
                      <td>{proc.mem_pct}</td>
                      <td>{proc.rss_kb ? `${Math.round(proc.rss_kb / 1024)} MB` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h3>服务状态</h3>
            <table className="data-table">
              <thead>
                <tr><th>服务</th><th>管理器</th><th>状态</th><th>启用</th><th>退出码</th><th>重启次数</th><th>最近失败</th><th>停止原因</th></tr>
              </thead>
              <tbody>
                {overview.services.map((service) => (
                  <tr key={service.service}>
                    <td>{service.service}</td>
                    <td>{service.manager}</td>
                    <td>
                      <span className={`state ${service.state === "failed" ? "warn" : "ok"}`}>
                        {service.state}
                      </span>
                    </td>
                    <td>{service.enabled ? "是" : "否"}</td>
                    <td>{service.exit_code ?? "—"}</td>
                    <td>{service.restart_count}</td>
                    <td>{service.last_failure_at ?? "—"}</td>
                    <td>{service.stop_reason ?? service.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section>
            <h3>系统错误日志</h3>
            <div className="kv-row">
              <span>来源</span>
              <strong>
                {overview.error_logs.source === "unavailable"
                  ? "日志不可用"
                  : `${overview.error_logs.source === "supervisor" ? "Supervisor" : "journal"} · ${overview.error_logs.service ?? "—"}`}
              </strong>
            </div>
            <p className="muted">模拟日志；优先展示故障服务 warn 及以上条目，不代表真实主机日志。</p>
            {overview.error_logs.entries.length === 0 ? (
              <p className="muted">没有可展示的错误日志条目。</p>
            ) : (
              <ul className="log-list">
                {overview.error_logs.entries.slice(-10).map((entry, index) => (
                  <li key={`${entry.ts ?? ""}-${index}`}>
                    <span className={`risk-badge ${entry.level === "error" ? "destructive" : "read"}`}>{entry.level ?? "info"}</span>
                    <code>{entry.ts ?? "—"}</code>
                    <span>{entry.msg ?? entry.error_type ?? "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3>软件包</h3>
            <table className="data-table">
              <thead>
                <tr><th>包名</th><th>版本</th><th>架构</th><th>安装时间</th><th>vendor</th></tr>
              </thead>
              <tbody>
                {overview.packages.map((pkg) => (
                  <tr key={pkg.name}>
                    <td>{pkg.name}</td>
                    <td>{`${pkg.version}-${pkg.release}`}</td>
                    <td>{pkg.arch}</td>
                    <td>{pkg.install_time}</td>
                    <td>{pkg.vendor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {capabilities && (
        <section>
          <h3>后端能力</h3>
          <div className="kv-grid">
            <div className="kv-row"><span>LLM</span><strong>{capabilities.llm}</strong></div>
            <div className="kv-row"><span>检索</span><strong>{capabilities.retriever}</strong></div>
            <div className="kv-row"><span>重排</span><strong>{capabilities.reranker}</strong></div>
            <div className="kv-row"><span>向量库</span><strong>{capabilities.vector_store}</strong></div>
            <div className="kv-row"><span>缓存</span><strong>{capabilities.cache}</strong></div>
            <div className="kv-row"><span>运维后端</span><strong>{capabilities.ops_backend ?? "—"}</strong></div>
            <div className="kv-row"><span>确认存储</span><strong>{capabilities.pending_store ?? "—"}</strong></div>
            <div className="kv-row"><span>可巡检主机</span><strong>{capabilities.hosts ?? 0}</strong></div>
          </div>
          {capabilities.degraded && (
            <p className="muted">当前存在降级项（无 LLM Key / 内存向量库 / 词法重排等），答案与检索质量会下降。</p>
          )}
        </section>
      )}
    </div>
  );
}
