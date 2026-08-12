# WorkBuddy ima-mcp connector

Use the connector tools already exposed to the WorkBuddy agent. Authorization is managed by WorkBuddy; never request or read a local IMA Client ID or API Key.

## Required tools

| Tool | Purpose |
|---|---|
| `mcp__ima-mcp__get_knowledge_base_list` | List knowledge bases; `params` must be an array |
| `mcp__ima-mcp__get_addable_knowledge_base_list` | List writable knowledge bases |
| `mcp__ima-mcp__search_knowledge_base` | Resolve a base by name |
| `mcp__ima-mcp__get_knowledge_list` | Browse entries, detect duplicates, inspect parse state |
| `mcp__ima-mcp__search_knowledge` | Verify full-text retrieval |
| `mcp__ima-mcp__create_media` | Create media and obtain short-lived COS credentials |
| `mcp__ima-mcp__add_knowledge` | Add an uploaded media item to a base |

Do not use `import_urls` or `fetch_media_content` in the book-download workflow.

## Verified request shapes

List personal bases:

```json
{"params":[{"limit":20,"type":"KBT_MINE_KB"}]}
```

Create media:

```json
{
  "content_type":"application/pdf",
  "file_ext":"pdf",
  "file_name":"完整文件名.pdf",
  "file_size":13453802,
  "knowledge_base_id":"<runtime id>"
}
```

Add knowledge after COS succeeds:

```json
{
  "knowledge_base_id":"<runtime id>",
  "media_id":"<create_media media_id>",
  "duplicate_name_strategy":"DUPLICATE_NAME_STRATEGY_SAVE"
}
```

Do not add `title`, `file_info`, or `media_type` to the MCP form.

List recent entries and parse state:

```json
{"knowledge_base_id":"<runtime id>","limit":5,"cursor":"","sort_type":"UPDATE_TS_DESC_SORT_TYPE"}
```

`media_state=1` means parsing; `media_state=2` with `parse_progress=100` means parsing succeeded.

Verify retrieval:

```json
{"knowledge_base_id":"<runtime id>","query":"<title keyword>","cursor":""}
```

## Duplicate replacement

The connector has no `check_repeated_names` tool. Traverse `get_knowledge_list` pages and compare the exact title before `create_media`. IMA cannot replace an existing same-name file. Ask whether to keep both or cancel. If keeping both, append `_YYYYMMDDHHmmss` before the extension, then repeat preflight and duplicate checking.

## Failure rules

- Missing tool or connector authorization: stop and ask the user to connect `ima-mcp` in WorkBuddy. Do not fall back to local IMA credentials.
- COS script nonzero: stop before `add_knowledge`.
- `add_knowledge` success: report only “added”; do not claim retrieval until parse state and search both pass.
- Never expose connector IDs, COS credentials, tokens, temporary URLs, or internal IDs in user-facing text.
