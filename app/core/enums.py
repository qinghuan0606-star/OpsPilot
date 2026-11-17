"""Domain enums for OpsPilot: intent, complexity, strategy, package/service state and risk."""

from enum import Enum


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class IntentLabel(str, Enum):
    """Ops-oriented intents. Every label maps to exactly one ops sub-domain."""

    GREETING = "greeting"
    CHITCHAT = "chitchat"
    LINUX_BASICS = "linux_basics"
    OS_CONFIG = "os_config"
    NETWORK_DISK = "network_disk"
    PACKAGE_RPM = "package_rpm"
    SERVICE_OPS = "service_ops"
    LOG_ANALYSIS = "log_analysis"
    RESOURCE_CHECK = "resource_check"
    SECURITY_PERM = "security_perm"
    FAULT_DIAGNOSIS = "fault_diagnosis"
    HUMAN_HANDOFF = "human_handoff"
    OUT_OF_SCOPE = "out_of_scope"


class RetrievalStrategy(str, Enum):
    """Adaptive-RAG routing targets.

    DIRECT: parametric / greeting answers, no retrieval.
    SINGLE: one-shot hybrid retrieval.
    MULTI: Self-RAG iterative retrieval for multi-hop questions, may escalate to tools.
    AGENT: planner + ops tools, optionally with retrieval.
    REFUSE: boundary / dangerous-operation refusal.
    """

    DIRECT = "direct"
    SINGLE = "single"
    MULTI = "multi"
    AGENT = "agent"
    REFUSE = "refuse"


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    SINGLE_HOP = "single_hop"
    MULTI_HOP = "multi_hop"
    TOOL_REQUIRED = "tool_required"
    OUT_OF_SCOPE = "out_of_scope"


class PackageState(str, Enum):
    INSTALLED = "installed"
    UPGRADING = "upgrading"
    BROKEN = "broken"
    MISSING = "missing"
    CONFLICT = "conflict"


class ServiceState(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"
    ACTIVATING = "activating"
    UNKNOWN = "unknown"


class ToolRisk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"


class ToolExecutionStatus(str, Enum):
    """How a tool step actually ended.

    ``success`` on the trace is true only for ``ok``; a fallback is a failed
    original call with a different tool producing the evidence.
    """

    OK = "ok"
    FAILED = "failed"
    FALLBACK = "fallback"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"
    TIMEOUT = "timeout"
    INVALID_ARGUMENTS = "invalid_arguments"


class CompressionLevel(str, Enum):
    NONE = "none"
    SOFT_TRUNCATE = "soft_truncate"
    HARD_COMPRESS = "hard_compress"
    AUTO_COMPACT = "auto_compact"


class DocumentCategory(str, Enum):
    """Seven ops knowledge domains required by the migration brief."""

    LINUX_BASICS = "linux_basics"
    DOMESTIC_OS = "domestic_os"
    RPM_PACKAGE = "rpm_package"
    SERVICE_MGMT = "service_mgmt"
    LOG_FAULT = "log_fault"
    NETWORK_DISK = "network_disk"
    SECURITY_PERM = "security_perm"
