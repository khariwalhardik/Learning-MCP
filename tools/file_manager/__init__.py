from pathlib import Path

from pydantic import Field
from mcp.server.fastmcp.prompts import base


def register_file_manager_tools(mcp, log_event):
    docs = {
        "deposition.md": "This deposition covers the testimony of Angela Smith, P.E.",
        "report.pdf": "The report details the state of a 20m condenser tower.",
        "financials.docx": "These financials outline the project's budget and expenditures.",
        "outlook.pdf": "This document presents the projected future performance of the system.",
        "plan.md": "The plan outlines the steps for the project's implementation.",
        "spec.txt": "These specifications define the technical requirements for the equipment.",
    }

    @mcp.tool(
        name="read_doc",
        description="Read the contents of a document by id.",
    )
    def read_doc(doc_id: str) -> str:
        log_event("tool.read_doc.start", doc_id=doc_id)
        if doc_id not in docs:
            log_event("tool.read_doc.error", doc_id=doc_id, error="doc_not_found")
            raise ValueError(f"Doc with id {doc_id} not found")
        result = docs[doc_id]
        log_event("tool.read_doc.success", doc_id=doc_id, length=len(result))
        return result

    @mcp.tool(
        name="read_doc_contents",
        description="Read the contents of a document and return it as a string.",
    )
    def read_document(
        doc_id: str = Field(description="Id of the document to read"),
    ):
        log_event("tool.read_doc_contents.start", doc_id=doc_id)
        if doc_id not in docs:
            log_event("tool.read_doc_contents.error", doc_id=doc_id, error="doc_not_found")
            raise ValueError(f"Doc with id {doc_id} not found")

        result = docs[doc_id]
        log_event("tool.read_doc_contents.success", doc_id=doc_id, length=len(result))
        return result

    @mcp.tool(
        name="list_files",
        description="List files in a folder, similar to ls. Supports recursive listing.",
    )
    def list_files(
        folder_path: str = Field(
            default=".",
            description="Folder path to list",
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

        target = Path(folder_path).expanduser().resolve()
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
        description="Edit a document by replacing a string in the documents content with a new string",
    )
    def edit_document(
        doc_id: str = Field(description="Id of the document that will be edited"),
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
        if doc_id not in docs:
            log_event("tool.edit_document.error", doc_id=doc_id, error="doc_not_found")
            raise ValueError(f"Doc with id {doc_id} not found")

        before = docs[doc_id]
        docs[doc_id] = docs[doc_id].replace(old_str, new_str)
        changed = before != docs[doc_id]
        log_event("tool.edit_document.success", doc_id=doc_id, changed=changed)

    @mcp.resource("docs://documents", mime_type="application/json")
    def list_docs() -> list[str]:
        result = list(docs.keys())
        log_event("resource.list_docs.success", count=len(result), doc_ids=result)
        return result

    @mcp.resource("docs://documents/{doc_id}", mime_type="text/plain")
    def fetch_doc(doc_id: str) -> str:
        log_event("resource.fetch_doc.start", doc_id=doc_id)
        if doc_id not in docs:
            log_event("resource.fetch_doc.error", doc_id=doc_id, error="doc_not_found")
            raise ValueError(f"Doc with id {doc_id} not found")
        result = docs[doc_id]
        log_event("resource.fetch_doc.success", doc_id=doc_id, length=len(result))
        return result

    @mcp.prompt(
        name="format",
        description="Rewrites the contents of the document in Markdown format.",
    )
    def format_document(
        doc_id: str = Field(description="Id of the document to format"),
    ) -> list[base.Message]:
        log_event("prompt.format.start", doc_id=doc_id)
        prompt = f"""
        Your goal is to reformat a document to be written with markdown syntax.

        The id of the document you need to reformat is:
        <document_id>
        {doc_id}
        </document_id>

        Add in headers, bullet points, tables, etc as necessary. Feel free to add in extra text, but don't change the meaning of the report.
        Use the 'edit_document' tool to edit the document. After the document has been edited, respond with the final version of the doc. Don't explain your changes.
        """

        result = [base.UserMessage(prompt)]
        log_event("prompt.format.success", doc_id=doc_id)
        return result
