# Project Description: Designing a Proxy Server

## Objective
Build a working forward proxy for a Computer Networks mini-project. The proxy receives client HTTP requests, validates them, enforces domain-based access control, optionally reuses a fresh cached response, forwards cache misses to the origin server, and logs the outcome. It handles multiple clients with a thread-per-client model.

## Architecture

`Client → TCP listener → request parser/validator → domain blocklist → cache lookup → origin connection on miss → response framing → client`

HTTPS clients use `CONNECT`; after an allowed tunnel is established, encrypted bytes are relayed without TLS decryption.

## Design choices

- **Language/networking:** Python 3 standard library, TCP sockets, and threads.
- **Cache:** in-memory `OrderedDict` with a lock. The mapping key is `(canonical_url, accept_encoding)`. `get()` counts a valid fresh entry as a hit; a missing or expired entry counts as a miss. Successful lookups update recency. The oldest entry is evicted at capacity.
- **Freshness:** TTL uses origin `s-maxage`/`max-age` or `Expires` when available, capped by the configured 60-second default. `Age` is deducted from max-age. Expired entries are never served.
- **Cache safety:** cache only complete HTTP 200 GET responses that meet a conservative policy. Bypass requests with cookies/authorization and avoid storing private/no-store/no-cache/set-cookie or unsupported Vary responses.
- **Access control:** `blocked_domains.txt` blocks a domain and its subdomains, returning HTTP 403.
- **Protocol/error handling:** HTTP request headers are size-limited, Content-Length bodies are bounded, unsupported chunked uploads are explicitly rejected, and origin responses are read using Content-Length, chunked framing, or connection-close framing. Truncated framed responses are not cached. DNS/connect/timeout failures are logged and mapped to HTTP error responses where possible.
- **Logging:** request method, destination, HTTP status, cache state, elapsed time, block events, cache storage, and cache statistics are logged.
- **Performance measurement:** direct and proxied requests use the same URL and `Cache-Control: no-cache`, separating proxy overhead from cache-hit speedups. A distinct warm-cache check demonstrates caching where the origin allows it.

## Scope limitations

This is a course demonstration, not a production proxy. It handles one request per client connection, does not implement persistent keep-alive, rejects chunked request bodies, does not implement full standards-compliant cache revalidation, and cannot inspect encrypted HTTPS traffic inside CONNECT tunnels. A thread is created per accepted client.

## Run and test

```bash
python proxy.py
python -m unittest -v test_lru test_proxy
python performance_test.py --url http://example.com/ --rounds 8 --clients 10
```

Use a destination you are permitted to test and report the actual benchmark output from your environment.
