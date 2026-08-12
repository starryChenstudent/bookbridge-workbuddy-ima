# Fast Download API reference

Official documentation source: <https://tw.annas-archive.gl/faq#api>

## Scope

The stable member JSON API only obtains a fast download URL. It is not a general search API. Use the website Full database search for ordinary discovery; large custom indexes require Anna's Archive's published Elasticsearch or MariaDB datasets.

## Endpoint

`GET https://tw.annas-archive.gl/dyn/api/fast_download.json`

Required query parameters:

- `md5`: 32-character MD5 of the selected record;
- `key`: member secret key.

Optional query parameters:

- `path_index`: zero-based collection choice;
- `domain_index`: zero-based download server choice.

Successful responses use HTTP 200 or 204 and provide `download_url` plus `account_fast_download_info`. Error responses use another status or provide a null URL and an `error` string.

## First-version runtime rules

- Use Python 3.10 or newer with a current TLS stack on macOS or Windows.
- Read the key from `ANNAS_ARCHIVE_API_KEY` or the current user's `~/.config/annas-archive/api_key` file.
- Never store the key inside the Skill directory or include it in a Skill package.
- Never accept the key as a CLI argument.
- Never log the API request URL or returned temporary download URL.
- Pin API requests to `annas-archive.gl` or `tw.annas-archive.gl` over HTTPS.
- Reject cross-host API redirects.
- Treat the partner download URL as sensitive and temporary.
- Redact credentials and URLs from error messages.
- Disable environment and system proxies explicitly. Use direct connections only.

## Expected error handling

- Invalid MD5: stop and return to candidate selection.
- Missing or invalid key: run `scripts/configure_key.py` locally with hidden input; do not ask for the key in chat or pass it as a command argument.
- Membership or quota error: report the credential-safe server message and stop.
- Empty download URL: do not fall back to mirrors, torrents, or browser bypasses.
- Partner download failure: retry normally up to three times and retain only the deterministic `.part` file for a later retry.
