import secrets
import time
from typing import Optional

from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken


class DomainRestrictedOAuthClient(OAuthClientInformationFull):
    allowed_redirect_host_suffixes: list[str] = ["claude.ai"]

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            raise InvalidRedirectUriError("redirect_uri is required")

        host = redirect_uri.host or ""
        scheme = redirect_uri.scheme
        is_localhost = host in {"localhost", "127.0.0.1"}

        if scheme != "https" and not is_localhost:
            raise InvalidRedirectUriError("redirect_uri must use https")

        if not any(host == suffix or host.endswith("." + suffix) for suffix in self.allowed_redirect_host_suffixes):
            raise InvalidRedirectUriError(
                f"Redirect URI host '{host}' is not allowed. Allowed suffixes: {self.allowed_redirect_host_suffixes}"
            )

        return redirect_uri


class InMemoryOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        default_scopes: list[str],
        allowed_redirect_host_suffixes: list[str] | None = None,
        auth_code_ttl_seconds: int = 300,
        access_token_ttl_seconds: int = 3600,
        refresh_token_ttl_seconds: int = 30 * 24 * 3600,
        allow_dynamic_client_registration: bool = False,
    ):
        self.auth_code_ttl_seconds = auth_code_ttl_seconds
        self.access_token_ttl_seconds = access_token_ttl_seconds
        self.refresh_token_ttl_seconds = refresh_token_ttl_seconds
        self.allow_dynamic_client_registration = allow_dynamic_client_registration

        self.clients: dict[str, OAuthClientInformationFull] = {}
        self.authorization_codes: dict[str, AuthorizationCode] = {}
        self.refresh_tokens: dict[str, RefreshToken] = {}
        self.access_tokens: dict[str, AccessToken] = {}

        static_client = DomainRestrictedOAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=None,
            redirect_uris=[AnyUrl("https://claude.ai/")],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=" ".join(default_scopes),
            client_name="Claude MCP Client",
            allowed_redirect_host_suffixes=allowed_redirect_host_suffixes or ["claude.ai"],
        )
        self.clients[client_id] = static_client

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not self.allow_dynamic_client_registration:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="Dynamic client registration is disabled",
            )

        if client_info.client_id is None:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="client_id is required",
            )

        self.clients[client_info.client_id] = client_info

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        code = secrets.token_urlsafe(48)
        expires_at = time.time() + self.auth_code_ttl_seconds
        scopes = params.scopes if params.scopes is not None else (client.scope.split(" ") if client.scope else [])

        self.authorization_codes[code] = AuthorizationCode(
            code=code,
            scopes=scopes,
            expires_at=expires_at,
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )

        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self.authorization_codes.get(authorization_code)
        if code is None:
            return None

        if code.expires_at < time.time():
            self.authorization_codes.pop(authorization_code, None)
            return None

        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Enforce one-time use of authorization code.
        self.authorization_codes.pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)
        now = int(time.time())
        access_expires_at = now + self.access_token_ttl_seconds
        refresh_expires_at = now + self.refresh_token_ttl_seconds

        access = AccessToken(
            token=access_token,
            client_id=client.client_id or "",
            scopes=authorization_code.scopes,
            expires_at=access_expires_at,
            resource=authorization_code.resource,
        )
        refresh = RefreshToken(
            token=refresh_token,
            client_id=client.client_id or "",
            scopes=authorization_code.scopes,
            expires_at=refresh_expires_at,
        )

        self.access_tokens[access_token] = access
        self.refresh_tokens[refresh_token] = refresh

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=self.access_token_ttl_seconds,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token = self.refresh_tokens.get(refresh_token)
        if token is None:
            return None

        if token.expires_at is not None and token.expires_at < int(time.time()):
            self.refresh_tokens.pop(refresh_token, None)
            return None

        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        self.refresh_tokens.pop(refresh_token.token, None)

        new_access_token = secrets.token_urlsafe(48)
        new_refresh_token = secrets.token_urlsafe(48)
        now = int(time.time())
        access_expires_at = now + self.access_token_ttl_seconds
        refresh_expires_at = now + self.refresh_token_ttl_seconds

        access = AccessToken(
            token=new_access_token,
            client_id=client.client_id or "",
            scopes=scopes,
            expires_at=access_expires_at,
            resource=None,
        )
        refresh = RefreshToken(
            token=new_refresh_token,
            client_id=client.client_id or "",
            scopes=scopes,
            expires_at=refresh_expires_at,
        )

        self.access_tokens[new_access_token] = access
        self.refresh_tokens[new_refresh_token] = refresh

        return OAuthToken(
            access_token=new_access_token,
            token_type="Bearer",
            expires_in=self.access_token_ttl_seconds,
            refresh_token=new_refresh_token,
            scope=" ".join(scopes) if scopes else None,
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        access_token = self.access_tokens.get(token)
        if access_token is None:
            return None

        if access_token.expires_at is not None and access_token.expires_at < int(time.time()):
            self.access_tokens.pop(token, None)
            return None

        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, AccessToken):
            self.access_tokens.pop(token.token, None)
            return

        if isinstance(token, RefreshToken):
            self.refresh_tokens.pop(token.token, None)
            return

        raise TokenError(error="invalid_request", error_description="Unknown token type")
