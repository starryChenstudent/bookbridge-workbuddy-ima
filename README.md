# BookBridge

> A local reading workflow for WorkBuddy: find books the user is authorized to access, save the original files locally, and import them into an IMA knowledge base.

[English](README.md) | [简体中文](README.zh-CN.md)

[![Version](https://img.shields.io/badge/version-BookBridge--v1-blue.svg)](https://github.com/starryChenstudent/bookbridge-workbuddy-ima/tree/BookBridge-v1)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![WorkBuddy Skill](https://img.shields.io/badge/WorkBuddy-Skill-7c3aed.svg)](SKILL.md)

## Overview

BookBridge is a WorkBuddy Skill that handles edition discovery, format selection, authorized downloading, local integrity checks, IMA duplicate detection, upload, ingestion, and retrieval verification.

Original downloaded books are stored by default in:

```text
Desktop/library/books/
```

Use this project only for public-domain or openly licensed works, or content that you are legally authorized to access and download. Follow applicable laws, content licenses, and service terms.

## Features

- Search by title, author, ISBN, DOI, or MD5.
- Prefer PDF, then EPUB, then formats accepted by or convertible for IMA.
- Resume interrupted downloads and validate HTTPS, file signatures, size, and MD5.
- Preserve original files locally without silently overwriting existing books.
- Upload through WorkBuddy's connected `ima-mcp` connector.
- Check for exact-name duplicates before uploading.
- Distinguish between added, parsing, and searchable states.
- Keep Anna's Archive keys, IMA credentials, and temporary COS credentials out of the public package.

## Workflow

```mermaid
flowchart LR
    A[Book request] --> B[Find and select an edition]
    B --> C[Authorized download and validation]
    C --> D[Save to local library]
    D --> E[IMA preflight and duplicate check]
    E --> F[Upload and add to knowledge base]
    F --> G[Wait for parsing and verify search]
```

## Requirements

- WorkBuddy with a working `ima-mcp` connector.
- Python 3.10 or later. The core Python scripts use only the standard library.
- Node.js 18 or later for streaming files to Tencent Cloud COS.
- An active Anna's Archive membership and its member secret key for the Fast Download API.
- Optional: Calibre's `ebook-convert`, only when MOBI, AZW, AZW3, FB2, RTF, or DJVU must be converted to EPUB.

The project does not install Python, Node.js, Calibre, or other software automatically.

## Install

### Option 1: download the Skill-only package

Download [`BookBridge-v1`](https://github.com/starryChenstudent/bookbridge-workbuddy-ima/archive/refs/tags/BookBridge-v1.zip). This tag snapshot contains only the Skill itself—no README, license, or Git configuration. Extract it and import the directory containing `SKILL.md` into WorkBuddy.

### Option 2: clone the repository

```bash
git clone https://github.com/starryChenstudent/bookbridge-workbuddy-ima.git
cd ./bookbridge-workbuddy-ima
```

Then add the directory as a Skill in WorkBuddy.

## Anna's Archive API access and key setup

BookBridge does not grant Anna's Archive API access. The stable Fast Download JSON API is a member feature, so complete these steps first:

1. Open the [Anna's Archive account page](https://annas-archive.gl/account) and register or sign in.
2. Obtain an active membership through Anna's Archive's official process. Review its current terms and availability before proceeding.
3. Save the account **secret key** supplied by Anna's Archive. This member secret key is used as the Fast Download API key. Do not post it in chat, an issue, or a commit.

Anna's Archive documents the member API in its [API FAQ](https://annas-archive.gl/faq#api). Membership, quota, and access rules are controlled by Anna's Archive and may change.

After installing the Skill, open a terminal in the Skill root and check the runtime and key status:

```bash
python3 scripts/python_runner.py runtime_check.py
python3 scripts/python_runner.py configure_key.py --check
```

If the result contains `configured: false`, run:

```bash
python3 scripts/python_runner.py configure_key.py
```

Paste the Anna's Archive member secret key only into the hidden terminal prompt, then enter it again for confirmation. The script stores it outside the Skill directory at:

```text
~/.config/annas-archive/api_key
```

Verify the setup without displaying the key:

```bash
python3 scripts/python_runner.py configure_key.py --check
```

A successful result reports `configured: true`. Never add the key to `SKILL.md`, `.env`, Git, a public ZIP, or a chat message.

Finally, connect `ima-mcp` from WorkBuddy's connector management page. IMA authorization is managed by WorkBuddy; BookBridge does not read a local IMA Client ID or API key.

## Usage examples

After installation and `ima-mcp` connection, ask WorkBuddy directly:

```text
Find and download <Book Title>, then add it to my IMA knowledge base.
```

```text
Find the Chinese edition for ISBN 978xxxxxxxxxx. Download it locally only; do not upload it to IMA.
```

```text
Import this authorized EPUB into my default IMA knowledge base and confirm that it is searchable.
```

The default workflow completes search, download, IMA ingestion, and retrieval verification. It stops after local download only when the user explicitly asks not to upload.

## Project structure

```text
.
├── SKILL.md                         # Main workflow and safety gates
├── agents/openai.yaml               # WorkBuddy/Agent metadata
├── references/
│   ├── api.md                       # Fast Download API reference
│   └── ima-mcp.md                   # IMA MCP request conventions
└── scripts/
    ├── annas_archive_client.py      # Search, download, and integrity checks
    ├── configure_key.py             # Hidden local credential setup
    ├── cos-upload.cjs               # Streaming COS upload
    ├── format_for_ima.py            # Format preparation and preflight
    ├── library_paths.py             # Local library path handling
    ├── package_skill.py             # Public/private packaging
    ├── python_runner.py             # Python runtime entry point
    └── runtime_check.py             # Runtime checks
```

## Security and privacy

- Public source and public packages never contain an Anna's Archive key.
- Temporary download URLs, COS credentials, tokens, knowledge-base IDs, media IDs, and hashes are not shown to users.
- Downloads require HTTPS and do not use proxies, torrents, or access-control bypasses.
- A failed COS upload never proceeds to IMA ingestion.
- Packaging or reinstalling does not delete books or user configuration under `Desktop/library/`.

See [SKILL.md](SKILL.md) for the complete execution rules.

## Version

The first public version is **BookBridge-v1**.

## License

This project uses the [MIT License](LICENSE). Third-party content, services, and downloaded files remain subject to their respective terms and licenses.
