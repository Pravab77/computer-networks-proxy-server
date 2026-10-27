"""Fair direct-vs-proxy benchmark and concurrent-load smoke test.

The overhead benchmark sends Cache-Control: no-cache to both paths so that the
proxy benchmark measures proxy overhead rather than comparing direct requests
with proxy cache hits. A separate optional warm-cache section checks cache speed
when the origin permits caching. Run against a URL you are allowed to test.
"""
import argparse
import http.client
import math
import os
import socket
import statistics
import threading
import time
from urllib.parse import urlsplit

PROXY_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8080"))
DEFAULT_URL = "http://example.com/"
DEFAULT_ROUNDS = 8
DEFAULT_CLIENTS = 10
DEFAULT_TIMEOUT = 15


def request_once(url, via_proxy, no_cache=True, timeout=DEFAULT_TIMEOUT):
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ValueError("Benchmark URL must be an HTTP URL (not HTTPS).")
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = host if port == 80 else f"{host}:{port}"
    connect_host, connect_port = (PROXY_HOST, PROXY_PORT) if via_proxy else (host, port)
    target = url if via_proxy else path
    headers = [f"GET {target} HTTP/1.1", f"Host: {host_header}", "Connection: close"]
    if no_cache:
        headers.append("Cache-Control: no-cache")
    payload = ("\r\n".join(headers) + "\r\n\r\n").encode("iso-8859-1")
    started = time.perf_counter()
    with socket.create_connection((connect_host, connect_port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        response = http.client.HTTPResponse(sock)
        response.begin()
        status = response.status
        body = response.read()
        reason = response.reason
        response.close()
    return {
        "elapsed": time.perf_counter() - started,
        "status": status,
        "reason": reason,
        "bytes": len(body),
        "body": body,
    }


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def summarize(label, results, errors, wall_seconds=None):
    print(f"\n{label}")
    print(f"  successful requests : {len(results)}")
    print(f"  failed requests     : {len(errors)}")
    if errors:
        for error in errors[:5]:
            print(f"    error: {error}")
    samples = [item["elapsed"] for item in results]
    if not samples:
        return None
    print(f"  min latency         : {min(samples):.4f}s")
    print(f"  mean latency        : {statistics.mean(samples):.4f}s")
    print(f"  median latency      : {statistics.median(samples):.4f}s")
    print(f"  p95 latency         : {percentile(samples, 0.95):.4f}s")
    print(f"  max latency         : {max(samples):.4f}s")
    if wall_seconds and wall_seconds > 0:
        print(f"  throughput          : {len(results) / wall_seconds:.2f} requests/s")
    status_counts = {}
    for item in results:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    print(f"  HTTP status counts  : {status_counts}")
    return statistics.mean(samples)


def sequential_benchmark(url, rounds, timeout):
    print("\n========== DIRECT VS PROXY (CACHE BYPASSED) ==========")
    direct, proxy, errors = [], [], []
    # Alternate order to reduce systematic timing bias.
    for index in range(rounds):
        modes = (False, True) if index % 2 == 0 else (True, False)
        for via_proxy in modes:
            label = "proxy" if via_proxy else "direct"
            try:
                result = request_once(url, via_proxy, no_cache=True, timeout=timeout)
                if not 200 <= result["status"] < 400:
                    errors.append(f"{label} returned HTTP {result['status']}")
                else:
                    (proxy if via_proxy else direct).append(result)
            except (OSError, socket.timeout, ValueError, http.client.HTTPException) as error:
                errors.append(f"{label}: {error}")
    direct_mean = summarize("Direct connection", direct, [e for e in errors if e.startswith("direct")])
    proxy_mean = summarize("Proxy connection (Cache-Control: no-cache)", proxy,
                           [e for e in errors if e.startswith("proxy")])
    if direct_mean is not None and proxy_mean is not None:
        delta = proxy_mean - direct_mean
        pct = (delta / direct_mean * 100) if direct_mean > 0 else 0.0
        print(f"\nMean proxy overhead: {delta:+.4f}s ({pct:+.2f}%)")
        if delta < 0:
            print("Note: a negative result is possible from network variance; it does not prove the proxy is inherently faster.")
    else:
        print("Overhead not calculated because one side had no successful samples.")


def concurrent_benchmark(url, clients, timeout):
    print("\n========== CONCURRENT LOAD ==========")
    for via_proxy in (False, True):
        label = "Proxy" if via_proxy else "Direct"
        results, errors = [], []
        lock = threading.Lock()

        def worker(index):
            try:
                item = request_once(url, via_proxy, no_cache=True, timeout=timeout)
                with lock:
                    if 200 <= item["status"] < 400:
                        results.append(item)
                    else:
                        errors.append(f"client {index}: HTTP {item['status']}")
            except (OSError, socket.timeout, ValueError, http.client.HTTPException) as error:
                with lock:
                    errors.append(f"client {index}: {error}")

        started = time.perf_counter()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, clients + 1)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout + 2)
        wall = time.perf_counter() - started
        summarize(f"{label}: {clients} concurrent clients; wall={wall:.4f}s", results, errors, wall)


def warm_cache_check(url, timeout):
    print("\n========== OPTIONAL CACHE HIT CHECK ==========")
    first = request_once(url, True, no_cache=False, timeout=timeout)
    second = request_once(url, True, no_cache=False, timeout=timeout)
    print(f"First request : HTTP {first['status']}, {first['elapsed']:.4f}s, {first['bytes']} body bytes")
    print(f"Second request: HTTP {second['status']}, {second['elapsed']:.4f}s, {second['bytes']} body bytes")
    print("Same status/body size:", first["status"] == second["status"] and first["bytes"] == second["bytes"])
    print("Check proxy.log for CACHE HIT / CACHE MISS / CACHE STORED. The origin may forbid caching.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help=f"HTTP URL to test (default: {DEFAULT_URL})")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="sequential paired samples")
    parser.add_argument("--clients", type=int, default=DEFAULT_CLIENTS, help="simultaneous clients per load test")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="request timeout in seconds")
    parser.add_argument("--skip-concurrency", action="store_true", help="skip concurrent load tests")
    parser.add_argument("--skip-cache-check", action="store_true", help="skip optional warm-cache check")
    args = parser.parse_args()
    if args.rounds < 1 or args.clients < 1:
        parser.error("--rounds and --clients must be at least 1")
    print(f"URL: {args.url}\nProxy: {PROXY_HOST}:{PROXY_PORT}\nRounds: {args.rounds}; concurrent clients: {args.clients}")
    sequential_benchmark(args.url, args.rounds, args.timeout)
    if not args.skip_concurrency:
        concurrent_benchmark(args.url, args.clients, args.timeout)
    if not args.skip_cache_check:
        try:
            warm_cache_check(args.url, args.timeout)
        except (OSError, socket.timeout, ValueError, http.client.HTTPException) as error:
            print(f"Optional cache check failed: {error}")


if __name__ == "__main__":
    main()
