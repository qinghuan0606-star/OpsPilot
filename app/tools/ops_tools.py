"""Read-only and confirmable ops tools.

Every tool answers through a capability on the backend. There is no argument
that accepts a shell string, so the planner cannot turn a model hallucination
into a command. Each result carries an `evidence` block that the executor turns
into a citable :class:`EvidenceItem`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.config.settings import Settings
from app.core.enums import ToolRisk
from app.core.exceptions import (
    AppError,
    InvalidRequestError,
    PackageNotFoundError,
    ServiceNotFoundError,
    ToolPermissionError,
)
from app.ops.backend import OpsBackend, OpsNotFound
from app.ops.hosts import HostProfile, HostRegistry
from app.schemas.agent import ToolResult
from app.tools.base import Tool, ToolContext


class OpsTool(Tool):
    """Shared base: resolve the target host, time the backend call, normalise errors."""

    def __init__(
        self,
        backend: OpsBackend,
        hosts: HostRegistry,
        settings: Settings,
    ) -> None:
        self._backend = backend
        self._hosts = hosts
        self._settings = settings

    def _resolve(self, host_id: str | None) -> HostProfile:
        return self._hosts.resolve(host_id, default=self._settings.ops_default_host)

    def _expected_host(self, context: ToolContext, requested: str | None) -> str:
        """Bind the call to the host chosen for this turn.

        A plan step cannot silently retarget a different machine than the one
        the router authorised for the turn.
        """
        if context.host_id and requested and requested != context.host_id:
            raise ToolPermissionError(
                f"tool call targets {requested} but this turn is scoped to {context.host_id}"
            )
        return requested or context.host_id or self._settings.ops_default_host

    async def _call(self, coro: Any, *, kind: str) -> dict[str, Any]:
        try:
            return await coro
        except OpsNotFound as exc:
            message = str(exc)
            if kind == "package":
                raise PackageNotFoundError(message) from exc
            if kind == "service":
                raise ServiceNotFoundError(message) from exc
            raise InvalidRequestError(message) from exc
        except AppError:
            raise
        except Exception as exc:
            raise InvalidRequestError(f"backend rejected the request: {exc}") from exc


class _HostArg(BaseModel):
    host_id: str | None = Field(
        default=None,
        max_length=64,
        description="目标主机 ID，如 lab-node-1；省略时使用本次请求默认主机。不要填 IP 或主机名之外的任何内容",
    )


def _validate_timestamp(value: str | None) -> str | None:
    if not value:
        return value
    if any(ch in value for ch in (";", "|", "&", "$", "`", ">", "<", "\n")):
        raise ValueError("time filter must be an ISO timestamp, not a shell fragment")
    try:
        datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("time filter must be ISO-8601, e.g. 2026-11-16T09:00:00+08:00") from exc
    return value


_ALLOWED_LEVELS = {
    "emerg",
    "emergency",
    "alert",
    "crit",
    "critical",
    "err",
    "error",
    "warn",
    "warning",
    "notice",
    "info",
    "debug",
    "fatal",
}


def _validate_level(value: str | None) -> str | None:
    if not value:
        return value
    lowered = value.strip().lower()
    if lowered not in _ALLOWED_LEVELS:
        raise ValueError(f"level must be one of {sorted(_ALLOWED_LEVELS)}")
    return value


def _plain_identifier(value: str) -> str:
    name = value.strip()
    if not name or any(ch in name for ch in (" ", "/", ";", "|", "&", "$", "`", ">", "<", "*")):
        raise ValueError("value must be a plain identifier, not a path or shell fragment")
    return name


class GetSystemInfoInput(_HostArg):
    pass


class GetSystemInfoTool(OpsTool):
    name = "get_system_info"
    description = (
        "查询目标主机的操作系统名称、版本、内核版本与架构（只读）。"
        "何时用：系统版本、内核版本、发行版、架构、是否国产操作系统；日志/服务分析前的环境确认。"
        "何时不用：CPU/内存用 get_cpu_memory；磁盘用 get_disk_usage；服务状态用 get_service_status。"
        "参数 host_id：可选，目标主机 ID；省略则用默认主机。"
        "返回 os_name/os_version/kernel/arch/vendor 结构化字段，附 evidence 定位信息。"
    )
    risk = ToolRisk.READ
    input_model = GetSystemInfoInput

    async def execute(self, parsed: GetSystemInfoInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(self._backend.system_info(host.host_id), kind="host")
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class GetCpuMemoryInput(_HostArg):
    top_n: int = Field(default=5, ge=1, le=20, description="返回资源占用最高的进程条数")


class GetCpuMemoryTool(OpsTool):
    name = "get_cpu_memory"
    description = (
        "查询目标主机的 CPU 负载、使用率与内存/swap 占用，并可返回 TOP 进程（只读）。"
        "何时用：CPU 高、内存不足、负载飙升、OOM、卡顿、找出占用最高的进程。"
        "何时不用：磁盘空间用 get_disk_usage；服务为什么起不来用 get_service_status + get_service_logs。"
        "参数 host_id 可选；top_n 默认 5（1–20）。"
        "返回 cpu{load_1/5/15,usage_pct,cores}、memory{total_kb,available_kb,usage_pct}、top_processes[]。"
    )
    risk = ToolRisk.READ
    input_model = GetCpuMemoryInput

    async def execute(self, parsed: GetCpuMemoryInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(self._backend.cpu_memory(host.host_id, parsed.top_n), kind="host")
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class GetDiskUsageInput(_HostArg):
    paths: list[str] | None = Field(
        default=None,
        max_length=5,
        description='可选，限定挂载点前缀列表，如 ["/", "/var"]；只接受挂载点，不接受命令',
    )

    @field_validator("paths")
    @classmethod
    def _no_shell_metachars(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return value
        for item in value:
            if any(ch in item for ch in (";", "|", "&", "$", "`", ">", "<", "\n")):
                raise ValueError("paths must be plain mount points, not shell fragments")
        return value


class GetDiskUsageTool(OpsTool):
    name = "get_disk_usage"
    description = (
        "查询目标主机的文件系统使用率、可用空间与 inode 使用率（只读）。"
        "何时用：磁盘满、/var 或 / 使用率高、写入失败疑似空间不足、inode 耗尽。"
        "何时不用：内存不足用 get_cpu_memory；日志体积分析用 get_service_logs。"
        "参数 host_id 可选；paths 可选挂载点前缀，最多 5 个。"
        "返回 filesystems[{mount,fs_type,size_kb,used_kb,avail_kb,use_pct}] 与 inode_use_pct。"
    )
    risk = ToolRisk.READ
    input_model = GetDiskUsageInput

    async def execute(self, parsed: GetDiskUsageInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(self._backend.disk_usage(host.host_id, parsed.paths), kind="host")
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class GetServiceStatusInput(_HostArg):
    service: str = Field(
        min_length=2,
        max_length=64,
        description="服务名，如 nginx、sshd、docker、app-worker；不要填 .service 后缀以外的东西",
    )
    manager: Literal["systemd", "supervisor"] | None = Field(
        default=None, description="服务管理器；省略时按主机记录自动判定"
    )

    @field_validator("service")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        name = value.strip()
        if name.endswith(".service"):
            name = name[: -len(".service")]
        if any(ch in name for ch in (" ", "/", ";", "|", "&", "$", "`", ">", "<")):
            raise ValueError("service must be a plain unit name such as nginx")
        return name


class GetServiceStatusTool(OpsTool):
    name = "get_service_status"
    description = (
        "查询 systemd 或 supervisor 管理服务的运行状态（只读）：active/failed/inactive、"
        "是否启用、PID、退出码、重启次数、最近失败时间、停止原因、unit 配置/启动参数。"
        "何时用：服务起不来、nginx 启动失败、进程不见了、服务是否在跑、退出码是什么、"
        "是否开机自启、Supervisor 托管程序状态。"
        "何时不用：具体报错日志用 get_service_logs；程序启动/重启策略用 get_supervisor_program_config。"
        "参数 service 必填（如 nginx、app-worker）；manager 可选 systemd|supervisor。"
        "返回 state/enabled/since/last_start_at/last_failure_at/pid/exit_code/restart_count/"
        "restart_events/unit_path/last_error/stop_reason/exec_start/restart_policy/unit_config。"
    )
    risk = ToolRisk.READ
    input_model = GetServiceStatusInput

    async def execute(self, parsed: GetServiceStatusInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.service_status(host.host_id, parsed.service, parsed.manager),
            kind="service",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class GetServiceLogsInput(_HostArg):
    service: str = Field(min_length=2, max_length=64, description="服务名，如 nginx、app-worker")
    lines: int = Field(default=50, ge=1, le=500, description="返回最近多少行，最多 500")
    since: str | None = Field(
        default=None,
        max_length=40,
        description="起始时间（含），ISO 时间，如 2026-11-16T09:00:00+08:00",
    )
    until: str | None = Field(
        default=None,
        max_length=40,
        description="结束时间（含），ISO 时间；不填表示到现在",
    )
    level: str | None = Field(
        default=None,
        max_length=16,
        description="精确级别过滤，支持 emerg/alert/crit/err/warn/notice/info/debug；error 等价 err",
    )
    level_min: str | None = Field(
        default=None,
        max_length=16,
        description="最低级别过滤，如 err 表示只看 err 及以上；与 level 同时使用时两者都要满足",
    )
    keyword: str | None = Field(
        default=None,
        max_length=120,
        description="在日志正文/unit/error_type 中做不区分大小写的关键词过滤",
    )

    @field_validator("service")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        name = value.strip()
        if name.endswith(".service"):
            name = name[: -len(".service")]
        if any(ch in name for ch in (" ", "/", ";", "|", "&", "$", "`", ">", "<")):
            raise ValueError("service must be a plain unit or program name such as nginx")
        return name

    @field_validator("since", "until")
    @classmethod
    def _plain_time(cls, value: str | None) -> str | None:
        return _validate_timestamp(value)

    @field_validator("keyword")
    @classmethod
    def _plain_keyword(cls, value: str | None) -> str | None:
        if value and any(ch in value for ch in (";", "|", "&", "$", "`", ">", "<", "\n")):
            raise ValueError("keyword must be plain text, not a shell fragment")
        return value

    @field_validator("level", "level_min")
    @classmethod
    def _level(cls, value: str | None) -> str | None:
        return _validate_level(value)


class GetServiceLogsTool(OpsTool):
    name = "get_service_logs"
    description = (
        "读取目标主机上某个 systemd 服务或 Supervisor 程序的日志尾部（只读，最多 500 行）。"
        "何时用：服务启动失败要看报错、Error/emerg 行、退出前最后几行、依赖库缺失或模块加载失败、"
        "按时间范围/级别/关键词过滤单服务日志。"
        "何时不用：只要状态用 get_service_status；跨服务或 Elasticsearch 日志检索用 "
        "search_elasticsearch_logs；错误聚合用 aggregate_error_logs。"
        "参数 service 必填；lines 默认 50（1–500）；since/until 可选 ISO 时间；"
        "level 精确级别；level_min 最低级别；keyword 关键词。"
        "返回 entries[{ts,level,unit,pid,msg,error_type}]、filters、source 与 truncated 标记。"
    )
    risk = ToolRisk.READ
    input_model = GetServiceLogsInput

    async def execute(self, parsed: GetServiceLogsInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.service_logs(
                host.host_id,
                parsed.service,
                parsed.lines,
                parsed.since,
                parsed.until,
                parsed.level,
                parsed.level_min,
                parsed.keyword,
            ),
            kind="service",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class GetRpmInfoInput(_HostArg):
    package: str = Field(
        min_length=2, max_length=64, description="RPM 包名，如 nginx；不要带版本号或路径"
    )

    @field_validator("package")
    @classmethod
    def _plain_package(cls, value: str) -> str:
        name = value.strip()
        if any(ch in name for ch in (" ", "/", ";", "|", "&", "$", "`", ">", "<", "*")):
            raise ValueError("package must be a plain rpm package name such as nginx")
        return name


class GetRpmInfoTool(OpsTool):
    name = "get_rpm_info"
    description = (
        "查询目标主机上某个 RPM 包的版本、发行号、安装时间、许可证、来源仓库与 requires/provides（只读）。"
        "何时用：包版本是什么、升级到哪个版本、装没装、依赖声明、vendor、repo。"
        "何时不用：依赖是否满足/冲突用 check_rpm_dependencies；服务起不来先看 get_service_status。"
        "参数 package 必填（如 nginx）。"
        "返回 name/epoch/version/release/arch/state/repo_id/repo_url/available_versions/install_time/requires[]/provides[]。"
    )
    risk = ToolRisk.READ
    input_model = GetRpmInfoInput

    async def execute(self, parsed: GetRpmInfoInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.rpm_info(host.host_id, parsed.package), kind="package"
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class CheckRpmDependenciesInput(_HostArg):
    package: str = Field(
        min_length=2, max_length=64, description="RPM 包名，如 nginx；不要带版本号或路径"
    )

    @field_validator("package")
    @classmethod
    def _plain_package(cls, value: str) -> str:
        name = value.strip()
        if any(ch in name for ch in (" ", "/", ";", "|", "&", "$", "`", ">", "<", "*")):
            raise ValueError("package must be a plain rpm package name such as nginx")
        return name


class CheckRpmDependenciesTool(OpsTool):
    name = "check_rpm_dependencies"
    description = (
        "检查某个 RPM 包的依赖是否满足、是否有冲突或残留模块文件（只读）。"
        "何时用：升级后起不来、疑似依赖冲突、缺 .so、模块不兼容、同系列包版本不匹配。"
        "何时不用：只看版本用 get_rpm_info；看服务报错用 get_service_logs。"
        "参数 package 必填。包不存在时返回结构化 PACKAGE_NOT_FOUND，不返回成功空结果。"
        "返回 package_state/missing[]/conflicts[]/satisfied[]/broken_by[]/stale_files[]/repo_available/note。"
    )
    risk = ToolRisk.READ
    input_model = CheckRpmDependenciesInput

    async def execute(self, parsed: CheckRpmDependenciesInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.rpm_dependencies(host.host_id, parsed.package), kind="package"
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class SearchElasticsearchLogsInput(_HostArg):
    index_pattern: str = Field(
        default="app-logs-*",
        max_length=100,
        description="Elasticsearch 索引模式，支持 *，如 app-logs-*；只接受索引名，不接受查询语句",
    )
    service: str | None = Field(
        default=None, max_length=64, description="服务名过滤，如 nginx；省略表示所有服务"
    )
    level: str | None = Field(
        default=None,
        max_length=16,
        description="日志级别过滤，支持 ERROR/WARN/INFO 或 err、warn；省略表示所有级别",
    )
    query: str | None = Field(
        default=None, max_length=200, description="正文/error_type/trace_id 关键词，不区分大小写"
    )
    since: str | None = Field(default=None, max_length=40, description="起始时间（含），ISO-8601")
    until: str | None = Field(default=None, max_length=40, description="结束时间（含），ISO-8601")
    limit: int = Field(default=100, ge=1, le=500, description="最多返回多少条，最大 500")
    sort: Literal["asc", "desc"] = Field(default="desc", description="按时间升序或降序")

    @field_validator("index_pattern")
    @classmethod
    def _plain_index(cls, value: str) -> str:
        pattern = value.strip()
        if not pattern or any(
            ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789*._-"
            for ch in pattern
        ):
            raise ValueError("index_pattern must be an index name/pattern, not a query")
        return pattern

    @field_validator("service")
    @classmethod
    def _plain_service(cls, value: str | None) -> str | None:
        return _plain_identifier(value) if value else value

    @field_validator("query")
    @classmethod
    def _plain_query(cls, value: str | None) -> str | None:
        if value and any(ch in value for ch in (";", "|", "&", "$", "`", ">", "<", "\n")):
            raise ValueError("query must be a literal keyword, not a query/shell fragment")
        return value

    @field_validator("level")
    @classmethod
    def _level(cls, value: str | None) -> str | None:
        return _validate_level(value)

    @field_validator("since", "until")
    @classmethod
    def _plain_time(cls, value: str | None) -> str | None:
        return _validate_timestamp(value)


class SearchElasticsearchLogsTool(OpsTool):
    name = "search_elasticsearch_logs"
    description = (
        "在目标主机的 Elasticsearch 索引中检索日志（只读），不是本地 journal。"
        "何时用：用户明确提到 Elasticsearch/ES、跨服务或跨时间检索日志、按 ERROR/级别、"
        "服务名、关键词查日志；应用日志量大、需要命中数和原始记录。"
        "何时不用：只查单个 systemd/Supervisor 服务尾部用 get_service_logs；"
        "错误次数/高频统计用 aggregate_error_logs；采集管道状态用 get_logstash_pipeline_status。"
        "参数 index_pattern 默认 app-logs-*；service/level/query/since/until 可选；limit 1–500。"
        "返回 total/entries[{index,timestamp,service,level,message,error_type,trace_id}]/matched_indices。"
    )
    risk = ToolRisk.READ
    input_model = SearchElasticsearchLogsInput

    async def execute(
        self, parsed: SearchElasticsearchLogsInput, context: ToolContext
    ) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.elasticsearch_logs(
                host.host_id,
                index_pattern=parsed.index_pattern,
                service=parsed.service,
                level=parsed.level,
                query=parsed.query,
                since=parsed.since,
                until=parsed.until,
                limit=parsed.limit,
                sort=parsed.sort,
            ),
            kind="host",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class AggregateErrorLogsInput(SearchElasticsearchLogsInput):
    # The inherited sort field stays in the schema for a uniform filter object;
    # aggregation output is always ordered by count desc, never by raw time.
    sort: Literal["desc"] = Field(default="desc", description="聚合结果按错误次数降序")
    group_by: Literal["service", "error_type", "level", "message_fingerprint", "time_bucket"] = (
        Field(default="error_type", description="聚合维度：服务、错误类型、级别、消息指纹或时间桶")
    )
    interval: Literal["1m", "5m", "1h", "1d"] = Field(
        default="5m", description="time_bucket 聚合的时间桶大小"
    )
    limit: int = Field(default=20, ge=1, le=100, description="最多返回多少个聚合桶")


class AggregateErrorLogsTool(OpsTool):
    name = "aggregate_error_logs"
    description = (
        "在 Elasticsearch 中按服务、错误类型、级别、消息指纹或时间桶聚合 ERROR 日志（只读）。"
        "何时用：大量 ERROR、高频异常、按服务/错误类型统计、需要错误次数与典型消息。"
        "何时不用：只需要原始日志明细用 search_elasticsearch_logs；本地单服务日志用 get_service_logs。"
        "参数过滤条件同 search_elasticsearch_logs；group_by 默认 error_type；interval 支持 1m/5m/1h/1d。"
        "返回 total_errors/buckets[{key,count,first_ts,last_ts,sample_message,services,error_types}]。"
    )
    risk = ToolRisk.READ
    input_model = AggregateErrorLogsInput

    async def execute(self, parsed: AggregateErrorLogsInput, context: ToolContext) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.aggregate_error_logs(
                host.host_id,
                index_pattern=parsed.index_pattern,
                service=parsed.service,
                level=parsed.level or "ERROR",
                query=parsed.query,
                since=parsed.since,
                until=parsed.until,
                group_by=parsed.group_by,
                interval=parsed.interval,
                limit=parsed.limit,
            ),
            kind="host",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class LogstashPipelineStatusInput(_HostArg):
    pipeline_id: str | None = Field(
        default=None, max_length=64, description="Logstash pipeline ID，省略表示返回全部"
    )

    @field_validator("pipeline_id")
    @classmethod
    def _plain_pipeline(cls, value: str | None) -> str | None:
        return _plain_identifier(value) if value else value


class GetLogstashPipelineStatusTool(OpsTool):
    name = "get_logstash_pipeline_status"
    description = (
        "查询目标主机 Logstash pipeline 的采集/处理/输出状态（只读）。"
        "何时用：日志没有进 Elasticsearch、采集延迟、pipeline 报错、队列堆积、workers/events 统计。"
        "何时不用：日志内容检索用 search_elasticsearch_logs；错误聚合用 aggregate_error_logs；"
        "Kibana 只是可视化层，不作为日志证据来源。"
        "参数 host_id 可选；pipeline_id 可选。"
        "返回 pipelines[{pipeline_id,state,workers,events_in,events_out,queue_events,last_error}] 与 summary。"
    )
    risk = ToolRisk.READ
    input_model = LogstashPipelineStatusInput

    async def execute(
        self, parsed: LogstashPipelineStatusInput, context: ToolContext
    ) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.logstash_pipeline_status(host.host_id, parsed.pipeline_id),
            kind="host",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class ListSupervisorProgramsInput(_HostArg):
    pass


class ListSupervisorProgramsTool(OpsTool):
    name = "list_supervisor_programs"
    description = (
        "列出目标主机上 Supervisor 托管的所有程序及运行状态（只读），不是 systemctl。"
        "何时用：不知道 supervisor 管了哪些程序、需要程序清单、先定位 app-worker 等程序。"
        "何时不用：查单个程序配置用 get_supervisor_program_config；查状态/日志用 get_service_status/"
        "get_service_logs；systemd 服务列表不在本工具范围。"
        "参数 host_id 可选。返回 programs[{program,service,state,pid,exit_code,restart_count,"
        "autostart,autorestart,startsecs,startretries,config_path}] 与 total。"
    )
    risk = ToolRisk.READ
    input_model = ListSupervisorProgramsInput

    async def execute(
        self, parsed: ListSupervisorProgramsInput, context: ToolContext
    ) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(self._backend.supervisor_programs(host.host_id), kind="host")
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class SupervisorProgramConfigInput(_HostArg):
    program: str = Field(
        min_length=2, max_length=64, description="Supervisor 托管程序名，如 app-worker"
    )

    @field_validator("program")
    @classmethod
    def _plain_program(cls, value: str) -> str:
        name = value.strip().removesuffix(".ini")
        return _plain_identifier(name)


class GetSupervisorProgramConfigTool(OpsTool):
    name = "get_supervisor_program_config"
    description = (
        "读取目标主机上某个 Supervisor 程序的 command、autostart、autorestart、startsecs、"
        "startretries、stopwaitsecs 等启动/重启配置（只读）。"
        "何时用：程序频繁退出、判断是应用自身崩溃还是 Supervisor 重启策略配置问题、"
        "确认启动命令/等待时间/重试次数。"
        "何时不用：只要运行状态用 get_service_status；日志用 get_service_logs；"
        "需要程序清单用 list_supervisor_programs。"
        "参数 program 必填（如 app-worker）。返回结构化 config、state、restart_count、restart_events。"
    )
    risk = ToolRisk.READ
    input_model = SupervisorProgramConfigInput

    async def execute(
        self, parsed: SupervisorProgramConfigInput, context: ToolContext
    ) -> ToolResult:
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.supervisor_program_config(host.host_id, parsed.program),
            kind="service",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


class RestartServiceInput(_HostArg):
    service: str = Field(min_length=2, max_length=64, description="要重启的服务名，如 nginx")
    reason: str = Field(
        min_length=4,
        max_length=200,
        description="重启原因，写清触发场景，如「升级后启动失败，验证修复」",
    )


class RestartServiceTool(OpsTool):
    name = "restart_service"
    description = (
        "重启目标主机上的服务（写操作，必须先由人工确认；本阶段仅在 mock 后端模拟执行）。"
        "何时用：用户明确要求重启，且已确认服务名与原因。"
        "何时不用：只是排查原因时不要重启；不确定服务名时先用 get_service_status。"
        "参数 service 必填；reason 必填，说明为什么重启。"
        "返回 restart_attempted 与 simulated=true；mock 后端不会真正重启任何进程。"
    )
    risk = ToolRisk.DESTRUCTIVE
    input_model = RestartServiceInput

    async def execute(self, parsed: RestartServiceInput, context: ToolContext) -> ToolResult:
        if not self._settings.ops_enable_write_tools:
            raise ToolPermissionError("write tools are disabled by configuration")
        host = self._resolve(self._expected_host(context, parsed.host_id))
        output = await self._call(
            self._backend.restart_service(
                host.host_id, parsed.service, parsed.reason, context.user_id
            ),
            kind="service",
        )
        return ToolResult(name=self.name, success=True, output=output, risk=self.risk)


__all__ = [
    "CheckRpmDependenciesTool",
    "GetCpuMemoryTool",
    "GetDiskUsageTool",
    "GetRpmInfoTool",
    "GetServiceLogsTool",
    "GetServiceStatusTool",
    "GetSystemInfoTool",
    "OpsTool",
    "RestartServiceTool",
]
