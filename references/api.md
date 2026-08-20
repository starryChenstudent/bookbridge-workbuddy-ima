# Fast Download API reference

Official documentation source: <https://tw.annas-archive.gl/faq#api>

## Scope

The stable member JSON API only obtains a fast download URL. It is not a general search API. Do not implement `book_search` by requesting or parsing `/search`: it is an unversioned human-facing HTML page, can redirect to `?check=1`, and can return a DDoS-Guard JavaScript challenge or HTTP 403 to automated sessions. Large fully automated indexes require Anna's Archive's published Elasticsearch or MariaDB datasets and are intentionally outside the lightweight Skill package.

## Record discovery contract

BookBridge v2 accepts either:

- an official HTTPS `/md5/<32-character MD5>` record URL; or
- the raw 32-character MD5.

Pass a new value to `annas_archive_client.py record --remember`. It is normalized and stored in the current user's `~/.config/bookbridge/records.json`. Later title-only requests first call `lookup`; a unique cached match can continue without asking for the MD5 again. Different file editions and formats have different MD5 values and are stored as separate records.

When `lookup` returns `record_required`, ask the user for the selected official record URL or MD5. After it is supplied, normalization, rights gating, Fast Download API use, file validation, and IMA ingestion can continue automatically. BookBridge does not open, fetch, or parse Anna's search page.

Do not switch to unofficial mirrors, spoof browser fingerprints, read or replay browser cookies, copy account credentials, solve CAPTCHAs, or replay challenge tokens. The member key is only for the Fast Download endpoint after record selection.

## Endpoint

`GET https://tw.annas-archive.gl/dyn/api/fast_download.json`

Required query parameters:

- `md5`: 32-character MD5 of the selected record;
- `key`: member secret key.

Optional query parameters:

- `path_index`: zero-based collection choice;
- `domain_index`: zero-based download server choice.

Successful responses use HTTP 200 or 204 and provide `download_url` plus `account_fast_download_info`. Error responses use another status or provide a null URL and an `error` string.

## Runtime rules

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
- Require public-domain status, an open license, official open access, or the user's explicit permission for the exact work before download. A title request, membership, or academic purpose alone is not sufficient.

## Expected error handling

- Invalid MD5: stop and return to candidate selection.
- Missing or invalid key: run `scripts/configure_key.py` locally with hidden input; do not ask for the key in chat or pass it as a command argument.
- Membership or quota error: report the credential-safe server message and stop.
- Empty download URL: do not fall back to mirrors, torrents, or browser bypasses.
- Title-only request with no cache hit: ask for the selected official record URL or MD5; do not scrape the protected HTML endpoint.
- Search challenge or HTTP 403 observed outside BookBridge: do not retry the protected HTML endpoint or use a CAPTCHA-solving service.
- Partner download failure: retry normally up to three times and retain only the deterministic `.part` file for a later retry.
