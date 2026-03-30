import os
from urllib.parse import quote

import httpx
from pydantic import Field


def register_obsidian_tools(mcp, log_event):
    def _config() -> dict[str, object]:
        base_url = os.getenv("OBSIDIAN_API_BASE_URL", "https://127.0.0.1:27124").strip().rstrip("/")
        api_key = os.getenv("OBSIDIAN_API_KEY", "").strip()
        verify_tls = os.getenv("OBSIDIAN_VERIFY_TLS", "0").strip().lower() in {"1", "true", "yes", "on"}
        timeout_seconds = float(os.getenv("OBSIDIAN_TIMEOUT_SECONDS", "15"))
        return {
            "base_url": base_url,
            "api_key": api_key,
            "verify_tls": verify_tls,
            "timeout_seconds": timeout_seconds,
        }

    def _normalize_vault_path(path: str) -> str:
        value = (path or "").strip().replace("\\", "/")
        value = value.lstrip("/")
        return value

    def _vault_url(path: str, trailing_slash: bool = False) -> str:
        cfg = _config()
        normalized = _normalize_vault_path(path)
        encoded = quote(normalized, safe="/")
        if encoded:
            url = f"{cfg['base_url']}/vault/{encoded}"
        else:
            url = f"{cfg['base_url']}/vault/"

        if trailing_slash and not url.endswith("/"):
            url += "/"
        return url

    def _request(
        method: str,
        url: str,
        *,
        content: str | bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        cfg = _config()
        api_key = str(cfg["api_key"])
        if not api_key:
            raise ValueError("OBSIDIAN_API_KEY is not set in .env")

        req_headers = {
            "Authorization": f"Bearer {api_key}",
        }
        if headers:
            req_headers.update(headers)

        with httpx.Client(verify=bool(cfg["verify_tls"]), timeout=float(cfg["timeout_seconds"])) as client:
            response = client.request(
                method,
                url,
                headers=req_headers,
                content=content,
            )
        return response

    def _parse_response(resp: httpx.Response):
        ctype = resp.headers.get("content-type", "").lower()
        if "application/json" in ctype:
            return resp.json()
        return resp.text

    @mcp.tool(
        name="obsidian_status",
        description="Check Obsidian Local REST API status.",
    )
    def obsidian_status() -> dict[str, object]:
        cfg = _config()
        log_event("tool.obsidian_status.start", base_url=cfg["base_url"])
        with httpx.Client(verify=bool(cfg["verify_tls"]), timeout=float(cfg["timeout_seconds"])) as client:
            resp = client.get(str(cfg["base_url"]) + "/")

        result = {
            "status_code": resp.status_code,
            "ok": resp.is_success,
            "body": resp.text[:500],
        }
        log_event("tool.obsidian_status.success", status_code=resp.status_code)
        return result

    @mcp.tool(
        name="obsidian_list",
        description="List files/folders in an Obsidian vault path.",
    )
    def obsidian_list(
        path: str = Field(default="", description="Vault-relative folder path, empty for root"),
    ):
        log_event("tool.obsidian_list.start", path=path)
        url = _vault_url(path, trailing_slash=True)
        resp = _request("GET", url)
        if not resp.is_success:
            log_event("tool.obsidian_list.error", path=path, status_code=resp.status_code, body=resp.text[:300])
            raise ValueError(f"Obsidian list failed ({resp.status_code}): {resp.text[:300]}")

        result = _parse_response(resp)
        log_event("tool.obsidian_list.success", path=path)
        return result

    @mcp.tool(
        name="obsidian_read",
        description="Read an Obsidian note/file from the vault.",
    )
    def obsidian_read(
        path: str = Field(description="Vault-relative file path, e.g. notes/todo.md"),
    ):
        log_event("tool.obsidian_read.start", path=path)
        url = _vault_url(path)
        resp = _request("GET", url)
        if not resp.is_success:
            log_event("tool.obsidian_read.error", path=path, status_code=resp.status_code, body=resp.text[:300])
            raise ValueError(f"Obsidian read failed ({resp.status_code}): {resp.text[:300]}")

        result = _parse_response(resp)
        log_event("tool.obsidian_read.success", path=path)
        return result

    @mcp.tool(
        name="obsidian_write",
        description="Create or overwrite an Obsidian note/file.",
    )
    def obsidian_write(
        path: str = Field(description="Vault-relative file path"),
        content: str = Field(description="Full file content to write"),
    ) -> dict[str, object]:
        log_event("tool.obsidian_write.start", path=path, content_length=len(content))
        url = _vault_url(path)
        resp = _request("PUT", url, content=content, headers={"Content-Type": "text/plain; charset=utf-8"})
        if not resp.is_success:
            log_event("tool.obsidian_write.error", path=path, status_code=resp.status_code, body=resp.text[:300])
            raise ValueError(f"Obsidian write failed ({resp.status_code}): {resp.text[:300]}")

        result = {
            "path": _normalize_vault_path(path),
            "status_code": resp.status_code,
            "ok": resp.is_success,
        }
        log_event("tool.obsidian_write.success", path=path, status_code=resp.status_code)
        return result

    @mcp.tool(
        name="obsidian_patch",
        description="Patch Obsidian note content by heading/block/frontmatter target.",
    )
    def obsidian_patch(
        path: str = Field(description="Vault-relative file path"),
        operation: str = Field(description="append, prepend, or replace"),
        target_type: str = Field(description="heading, block, or frontmatter"),
        target: str = Field(description="Target identifier"),
        content: str = Field(description="Content payload"),
        content_type: str = Field(
            default="text/plain",
            description="Content-Type, e.g. text/plain or application/json",
        ),
    ) -> dict[str, object]:
        op = operation.strip().lower()
        ttype = target_type.strip().lower()
        if op not in {"append", "prepend", "replace"}:
            raise ValueError("operation must be append, prepend, or replace")
        if ttype not in {"heading", "block", "frontmatter"}:
            raise ValueError("target_type must be heading, block, or frontmatter")

        log_event("tool.obsidian_patch.start", path=path, operation=op, target_type=ttype, target=target)
        url = _vault_url(path)
        resp = _request(
            "PATCH",
            url,
            content=content,
            headers={
                "Operation": op,
                "Target-Type": ttype,
                "Target": target,
                "Content-Type": content_type,
            },
        )
        if not resp.is_success:
            log_event("tool.obsidian_patch.error", path=path, status_code=resp.status_code, body=resp.text[:300])
            raise ValueError(f"Obsidian patch failed ({resp.status_code}): {resp.text[:300]}")

        result = {
            "path": _normalize_vault_path(path),
            "status_code": resp.status_code,
            "ok": resp.is_success,
        }
        log_event("tool.obsidian_patch.success", path=path, status_code=resp.status_code)
        return result

    @mcp.tool(
        name="obsidian_delete",
        description="Delete an Obsidian file from the vault.",
    )
    def obsidian_delete(
        path: str = Field(description="Vault-relative file path"),
    ) -> dict[str, object]:
        log_event("tool.obsidian_delete.start", path=path)
        url = _vault_url(path)
        resp = _request("DELETE", url)
        if not resp.is_success:
            log_event("tool.obsidian_delete.error", path=path, status_code=resp.status_code, body=resp.text[:300])
            raise ValueError(f"Obsidian delete failed ({resp.status_code}): {resp.text[:300]}")

        result = {
            "path": _normalize_vault_path(path),
            "status_code": resp.status_code,
            "ok": resp.is_success,
        }
        log_event("tool.obsidian_delete.success", path=path, status_code=resp.status_code)
        return result

    @mcp.tool(
        name="obsidian_create_folder",
        description="Create a folder in the Obsidian vault.",
    )
    def obsidian_create_folder(
        path: str = Field(description="Vault-relative folder path"),
    ) -> dict[str, object]:
        log_event("tool.obsidian_create_folder.start", path=path)
        url = _vault_url(path, trailing_slash=True)

        attempts = [
            ("POST", ""),
            ("PUT", ""),
            ("MKCOL", ""),
        ]
        last_status = None
        last_body = ""
        for method, body in attempts:
            resp = _request(method, url, content=body, headers={"Content-Type": "text/plain; charset=utf-8"})
            if resp.is_success:
                result = {
                    "path": _normalize_vault_path(path),
                    "status_code": resp.status_code,
                    "ok": True,
                    "method": method,
                }
                log_event("tool.obsidian_create_folder.success", path=path, status_code=resp.status_code, method=method)
                return result
            last_status = resp.status_code
            last_body = resp.text[:300]

        log_event("tool.obsidian_create_folder.error", path=path, status_code=last_status, body=last_body)
        raise ValueError(
            f"Obsidian create_folder failed ({last_status}): {last_body}. "
            "Try creating a note inside that folder first via obsidian_write."
        )

    log_event("tools.obsidian.loaded", tools=7)
