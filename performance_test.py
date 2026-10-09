"""Day 14: performance and concurrency validation for the HTTP proxy."""
import socket
import statistics
import threading
import time
from urllib.parse import urlsplit

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080
TEST_URL = "http://example.com/"
ROUNDS = 5
CONCURRENT_CLIENTS = 10
TIMEOUT = 15


def request_parts(url):
    p = urlsplit(url)
    if p.scheme.lower() != "http" or not p.hostname:
        raise ValueError("Only HTTP URLs are supported")
    port = p.port or 80
    path = p.path or "/"
    if p.query:
        path += "?" + p.query
    host_header = p.hostname if port == 80 else f"{p.hostname}:{port}"
    request = (f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n").encode("ascii")
    return p.hostname, port, request


def fetch_direct(url):
    host, port, request = request_parts(url)
    started = time.perf_counter()
    with socket.create_connection((host, port), timeout=TIMEOUT) as sock:
        sock.settimeout(TIMEOUT)
        sock.sendall(request)
        data = bytearray()
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data.extend(chunk)
    return time.perf_counter() - started, bytes(data)


def fetch_proxy(url):
    _, _, _ = request_parts(url)
    p = urlsplit(url)
    port = p.port or 80
    host_header = p.hostname if port == 80 else f"{p.hostname}:{port}"
    request = (f"GET {url} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n").encode("ascii")
    started = time.perf_counter()
    with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=TIMEOUT) as sock:
        sock.settimeout(TIMEOUT)
        sock.sendall(request)
        data = bytearray()
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            data.extend(chunk)
    return time.perf_counter() - started, bytes(data)


def status(data):
    return data.split(b"\r\n", 1)[0].decode("iso-8859-1", "replace") if data else "NO RESPONSE"


def stats(label, samples):
    if not samples:
        print(f"{label}: no successful samples")
        return
    print(f"\n{label}")
    print(f"  samples : {len(samples)}")
    print(f"  min     : {min(samples):.4f}s")
    print(f"  mean    : {statistics.mean(samples):.4f}s")
    print(f"  median  : {statistics.median(samples):.4f}s")
    print(f"  max     : {max(samples):.4f}s")


def sequential_test():
    direct, proxy = [], []
    print("\n========== DAY 14: PERFORMANCE ==========")
    for i in range(ROUNDS):
        try:
            elapsed, data = fetch_direct(TEST_URL)
            if data:
                direct.append(elapsed)
        except (OSError, ValueError) as exc:
            print(f"Direct request {i + 1} failed: {exc}")
    for i in range(ROUNDS):
        try:
            elapsed, data = fetch_proxy(TEST_URL)
            if data:
                proxy.append(elapsed)
                print(f"Proxy request {i + 1}: {status(data)} | {elapsed:.4f}s")
        except (OSError, ValueError) as exc:
            print(f"Proxy request {i + 1} failed: {exc}")
    stats("Direct connection", direct)
    stats("Proxy connection", proxy)
    if direct and proxy:
        d, p = statistics.mean(direct), statistics.mean(proxy)
        overhead = p - d
        pct = (overhead / d * 100) if d else 0
        print(f"\nProxy overhead: {overhead:.4f}s ({pct:.2f}%)")


def concurrency_test():
    print("\n========== DAY 14: CONCURRENCY ==========")
    results, errors = [], []
    lock = threading.Lock()

    def worker(i):
        try:
            elapsed, data = fetch_proxy(TEST_URL)
            with lock:
                results.append((i, elapsed, len(data), status(data)))
        except (OSError, ValueError) as exc:
            with lock:
                errors.append((i, str(exc)))

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, CONCURRENT_CLIENTS + 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = time.perf_counter() - started

    print(f"Total wall-clock time: {total:.4f}s")
    print(f"Successful clients: {len(results)}")
    print(f"Failed clients: {len(errors)}")
    for i, elapsed, size, code in sorted(results):
        print(f"Client {i:02d}: {code} | {elapsed:.4f}s | {size} bytes")
    for i, error in errors:
        print(f"Client {i:02d} ERROR: {error}")


if __name__ == "__main__":
    sequential_test()
    concurrency_test()
