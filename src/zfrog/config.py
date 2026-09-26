"""Application configuration using Pydantic Settings."""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Zfrog application settings.
    
    All settings can be overridden via environment variables or .env file.
    """
    
    model_config = SettingsConfigDict(
        env_prefix="ZFROG_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Redis configuration
    redis_url: str = "redis://localhost:6379/0"

    # Origins the dashboard is served from. "*" is fine for local use; a public
    # deployment must list its real origins, or any site can call the API with the
    # user's browser.
    cors_origins: str = "*"

    # Root for every state path below. "." keeps the historical behaviour (paths
    # relative to the working directory); a deployment points it at ONE mounted
    # volume so keys, users, sessions, versions and indexes survive a restart.
    data_dir: Path = Path(".")

    # Output configuration
    output_dir: Path = Path("output")

    # Local engine plugins (directory of *.py files, optional)
    plugins_dir: Path = Path("plugins")
    
    # Concurrency limits
    max_concurrent_jobs: int = 5
    worker_concurrency: int = 2
    
    # Proxy configuration
    proxy_url: str | None = None

    # Allow fetching private/loopback addresses. True is right for local use (you
    # clone your own machine and LAN); a public deployment sets it false so a
    # client cannot make the server read cloud metadata or scan the internal
    # network through it.
    allow_private_hosts: bool = True
    
    # HTTP client settings
    http_timeout_connect: int = 30
    http_timeout_read: int = 60
    http_max_redirects: int = 10
    
    # Wget settings
    wget_timeout: int = 300  # 5 minutes per URL
    
    # Browser pool settings
    browser_pool_size: int = 3
    browser_context_max_pages: int = 50
    browser_context_max_age_s: int = 1800  # 30 minutes

    # Probe settings
    probe_timeout: int = 15
    spa_content_threshold: int = 2048  # bytes - below this with scripts = likely SPA

    # Change detection: minimum share of changed pages that triggers a webhook
    change_alert_threshold: float = 0.1

    # Versioning (git-like history of clones)
    versions_dir: Path = Path("versions")

    # Delta crawling: cap on pages revalidated per run
    delta_max_pages: int = 200

    # Scheduling
    schedules_file: Path = Path("schedules.json")
    scheduler_interval_s: int = 30

    # Full-text / semantic search index
    search_db: Path = Path("search.db")

    # Authenticated sessions (cookies + localStorage per domain)
    sessions_dir: Path = Path("sessions")

    # Kubernetes operator
    k8s_namespace: str = "default"
    k8s_worker_image: str = "zfrog-worker:latest"
    k8s_api_server: str | None = None
    k8s_token_file: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    k8s_ca_file: Path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")

    # Session encryption at rest (key file is created 0600 on first use)
    sessions_key_file: Path = Path("sessions/.key")

    # IPFS publishing (content-addressed store -> IPFS node HTTP API)
    ipfs_enabled: bool = False
    ipfs_api_url: str = "http://127.0.0.1:5001"
    ipfs_timeout_s: int = 60

    # Cloned-content safety scan
    safety_enabled: bool = True

    # Audit log of API/CLI actions
    audit_log: Path = Path("audit.log")

    # Analytics store (per-engine outcomes)
    metrics_db: Path = Path("metrics.db")

    # Workflow DAG execution
    max_parallel_steps: int = 4

    # Content-aware change alerts
    significance_threshold: float = 0.35

    # Translation
    translation_target: str = "pt"

    # Video/stream extraction
    video_max_bytes: int = 500_000_000
    video_max_segments: int = 5000

    # Cost model (0.0 = do not report money, only resources)
    cost_per_gb_transfer: float = 0.0
    cost_per_cpu_hour: float = 0.0
    cost_per_gb_month: float = 0.0
    cost_currency: str = "BRL"

    # API authentication / RBAC
    auth_enabled: bool = False
    api_keys_file: Path = Path("api_keys.json")

    # Region-aware scheduling (edge deployment)
    region: str = "local"
    worker_regions: str = ""  # comma-separated list this scheduler may dispatch to

    # Marketplace of shared workflows/plugins
    marketplace_dir: Path = Path("marketplace")

    # Outbound integrations (Notion/Airtable/Sheets destinations)
    integrations_dir: Path = Path("integrations")

    # Identity: users, organizations and workspaces
    users_file: Path = Path("users.json")
    orgs_file: Path = Path("orgs.json")
    default_org: str = "default"

    # SSO (OpenID Connect)
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/auth/callback"
    oidc_scopes: str = "openid email profile"
    oidc_username_claim: str = "email"
    oidc_groups_claim: str = "groups"
    oidc_group_role_map: str = ""  # "admins=admin,devs=operator"

    # Dashboard login sessions, as a signed cookie (see zfrog/websession.py).
    # The signing key is created mode 0600 on first login.
    websession_key_file: Path = Path("websession.key")
    websession_ttl_s: int = 8 * 3600
    # Force the Secure flag on the cookie. Needed when TLS terminates at a proxy
    # that does not forward the original scheme.
    session_cookie_secure: bool = False
    # Where the browser lands after an SSO login.
    post_login_redirect: str = "http://localhost:3000"

    # Annotations on clones
    annotations_dir: Path = Path("annotations")

    # Domain-specialised AI profiles (prompt-level, not weight training)
    domain_profiles_dir: Path = Path("domains")

    # Search backend: "sqlite" (built in) or an HTTP service
    search_backend: str = "sqlite"
    meilisearch_url: str = "http://127.0.0.1:7700"
    meilisearch_key: str = ""
    elasticsearch_url: str = "http://127.0.0.1:9200"
    elasticsearch_index: str = "zfrog"
    elasticsearch_user: str = ""
    elasticsearch_password: str = ""

    # Worker registry and region-aware dispatch
    workers_heartbeat_ttl_s: int = 60
    worker_id: str = ""
    # Dispatch: how a scheduler hands a job to a worker, and how long to wait
    worker_api_port: int = 8000
    worker_api_scheme: str = "http"
    dispatch_timeout_s: int = 30

    # Price monitoring
    price_alert_drop_pct: float = 5.0
    price_alert_rise_pct: float = 5.0
    price_currency_hint: str = "BRL"

    # Two-factor codes for logging into your own account (RFC 6238)
    totp_digits: int = 6
    totp_period_s: int = 30

    # Fine-tuning dataset export (training itself happens elsewhere)
    finetune_dir: Path = Path("finetune")

    # Competitive / trend analysis
    analysis_dir: Path = Path("analysis")

    # Marketplace server
    marketplace_host: str = "127.0.0.1"
    marketplace_port: int = 8200

    # Permanent archiving on Arweave
    arweave_enabled: bool = False
    arweave_gateway: str = "https://arweave.net"
    arweave_wallet_file: Path = Path("arweave-wallet.json")
    arweave_timeout_s: int = 120

    # ROI: what an hour of manual work costs, to price the time saved
    roi_hourly_rate: float = 0.0
    roi_manual_minutes_per_page: float = 2.0

    @model_validator(mode="after")
    def _resolve_paths_under_data_dir(self) -> "Settings":
        """Put every relative state path under ``data_dir``.

        A deployment mounts ONE volume and sets ``ZFROG_DATA_DIR`` to it. Without
        this, each store default (``output``, ``versions``, ``api_keys.json``…)
        resolves against the working directory and lands in the container's
        writable layer — so a restart silently loses the API keys, users,
        sessions and version blobs.

        Absolute paths (the Kubernetes service-account files) are left alone, and
        ``data_dir="."`` reproduces the historical behaviour exactly.
        """
        if str(self.data_dir) in (".", ""):
            return self

        base = Path(self.data_dir)
        for name in _STATE_PATH_FIELDS:
            value = getattr(self, name, None)
            if isinstance(value, Path) and not value.is_absolute():
                setattr(self, name, base / value)
        return self


#: Every path setting that holds application state and must live on the volume.
_STATE_PATH_FIELDS: tuple[str, ...] = (
    "output_dir",
    "plugins_dir",
    "versions_dir",
    "schedules_file",
    "search_db",
    "metrics_db",
    "audit_log",
    "api_keys_file",
    "users_file",
    "orgs_file",
    "marketplace_dir",
    "integrations_dir",
    "sessions_dir",
    "sessions_key_file",
    "websession_key_file",
    "annotations_dir",
    "domain_profiles_dir",
    "finetune_dir",
    "analysis_dir",
    "arweave_wallet_file",
)


def redact_url_credentials(url: str) -> str:
    """Replace the password in a URL with a mask.

    ``settings.redis_url`` routinely carries the broker's password
    (``redis://:secret@host:6379/0``) and the dashboard displays it as
    information. The host and port are useful there; the password is a leak, and
    `GET /config` only needs `read:jobs`.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"

    if not parts.password:
        return url

    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"

    userinfo = f"{parts.username or ''}:********@"
    return urlunsplit((parts.scheme, f"{userinfo}{host}", parts.path, parts.query, parts.fragment))


# Global settings instance
settings = Settings()
