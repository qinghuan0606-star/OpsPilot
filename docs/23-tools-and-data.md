# 23 · 工具与数据

> 工具清单以 `GET /api/v1/ops/tools` 的 `describe()` 为准；`/api/v1/admin/tools` 保留给管理端。默认 16 个；开启写工具后 17 个。

## 1. 工具清单

| 工具 | 风险 | 参数 | 说明 |
|:---|:---|:---|:---|
| `search_knowledge` | read | `query, category?` | 检索知识库，返回可引用片段 |
| `get_system_info` | read | `host_id` | 主机 OS、内核、架构、uptime |
| `get_cpu_memory` | read | `host_id, top_n?` | CPU、内存、Load、Top 进程 |
| `get_disk_usage` | read | `host_id, paths?` | 文件系统、容量、inode |
| `get_service_status` | read | `host_id, service, manager?` | systemd/Supervisor 服务状态、退出码、重启次数、启用状态、最近失败 |
| `get_service_logs` | read | `host_id, service, lines?, since?, until?, level?, level_min?, keyword?` | journal / Supervisor 日志 |
| `get_rpm_info` | read | `host_id, package` | 包版本、状态、仓库、可用版本；未知包返回 `package_not_found` |
| `check_rpm_dependencies` | read | `host_id, package` | 缺失/冲突/满足依赖、残留文件 |
| `list_supervisor_programs` | read | `host_id` | 托管程序及状态 |
| `get_supervisor_program_config` | read | `host_id, program` | `command`、`autostart`、`autorestart`、`startsecs`、`startretries` |
| `search_elasticsearch_logs` | read | `host_id, index_pattern, service?, level?, query?, since?, until?, limit?, sort?` | ES 日志检索 |
| `aggregate_error_logs` | read | 同上 + `group_by?, interval?` | 按服务/错误类型聚合 |
| `get_logstash_pipeline_status` | read | `host_id, pipeline_id?` | Pipeline 采集/处理/输出统计与状态 |
| `escalate_to_human` | external | `reason` | 转人工流程封装 |
| `mcp_change_window` | external | `payload` | 变更窗口查询 |
| `mcp_oncall_roster` | external | `payload` | 值班表查询 |
| `restart_service` | destructive | `host_id, service, reason` | 默认不注册；必须人工确认 |

`read_only=false` 的工具不等于“已执行真实外部动作”：`escalate_to_human` 与两个 MCP 工具封装组织流程；`restart_service` 记录一次执行动作。

## 2. 统一返回与证据

`Tool.run()` 返回 `ToolResult`：

```text
{
  "tool_name": "...",
  "success": true,
  "status": "ok" | "error" | "timeout" | "fallback" | ...,
  "data": {...},
  "error": null,
  "evidence": [EvidenceItem...],
  "locator": "systemctl:nginx@lab-node-1",
  "latency_ms": 12.3
}
```

- 工具真实失败：`success=false`、`status=error/timeout`，`error` 有错误码。
- READ 工具失败且允许降级：`status=fallback`、`fallback_from` 记录原工具、`executed_tool=search_knowledge`；不会被标成“真实成功”。
- 工具证据进入统一 `evidence`，`citation.kind=tool`，`locator` 指向具体对象。
- 参数校验失败、主机越权、shell 片段在 `Tool.run()` 之前被拒绝。

## 3. 数据文件

```text
app/ops/data/
  lab-node-1.json
  lab-node-2.json
```

`lab-node-1.json` 的主要键：

| 键 | 内容 |
|:---|:---|
| `host_id` / `hostname` / `os` / `uptime` | 主机身份与系统信息 |
| `resources` | CPU、内存、Load、Top 进程 |
| `disks` / `inode_use_pct` | 磁盘与 inode |
| `packages` | RPM 包及 `requires` / `provides` / `available_versions` |
| `dependency_issues` | 按包名组织的缺失、冲突、满足、残留、仓库可用性 |
| `services` | 以服务名为键：`state`、`exit_code`、`restart_count`、`restart_events`、`unit_path`、`last_error`、`enabled` |
| `logs` | 以服务名为键的日志数组，含时间、级别、消息 |
| `supervisor.programs` | 托管程序状态、退出次数、配置 |
| `elasticsearch` | `available`、`cluster`、`endpoint`、`documents[]` |
| `logstash` | `available`、`pipelines[]` 及采集/处理/输出统计 |

## 4. 关联性约束

同一主机的数据必须能互相印证：

- `services.nginx.state=failed` ↔ `logs.nginx` 里 `libGeoIP.so.1` 缺失和 ABI 不兼容。
- `dependency_issues.nginx` ↔ `packages` 中 `nginx` 1.26.1 与 `nginx-mod-http-geoip` 1.20.1 的版本锁定。
- `supervisor.programs.app-worker` ↔ `services.app-worker` 的退出码与重启次数 ↔ `logs.app-worker` 的 `Exited too quickly`。
- `elasticsearch.documents[]` 的 `service` 字段 ↔ `services` 中的服务名；当前为 `app-api`、`app-worker`、`nginx`。
- `logstash.pipelines[]` 的 pipeline 名称与 ES 索引模式一致。

`restart_count` 不是孤立数字：`services.*.restart_events` 提供每次重启的时间、结果、退出码和原因。

## 6. 扩展方式

新增工具时：

1. 在 `app/tools/` 定义 `Input` Schema 与 `Tool` 子类，写清 `risk`、`read_only`、`requires_confirmation`。
2. 在 `app/services/container.py` 注册；写工具受 `OPS_ENABLE_WRITE_TOOLS` 控制。
3. 在 `app/ops/backend.py` 增加能力方法，数据后端读同一份 fixture。
4. 补工具级测试：成功、参数缺失、未知对象、超时、越权、证据 locator。
5. 若进入 Planner，补 `app/agents/nodes/planner.py` 的工具选择规则与场景测试。
