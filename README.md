# Designing a Proxy Server — Computer Networks Mini Project

A threaded Python forward proxy for real HTTP requests, with an in-memory TTL/LRU response cache, domain blocking, request/error logging, and HTTPS `CONNECT` tunnelling. The implementation is intended for a local course demonstration, not production deployment.

## Requirements

- Python 3.10 or newer (uses standard library only)
- Network access to the HTTP destination used for the demo

## Run the proxy

Open a terminal in this project folder:

```bash
python proxy.py
```

The default listener is `127.0.0.1:8080`. Stop it with `Ctrl+C`. Configure it using environment variables if needed:

| Variable | Default | Meaning |
|---|---|---|
| `PROXY_HOST` | `127.0.0.1` | Listening interface |
| `PROXY_PORT` | `8080` | Listening port |
| `PROXY_CACHE_TTL` | `60` | Maximum default cache freshness in seconds |
| `PROXY_CACHE_MAX_ENTRIES` | `100` | Maximum in-memory entries |
| `PROXY_BLOCKLIST` | `blocked_domains.txt` | Domain blocklist path |
| `PROXY_LOG_FILE` | `proxy.log` | Log file path |

The cache is **in memory**. All entries are cleared when the process stops; no cache directory or cache files are created.

## Demonstrate forwarding and cache

In a second terminal:

```bash
python test_client.py
```

Or configure a destination in `client.py` and run `python client.py`. Run the same eligible GET twice and inspect `proxy.log`: the first lookup should be a `CACHE MISS`; a later fresh lookup may be a `CACHE HIT` if the origin response permits caching. Some websites intentionally send `no-store`, `private`, `Set-Cookie`, or unsupported `Vary` directives, so not every public URL will be cached. Use a controlled local HTTP test server if a deterministic cache demo is required.

## Demonstrate domain blocking

Add a domain on its own line in `blocked_domains.txt`, for example:

```text
example.com
```

Requests for that domain and its subdomains are denied with HTTP `403 Forbidden`. Remove the test entry after the demo. The blocklist is read when each request is checked, so edits do not require restarting the proxy.

## HTTPS

Configure a browser/client to use `127.0.0.1:8080` as its HTTP proxy. HTTPS clients use `CONNECT host:443`; the proxy creates a TCP tunnel and does not decrypt TLS traffic. The same domain-blocking rule is applied before the tunnel opens. HTTPS tunnel support is implemented but is not covered by the HTTP performance benchmark.

## Tests

```bash
python -m unittest -v test_lru test_proxy
python -m py_compile proxy.py client.py test_client.py performance_test.py
```

The unit tests cover hit/miss counters, TTL expiry, LRU ordering/eviction, cache policy directives, and complete versus truncated response framing.

## Performance evaluation

Keep the proxy running, then run:

```bash
python performance_test.py --url http://example.com/ --rounds 8 --clients 10
```

Use an HTTP URL you are allowed to test. The direct-versus-proxy comparison sends `Cache-Control: no-cache` to both paths so it measures proxy overhead rather than comparing direct requests with cache hits. It reports successful/failed requests, status codes, min/mean/median/p95/max latency, throughput under concurrent load, and the mean overhead estimate. The optional warm-cache check is separate and may not hit if the origin disallows caching. Record the actual output for the report; do not claim the proxy is faster based on one run or negative overhead caused by network variance.

## Cache design

- `OrderedDict` stores `cache key -> CacheEntry(response, created_at, ttl)`.
- Cache key is the canonical URL plus `Accept-Encoding`, because that header can change the returned representation.
- Each lookup checks whether the mapping contains the key and whether the entry is fresh. A valid entry increments `hits`; an absent or expired entry increments `misses`. Expired entries are removed.
- Successful `200` GET responses are eligible only when request and response policy permits reuse. Requests containing `Authorization` or `Cookie` bypass shared caching. `no-cache`/`no-store` requests bypass the cache. Responses with `no-store`, `no-cache`, `private`, `Set-Cookie`, `Vary: *`, or unsupported `Vary` headers are not stored.
- Origin `s-maxage`/`max-age` and `Expires` freshness are considered, capped by `PROXY_CACHE_TTL`; `Age` reduces max-age freshness.
- Every successful cache access moves the key to the newest end. When capacity is reached, the oldest key is evicted. A lock protects the shared mapping and counters.

## Scope and limitations

- One request per client connection; no persistent client keep-alive.
- HTTP chunked request bodies are rejected with `501` rather than forwarded incorrectly. Content-Length request bodies are supported within a configured limit.
- The cache intentionally supports a conservative subset of HTTP caching semantics; it does not implement conditional revalidation (`ETag`/`Last-Modified`) or every directive combination.
- A thread is created per accepted client. This is suitable for a course demo but is not a hardened high-scale server.
- HTTPS is tunneled only; the proxy cannot inspect encrypted URLs/headers inside TLS.

## Files

- `proxy.py` — server, parsing/forwarding, in-memory TTL/LRU cache, blocklist, CONNECT tunnel, and logging.
- `client.py`, `test_client.py` — manual functional clients.
- `test_lru.py`, `test_proxy.py` — unit tests.
- `performance_test.py` — fair direct/proxy latency and concurrency benchmark.
- `blocked_domains.txt` — access-control configuration.
- `PROJECT_DESCRIPTION.md` — concise architecture and design trade-offs.
- `Designing_a_Proxy_Server_Final_Report.docx` — project design/report.

## Suggested live-demo order

1. Start the proxy and show its listening log.
2. Request an allowed HTTP URL and show forwarding.
3. Repeat an origin-cacheable URL and show `CACHE MISS` then `CACHE HIT`.
4. Add a domain to the blocklist and show HTTP `403`.
5. Run unit tests and show the LRU/TTL results.
6. Run the benchmark and explain why no-cache requests are used for fair overhead measurement.
7. Optionally show a browser HTTPS request through CONNECT.
