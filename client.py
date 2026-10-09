import socket
from urllib.parse import urlsplit

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 8080


def request_via_proxy(url="http://example.com/"):
    """Send one HTTP GET request through the local proxy."""
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ValueError("Only valid HTTP URLs are supported.")
    host = parsed.hostname
    port = parsed.port or 80
    host_header = host if port == 80 else f"{host}:{port}"
    target = url.split("#", 1)[0]
    if not parsed.path:
        target = target.replace(parsed.netloc, parsed.netloc + "/", 1)
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=10) as client:
            client.settimeout(15)
            client.sendall(request)
            response = bytearray()
            while True:
                try:
                    chunk = client.recv(8192)
                except socket.timeout:
                    print("Timed out while receiving response.")
                    break
                if not chunk:
                    break
                response.extend(chunk)
        print(bytes(response).decode("iso-8859-1", errors="replace") if response
              else "No response received from the proxy.")
    except ConnectionRefusedError:
        print("Could not connect to the proxy. Make sure proxy.py is running.")
    except socket.timeout:
        print("Connection timed out.")
    except OSError as error:
        print(f"Network error: {error}")


if __name__ == "__main__":
    request_via_proxy()
