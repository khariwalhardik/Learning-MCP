import mimetypes
from pathlib import Path

from pydantic import Field
from mcp.server.fastmcp.prompts import base


def register_file_manager_tools(mcp, log_event):
    home_dir = Path.home().resolve()

    alias_map = {
        "home": home_dir,
        "desktop": (home_dir / "Desktop").resolve(),
        "downloads": (home_dir / "Downloads").resolve(),
        "documents": (home_dir / "Documents").resolve(),
        "cwd": Path.cwd().resolve(),
        ".": Path.cwd().resolve(),
    }

    def _resolve_path(raw_path: str) -> Path:
        text = (raw_path or "").strip()
        if not text:
            text = "."

        key = text.lower()
        if key in alias_map:
            candidate = alias_map[key]
        else:
            candidate = Path(text).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            else:
                candidate = candidate.resolve()

        # Keep filesystem tools limited to the current user home for safety.
        if home_dir not in candidate.parents and candidate != home_dir:
            raise ValueError(f"Path is outside allowed root ({home_dir}): {candidate}")

        return candidate

    def _resolve_existing_file(raw_path: str) -> Path:
        candidate = _resolve_path(raw_path)
        if candidate.exists() and candidate.is_file():
            return candidate

        # For plain filenames like "test.txt", try common user folders.
        text = (raw_path or "").strip()
        if text and "/" not in text and "\\" not in text and text.lower() not in alias_map:
            for base in (alias_map["desktop"], alias_map["downloads"], alias_map["documents"]):
                probe = (base / text).resolve()
                if probe.exists() and probe.is_file():
                    return probe

        raise ValueError(
            f"File not found: {candidate}. Try an absolute path or aliases like 'desktop/{text}'"
        )

    def _guess_is_text(path: Path) -> bool:
        mime, _enc = mimetypes.guess_type(str(path))
        if mime is None:
            return True
        return mime.startswith("text/") or mime in {
            "application/json",
            "application/xml",
            "application/javascript",
        }

    def _read_text_file(path: Path) -> str:
        if not _guess_is_text(path):
            raise ValueError(f"Refusing to read non-text/binary file: {path}")
        return path.read_text(encoding="utf-8")

    @mcp.tool(
        name="read_doc",
        description="Read a text document by path (supports aliases: desktop, downloads, documents, home, cwd).",
    )
    def read_doc(doc_id: str) -> str:
        log_event("tool.read_doc.start", doc_id=doc_id)
        path = _resolve_existing_file(doc_id)
        result = _read_text_file(path)
        log_event("tool.read_doc.success", doc_id=doc_id, resolved_path=str(path), length=len(result))
        return result

    @mcp.tool(
        name="read_doc_contents",
        description="Read a text file and return contents (path or alias-supported path).",
    )
    def read_document(
        doc_id: str = Field(description="Path of the document to read"),
    ):
        log_event("tool.read_doc_contents.start", doc_id=doc_id)
        path = _resolve_existing_file(doc_id)
        result = _read_text_file(path)
        log_event("tool.read_doc_contents.success", doc_id=doc_id, resolved_path=str(path), length=len(result))
        return result

    @mcp.tool(
        name="list_files",
        description="List files in a folder, similar to ls. Supports recursive listing.",
    )
    def list_files(
        folder_path: str = Field(
            default=".",
            description="Folder path or alias (desktop, downloads, documents, home, cwd)",
        ),
        recursive: bool = Field(
            default=False,
            description="Set true to list files recursively",
        ),
        include_hidden: bool = Field(
            default=False,
            description="Set true to include hidden files and directories",
        ),
        include_dirs: bool = Field(
            default=True,
            description="Set true to include directories in the output",
        ),
        max_entries: int = Field(
            default=500,
            description="Maximum number of entries to return",
        ),
    ) -> dict[str, object]:
        log_event(
            "tool.list_files.start",
            folder_path=folder_path,
            recursive=recursive,
            include_hidden=include_hidden,
            include_dirs=include_dirs,
            max_entries=max_entries,
        )

        target = _resolve_path(folder_path)
        if not target.exists():
            log_event("tool.list_files.error", error="path_not_found", folder_path=str(target))
            raise ValueError(f"Path not found: {target}")

        if not target.is_dir():
            log_event("tool.list_files.error", error="path_not_directory", folder_path=str(target))
            raise ValueError(f"Path is not a directory: {target}")

        if max_entries <= 0:
            log_event("tool.list_files.error", error="invalid_max_entries", max_entries=max_entries)
            raise ValueError("max_entries must be greater than 0")

        iterator = target.rglob("*") if recursive else target.iterdir()
        entries: list[str] = []
        truncated = False

        for item in iterator:
            rel_parts = item.relative_to(target).parts
            if not include_hidden and any(part.startswith(".") for part in rel_parts):
                continue

            if item.is_dir():
                if include_dirs:
                    entries.append(item.relative_to(target).as_posix() + "/")
            else:
                entries.append(item.relative_to(target).as_posix())

            if len(entries) >= max_entries:
                truncated = True
                break

        entries.sort()
        result: dict[str, object] = {
            "folder": str(target),
            "recursive": recursive,
            "include_hidden": include_hidden,
            "include_dirs": include_dirs,
            "max_entries": max_entries,
            "count": len(entries),
            "truncated": truncated,
            "entries": entries,
        }
        log_event(
            "tool.list_files.success",
            folder=str(target),
            count=len(entries),
            truncated=truncated,
        )
        return result

    @mcp.tool(
        name="edit_document",
        description="Edit a text file by replacing exact text (path-based).",
    )
    def edit_document(
        doc_id: str = Field(description="Path of the document that will be edited"),
        old_str: str = Field(
            description="The text to replace. Must match exactly, including whitespace"
        ),
        new_str: str = Field(
            description="The new text to insert in place of the old text"
        ),
    ):
        log_event(
            "tool.edit_document.start",
            doc_id=doc_id,
            old_str=old_str,
            new_str=new_str,
        )
        path = _resolve_existing_file(doc_id)

        before = _read_text_file(path)
        after = before.replace(old_str, new_str)
        changed = before != after
        if changed:
            path.write_text(after, encoding="utf-8")

        log_event("tool.edit_document.success", doc_id=doc_id, resolved_path=str(path), changed=changed)

        return {
            "path": str(path),
            "changed": changed,
        }

    @mcp.resource("docs://documents", mime_type="application/json")
    def list_docs() -> list[str]:
        # Return top-level entries from Desktop and Downloads for quick discovery.
        result: list[str] = []
        for label in ("desktop", "downloads"):
            base = alias_map[label]
            if base.exists() and base.is_dir():
                for item in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                    suffix = "/" if item.is_dir() else ""
                    result.append(f"{label}/{item.name}{suffix}")

        log_event("resource.list_docs.success", count=len(result))
        return result

    @mcp.resource("docs://documents/{doc_id}", mime_type="text/plain")
    def fetch_doc(doc_id: str) -> str:
        log_event("resource.fetch_doc.start", doc_id=doc_id)
        path = _resolve_existing_file(doc_id)

        result = _read_text_file(path)
        log_event("resource.fetch_doc.success", doc_id=doc_id, resolved_path=str(path), length=len(result))
        return result

    @mcp.prompt(
        name="format",
        description="Rewrites the contents of the document in Markdown format.",
    )
    def format_document(
        doc_id: str = Field(description="Path of the document to format"),
    ) -> list[base.Message]:
        log_event("prompt.format.start", doc_id=doc_id)
        prompt = f"""
        Your goal is to reformat a document to be written with markdown syntax.

        The path of the document you need to reformat is:
        <document_id>
        {doc_id}
        </document_id>

        Add in headers, bullet points, tables, etc as necessary. Feel free to add in extra text, but don't change the meaning of the report.
        Use the 'edit_document' tool to edit the document. After the document has been edited, respond with the final version of the doc. Don't explain your changes.
        """

        result = [base.UserMessage(prompt)]
        log_event("prompt.format.success", doc_id=doc_id)
        return result
