"""Notion API helpers: read drafts, write improved pages."""

from typing import Any

from notion_client import Client


def _rich_text_to_str(rich_texts: list[dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def _block_to_markdown(block: dict) -> str:
    btype = block["type"]
    payload = block.get(btype, {})
    text = _rich_text_to_str(payload.get("rich_text", []))

    match btype:
        case "heading_1":
            return f"# {text}"
        case "heading_2":
            return f"## {text}"
        case "heading_3":
            return f"### {text}"
        case "bulleted_list_item":
            return f"- {text}"
        case "numbered_list_item":
            return f"1. {text}"
        case "paragraph":
            return text
        case _:
            return text


def get_page_title(page: dict) -> str:
    for prop in page["properties"].values():
        if prop["type"] == "title":
            return _rich_text_to_str(prop["title"])
    return "Untitled"


def get_page_content(client: Client, page_id: str) -> str:
    lines: list[str] = []
    cursor = None

    while True:
        kwargs: dict[str, Any] = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor

        response = client.blocks.children.list(**kwargs)

        for block in response["results"]:
            line = _block_to_markdown(block)
            if line:
                lines.append(line)

        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]

    return "\n\n".join(lines)


def _db_query(client: Client, database_id: str, body: dict) -> dict:
    return client.request(
        path=f"databases/{database_id}/query",
        method="POST",
        body=body,
    )


def get_draft_pages(client: Client, database_id: str) -> list[dict]:
    pages: list[dict] = []
    cursor = None

    while True:
        body: dict[str, Any] = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor

        response = _db_query(client, database_id, body)
        pages.extend(response["results"])

        if not response.get("has_more"):
            break
        cursor = response["next_cursor"]

    return pages


def page_url(page_id: str) -> str:
    return f"https://notion.so/{page_id.replace('-', '')}"


def find_improved_by_original_url(
    client: Client, database_id: str, original_url: str
) -> dict | None:
    response = _db_query(
        client,
        database_id,
        body={
            "filter": {
                "property": "Original Draft",
                "url": {"equals": original_url},
            }
        },
    )
    results = response.get("results", [])
    return results[0] if results else None


def _markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("### "):
            blocks.append(_heading_block(3, stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(_heading_block(2, stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(_heading_block(1, stripped[2:]))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_list_block("bulleted", stripped[2:]))
        elif stripped[:3].rstrip(". ").isdigit() and ". " in stripped:
            text = stripped.split(". ", 1)[1]
            blocks.append(_list_block("numbered", text))
        else:
            blocks.append(_paragraph_block(stripped))

    return blocks


def _rich_text(text: str) -> list[dict]:
    return [{"type": "text", "text": {"content": text}}]


def _heading_block(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {key: {"rich_text": _rich_text(text)}, "type": key, "object": "block"}


def _list_block(style: str, text: str) -> dict:
    key = f"{style}_list_item"
    return {key: {"rich_text": _rich_text(text)}, "type": key, "object": "block"}


def _paragraph_block(text: str) -> dict:
    return {
        "paragraph": {"rich_text": _rich_text(text)},
        "type": "paragraph",
        "object": "block",
    }


def create_improved_page(
    client: Client,
    database_id: str,
    title: str,
    content_markdown: str,
    original_url: str,
) -> dict:
    blocks = _markdown_to_blocks(content_markdown)

    # Notion API caps children at 100 blocks per request; we append in batches later.
    first_batch = blocks[:100]
    overflow = blocks[100:]

    page = client.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": _rich_text(title)},
            "Original Draft": {"url": original_url},
        },
        children=first_batch,
    )

    for i in range(0, len(overflow), 100):
        client.blocks.children.append(
            block_id=page["id"],
            children=overflow[i : i + 100],
        )

    return page


def update_improved_page(
    client: Client,
    page_id: str,
    title: str,
    content_markdown: str,
) -> dict:
    # Clear existing children then re-append.
    existing = client.blocks.children.list(block_id=page_id)
    for block in existing["results"]:
        client.blocks.delete(block_id=block["id"])

    blocks = _markdown_to_blocks(content_markdown)
    for i in range(0, len(blocks), 100):
        client.blocks.children.append(
            block_id=page_id, children=blocks[i : i + 100]
        )

    return client.pages.update(
        page_id=page_id,
        properties={
            "Name": {"title": _rich_text(title)},
        },
    )
