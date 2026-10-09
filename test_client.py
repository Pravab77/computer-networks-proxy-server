import socket
import time
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080
TIMEOUT = 15


def send_request(url="http://example.com/"):
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        print("Please provide a valid HTTP URL.")
        return b"", 0
    host = parsed.hostname
    port = parsed.port or 80
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = host if port == 80 else f"{host}:{port}"
    target = f"http://{host_header}{path}"
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    started = time.perf_counter()
    response = bytearray()
    try:
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as client:
            client.settimeout(TIMEOUT)
            client.sendall(request)
            while True:
                chunk = client.recv(8192)
                if not chunk:
                    break
                response.extend(chunk)
    except ConnectionRefusedError:
        print("Could not connect. Make sure proxy.py is running.")
        return b"", 0
    except socket.timeout:
        print("Client timed out while waiting for response.")
        return bytes(response), time.perf_counter() - started
    except OSError as error:
        print(f"Client error: {error}")
        return bytes(response), time.perf_counter() - started
    elapsed = time.perf_counter() - started
    raw = bytes(response)
    status_line = raw.split(b"\r\n", 1)[0].decode("iso-8859-1", "replace") if raw else "No response"
    print(f"Status: {status_line}")
    print(f"Elapsed: {elapsed:.4f}s")
    print(f"Bytes received: {len(raw)}")
    print(raw[:500].decode("iso-8859-1", "replace"))
    return raw, elapsed


if __name__ == "__main__":
    print("========== FIRST REQUEST (expected MISS) ==========")
    first, first_time = send_request()
    print("\n========== SECOND REQUEST (expected HIT if cacheable) ==========")
    second, second_time = send_request()
    if first and second:
        print("\nResponses byte-identical:", first == second)
    print(f"First request: {first_time:.4f}s")
    print(f"Second request: {second_time:.4f}s")
    print("Check proxy.log to confirm cache HIT/MISS.")
