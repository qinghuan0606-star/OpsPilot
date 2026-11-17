import { useEffect, useState } from "react";
import { getKnowledgeDocument, getKnowledgeDocuments } from "../lib/api";
import type { KnowledgeDetail, KnowledgeDocument } from "../types";

const SOURCE_LABELS: Record<string, string> = {
  self_written: "自写整理",
  public_summary: "公开资料摘要",
  upstream_manual_excerpt: "上游手册节选",
};

const SYSTEM_LABELS: Record<string, string> = {
  linux_generic: "Linux 通用",
  openeuler: "openEuler",
  kylin_v10: "麒麟 V10",
  openeuler_kylin_v10: "openEuler / 麒麟 V10 共同",
};

const FORMAT_LABELS: Record<string, string> = {
  runbook: "完整 Runbook",
  quick_reference: "速查卡",
};

const CATEGORY_LABELS: Record<string, string> = {
  linux_basics: "Linux 基础",
  domestic_os: "国产操作系统",
  rpm_package: "RPM 软件包",
  service_mgmt: "服务管理",
  log_fault: "日志与故障案例",
  network_disk: "网络与磁盘",
  security_perm: "安全与权限",
};

export function KnowledgePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<KnowledgeDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getKnowledgeDocuments(controller.signal)
      .then((payload) => setDocuments(payload.documents))
      .catch((exc: unknown) => setError(exc instanceof Error ? exc.message : "加载失败"))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function openDocument(doc: KnowledgeDocument) {
    setDetailError(null);
    setDetailLoading(true);
    try {
      const payload = await getKnowledgeDocument(doc.document_id);
      setSelected(payload);
      if (!payload.found) setDetailError("清单中存在该文档，但检索索引未返回对应切片。");
    } catch (exc: unknown) {
      setDetailError(exc instanceof Error ? exc.message : "详情加载失败");
    } finally {
      setDetailLoading(false);
    }
  }

  const visible = documents.filter((doc) =>
    filter
      ? `${doc.title}${doc.document_id}${doc.category}${doc.system}${doc.source_type}${doc.source_note}`.includes(filter)
      : true,
  );
  const categories = new Set(documents.map((doc) => doc.category));

  return (
    <div className="page">
      <header className="page-header">
        <h2>知识库管理</h2>
        <p>
          共 {documents.length} 篇文档，覆盖 {categories.size} 个运维域。来源类型与适用版本由
          <code>knowledge/_manifest.json</code> 给出，不标注任何厂商内部文档。
        </p>
      </header>
      {error && (
        <div className="service-banner" role="status">
          <strong>知识库清单不可用</strong>
          <span>{error}</span>
        </div>
      )}
      {loading && !error && <p className="muted">正在加载知识文档清单…</p>}
      <input
        className="filter-input"
        placeholder="按标题 / 分类 / 系统 / 来源筛选"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />
      {!loading && !error && visible.length === 0 && (
        <p className="muted">没有匹配的文档，请调整筛选条件。</p>
      )}
      <table className="data-table clickable">
        <thead>
          <tr>
            <th>文档</th>
            <th>分类</th>
            <th>系统</th>
            <th>格式</th>
            <th>切片</th>
            <th>更新</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((doc) => (
            <tr key={doc.document_id} onClick={() => void openDocument(doc)}>
              <td>
                <strong>{doc.title}</strong>
                <span className="muted block">{doc.document_id}</span>
              </td>
              <td>{CATEGORY_LABELS[doc.category] ?? doc.category}</td>
              <td>{SYSTEM_LABELS[doc.system] ?? doc.system}</td>
              <td>{FORMAT_LABELS[doc.doc_format] ?? doc.doc_format}</td>
              <td>{doc.chunk_count}</td>
              <td>{doc.updated_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {detailLoading && <p className="muted">正在读取文档详情与切片…</p>}
      {detailError && <p className="muted warn">{detailError}</p>}
      {selected?.found && selected.document && (
        <section className="detail-panel">
          <header>
            <div>
              <h3>{selected.document.title}</h3>
              <code className="trace-id">{selected.document.document_id}</code>
            </div>
            <button className="cancel-button" onClick={() => setSelected(null)}>关闭</button>
          </header>
          <div className="kv-grid">
            <div className="kv-row"><span>知识域</span><strong>{CATEGORY_LABELS[selected.document.category] ?? selected.document.category}</strong></div>
            <div className="kv-row"><span>来源类型</span><strong>{SOURCE_LABELS[selected.document.source_type] ?? selected.document.source_type}</strong></div>
            <div className="kv-row"><span>适用系统</span><strong>{SYSTEM_LABELS[selected.document.system] ?? selected.document.system}</strong></div>
            <div className="kv-row"><span>适用版本</span><strong>{selected.document.applicable_version}</strong></div>
            <div className="kv-row"><span>文档格式</span><strong>{FORMAT_LABELS[selected.document.doc_format] ?? selected.document.doc_format}</strong></div>
            <div className="kv-row"><span>更新时间</span><strong>{selected.document.updated_at}</strong></div>
            <div className="kv-row"><span>切片数量</span><strong>{selected.document.chunk_count}</strong></div>
          </div>
          <div className="kv-row"><span>来源说明</span><strong>{selected.document.source_note}</strong></div>
          {selected.document.source_url && (
            <p className="evidence-locator">公开资料入口：{selected.document.source_url}</p>
          )}
          <h4>已入库切片</h4>
          {(selected.chunks ?? []).length === 0 ? (
            <p className="muted">检索索引中没有该文档的切片。</p>
          ) : (
            <ol className="chunk-list">
              {(selected.chunks ?? []).map((chunk) => (
                <li key={chunk.chunk_id}>
                  <strong>{chunk.section || "正文"} · {chunk.chunk_id}</strong>
                  <p>{chunk.content.slice(0, 380)}{chunk.content.length > 380 ? "…" : ""}</p>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      <p className="muted">
        说明：当前知识库以 Markdown 文件为源，页面尚未提供上传/删除接口；切片数量来自当前 BM25 检索索引，
        详情只展示已入库内容，不代表重新解析成功。
      </p>
    </div>
  );
}
