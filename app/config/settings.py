"""Environment-backed settings with a cached accessor."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed runtime configuration.

    Secrets stay in SecretStr so accidental str() / logs do not leak keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "testing", "production"] = "development"
    app_name: str = "ops-pilot"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    embedding_api_key: SecretStr = SecretStr("")
    embedding_base_url: str = ""
    embedding_model: str = "bge-small-zh-v1.5"
    embedding_dim: int = 512
    local_embedding_enabled: bool = True
    local_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    local_embedding_device: str = ""
    local_embedding_force: bool = False

    cross_encoder_enabled: bool = True
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    cross_encoder_device: str = ""
    cross_encoder_max_length: int = 512
    cross_encoder_force: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/local/app.db"
    redis_url: str = ""
    qdrant_url: str = ""
    qdrant_collection: str = "ops_knowledge"

    retrieval_top_k_simple: int = 3
    retrieval_top_k_complex: int = 8
    rrf_k: int = 60
    rerank_top_n: int = 5
    max_retrieval_hops: int = 3

    token_budget: int = 128_000
    compress_soft_ratio: float = 0.50
    compress_hard_ratio: float = 0.70
    auto_compact_ratio: float = 0.85

    max_agent_steps: int = 8
    max_tool_calls: int = 6

    # --- Ops tool plane ---------------------------------------------------
    # mock: read-only fixtures on isolated hosts (default, safe).
    # local: reserved for real read commands on the host running the API.
    # ssh: reserved for remote inspection; not implemented in this phase.
    ops_tool_backend: Literal["mock", "local", "ssh"] = "mock"
    ops_default_host: str = "lab-node-1"
    ops_allowed_hosts: str = "lab-node-1,lab-node-2"
    ops_fixtures_dir: str = ""
    # Write tools are opt-in. The executor also refuses them without a consumed
    # confirmation, so two independent gates must open before a restart runs.
    ops_enable_write_tools: bool = False
    tool_timeout_seconds: float = 8.0
    # A MULTI diagnosis may run one extra retrieval round after tool evidence.
    max_evidence_hops: int = 2
    # A failing diagnosis critic may request at most this many targeted
    # corrections (one retrieval or replan each) before the answer is emitted
    # with explicit evidence gaps.
    max_correction_rounds: int = 2

    # --- Confirmation store ----------------------------------------------
    # auto: Redis when REDIS_URL is set, otherwise disabled (never silent memory).
    # memory: tests only, explicitly opt-in.
    pending_store_backend: Literal["auto", "redis", "memory", "disabled"] = "auto"
    pending_action_ttl_seconds: int = 900

    rate_limit_per_minute: int = 60
    retrieval_cache_ttl_seconds: int = 60
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    admin_api_token: SecretStr = SecretStr("")
    knowledge_dir: str = "knowledge"
    unstructured_enabled: bool = True
    unstructured_strategy: str = "auto"
    unstructured_ocr_languages: str = "chi_sim+eng"
    unstructured_force: bool = False
    mcp_enabled: bool = True
    mcp_remote_url: str = ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.get_secret_value())

    @property
    def embedding_configured(self) -> bool:
        return bool(self.embedding_api_key.get_secret_value() and self.embedding_base_url)

    @property
    def local_embedding_configured(self) -> bool:
        """True when production will attempt to load the local dense model."""
        return self.local_embedding_enabled and (
            self.app_env != "testing" or self.local_embedding_force
        )

    @property
    def cross_encoder_configured(self) -> bool:
        """True when the production path will attempt to load the Cross-Encoder."""
        return self.cross_encoder_enabled and (
            self.app_env != "testing" or self.cross_encoder_force
        )

    @property
    def unstructured_configured(self) -> bool:
        """True when ingest will attempt Unstructured partition."""
        return self.unstructured_enabled and (self.app_env != "testing" or self.unstructured_force)

    @property
    def redis_configured(self) -> bool:
        return bool(self.redis_url)

    @property
    def qdrant_configured(self) -> bool:
        return bool(self.qdrant_url)

    @property
    def use_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    """Used by tests after monkeypatching environment variables."""
    get_settings.cache_clear()
