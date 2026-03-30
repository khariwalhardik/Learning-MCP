import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from core.oauth_provider import InMemoryOAuthProvider
from tools.testing import register_testing_tools
from tools.file_manager import register_file_manager_tools
from tools.obsidian import register_obsidian_tools

load_dotenv()

HOST = os.getenv("MCP_HOST", "0.0.0.0")
PORT = int(os.getenv("MCP_PORT", "8000"))
APP_LOG_LEVEL = os.getenv("APP_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, APP_LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("mcp_server")


class StaticBearerTokenVerifier(TokenVerifier):
    def __init__(self, token: str, scopes: list[str] | None = None):
        self._token = token
        self._scopes = scopes or ["mcp:access"]

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != self._token:
            return None
        return AccessToken(
            token=token,
            client_id="static-client",
            scopes=self._scopes,
        )


def log_event(event: str, **data) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "data": data,
    }
    logger.info(json.dumps(payload, ensure_ascii=True))


AUTH_BEARER_TOKEN = os.getenv("MCP_AUTH_BEARER_TOKEN", "").strip()
AUTH_ISSUER_URL = os.getenv("MCP_AUTH_ISSUER_URL", "").strip()
AUTH_RESOURCE_SERVER_URL = os.getenv("MCP_AUTH_RESOURCE_SERVER_URL", "").strip()
AUTH_REQUIRED_SCOPES = [
    scope.strip() for scope in os.getenv("MCP_AUTH_REQUIRED_SCOPES", "mcp:access").split(",") if scope.strip()
]

OAUTH_ENABLED = os.getenv("MCP_OAUTH_ENABLED", "0").strip() in {"1", "true", "yes", "on"}
OAUTH_CLIENT_ID = os.getenv("MCP_OAUTH_CLIENT_ID", "nexus-claude-client").strip()
OAUTH_CLIENT_SECRET = os.getenv("MCP_OAUTH_CLIENT_SECRET", "").strip()
OAUTH_ALLOWED_REDIRECT_HOSTS = [
    host.strip() for host in os.getenv("MCP_OAUTH_ALLOWED_REDIRECT_HOSTS", "claude.ai").split(",") if host.strip()
]
OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION = os.getenv(
    "MCP_OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION", "0"
).strip() in {"1", "true", "yes", "on"}
OAUTH_AUTH_CODE_TTL_SECONDS = int(os.getenv("MCP_OAUTH_AUTH_CODE_TTL_SECONDS", "300"))
OAUTH_ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS", "3600"))
OAUTH_REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("MCP_OAUTH_REFRESH_TOKEN_TTL_SECONDS", "2592000"))

auth_settings = None
token_verifier = None
auth_server_provider = None

if OAUTH_ENABLED:
    if not AUTH_ISSUER_URL or not AUTH_RESOURCE_SERVER_URL:
        raise ValueError(
            "When MCP_OAUTH_ENABLED is true, MCP_AUTH_ISSUER_URL and "
            "MCP_AUTH_RESOURCE_SERVER_URL must be set"
        )
    if not OAUTH_CLIENT_SECRET:
        raise ValueError(
            "When MCP_OAUTH_ENABLED is true, MCP_OAUTH_CLIENT_SECRET must be set"
        )

    auth_settings = AuthSettings(
        issuer_url=AUTH_ISSUER_URL,
        resource_server_url=AUTH_RESOURCE_SERVER_URL,
        required_scopes=AUTH_REQUIRED_SCOPES,
        client_registration_options=ClientRegistrationOptions(
            enabled=OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION,
            valid_scopes=AUTH_REQUIRED_SCOPES,
            default_scopes=AUTH_REQUIRED_SCOPES,
        ),
        revocation_options=RevocationOptions(enabled=True),
    )

    auth_server_provider = InMemoryOAuthProvider(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        default_scopes=AUTH_REQUIRED_SCOPES,
        allowed_redirect_host_suffixes=OAUTH_ALLOWED_REDIRECT_HOSTS,
        auth_code_ttl_seconds=OAUTH_AUTH_CODE_TTL_SECONDS,
        access_token_ttl_seconds=OAUTH_ACCESS_TOKEN_TTL_SECONDS,
        refresh_token_ttl_seconds=OAUTH_REFRESH_TOKEN_TTL_SECONDS,
        allow_dynamic_client_registration=OAUTH_ALLOW_DYNAMIC_CLIENT_REGISTRATION,
    )

elif AUTH_BEARER_TOKEN:
    if not AUTH_ISSUER_URL or not AUTH_RESOURCE_SERVER_URL:
        raise ValueError(
            "When MCP_AUTH_BEARER_TOKEN is set, MCP_AUTH_ISSUER_URL and "
            "MCP_AUTH_RESOURCE_SERVER_URL must also be set"
        )

    auth_settings = AuthSettings(
        issuer_url=AUTH_ISSUER_URL,
        resource_server_url=AUTH_RESOURCE_SERVER_URL,
        required_scopes=AUTH_REQUIRED_SCOPES,
    )
    token_verifier = StaticBearerTokenVerifier(
        token=AUTH_BEARER_TOKEN,
        scopes=AUTH_REQUIRED_SCOPES,
    )

mcp = FastMCP(
    "DocumentMCP",
    log_level="INFO",
    host=HOST,
    port=PORT,
    auth=auth_settings,
    auth_server_provider=auth_server_provider,
    token_verifier=token_verifier,
)

register_testing_tools(mcp, log_event)
register_file_manager_tools(mcp, log_event)
register_obsidian_tools(mcp, log_event)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    log_event(
        "server.starting",
        transport=transport,
        host=mcp.settings.host,
        port=mcp.settings.port,
        streamable_http_path=mcp.settings.streamable_http_path,
        app_log_level=APP_LOG_LEVEL,
        auth_enabled=bool(OAUTH_ENABLED or AUTH_BEARER_TOKEN),
        auth_mode=("oauth" if OAUTH_ENABLED else "bearer" if AUTH_BEARER_TOKEN else "none"),
        oauth_client_id=(OAUTH_CLIENT_ID if OAUTH_ENABLED else ""),
    )

    # For local testing with ngrok + Claude Custom MCP, run as HTTP.
    if transport in {"streamable-http", "streamable_http", "http"}:
        print(
            f"Starting MCP server on http://{mcp.settings.host}:{mcp.settings.port}{mcp.settings.streamable_http_path} (transport=streamable-http)"
        )
        log_event("server.mode", selected_transport="streamable-http")
        mcp.run(transport="streamable-http")
    else:
        print("Starting MCP server with stdio transport")
        log_event("server.mode", selected_transport="stdio")
        mcp.run(transport="stdio")
