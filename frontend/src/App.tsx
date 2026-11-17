import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  Activity,
  BookOpen,
  ClipboardList,
  LayoutDashboard,
  ListTree,
  Wrench,
} from "lucide-react";
import { useEffect, useState } from "react";
import { checkHealth } from "./lib/api";
import { WorkbenchPage } from "./pages/WorkbenchPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { ToolsPage } from "./pages/ToolsPage";
import { DiagnosesPage } from "./pages/DiagnosesPage";
import { TracesPage } from "./pages/TracesPage";
import { MonitoringPage } from "./pages/MonitoringPage";

const NAV = [
  { to: "/workbench", label: "智能运维工作台", icon: LayoutDashboard },
  { to: "/knowledge", label: "知识库管理", icon: BookOpen },
  { to: "/tools", label: "运维工具管理", icon: Wrench },
  { to: "/diagnoses", label: "故障诊断记录", icon: ClipboardList },
  { to: "/traces", label: "Agent 执行记录", icon: ListTree },
  { to: "/monitoring", label: "系统监控", icon: Activity },
];

function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(() =>
    localStorage.getItem("opspilot-theme") === "dark" ? "dark" : "light",
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("opspilot-theme", theme);
  }, [theme]);

  useEffect(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal).then(setHealthy);
    return () => controller.abort();
  }, []);

  return (
    <div className="console-shell">
      <aside className="console-nav">
        <div className="brand">
          <strong>OpsPilot</strong>
          <small>智能运维平台</small>
        </div>
        <nav>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
            >
              <item.icon size={17} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="nav-footer">
          <button
            className="cancel-button"
            onClick={() => setTheme(theme === "light" ? "dark" : "light")}
          >
            {theme === "light" ? "切换深色" : "切换浅色"}
          </button>
          <span className={`connection-pill ${healthy === false ? "offline" : ""}`}>
            <span />
            {healthy === null ? "连接中" : healthy ? "后端已连接" : "后端未连接"}
          </span>
        </div>
      </aside>
      <main className="console-main">
        {healthy === false && (
          <div className="service-banner" role="status">
            <strong>暂时无法连接后端</strong>
            <span>请先启动 FastAPI 服务，再刷新本页。</span>
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/workbench" replace />} />
          <Route path="/workbench" element={<WorkbenchPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/diagnoses" element={<DiagnosesPage />} />
          <Route path="/traces" element={<TracesPage />} />
          <Route path="/monitoring" element={<MonitoringPage />} />
          <Route path="*" element={<Navigate to="/workbench" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
