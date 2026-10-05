import hashlib
import logging
import os
import socket
import threading
import time
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080
CACHE_DIR = "cache"
CACHE_TTL = 60
BLOCKED_DOMAINS_FILE = "blocked_domains.txt"
LOG_FILE = "proxy.log"
CLIENT_TIMEOUT = 10
CONNECT_TIMEOUT = 5
UPSTREAM_TIMEOUT = 10
MAX_HEADER_BYTES = 65536
BUFFER_SIZE = 8192

os.makedirs(CACHE_DIR, exist_ok=True)

logger = logging.getLogger("proxy")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)


def log_request(client_ip, method="-", url="-", status="-", cache="N/A", elapsed=0.0, detail="-"):
    logger.info(
        "client=%s | method=%s | url=%s | status=%s | cache=%s | response_time=%.4fs | detail=%s",
        client_ip, method, url, status, cache, elapsed, detail,
    )


def load_blocked_domains():
    blocked = set()
    try:
        with open(BLOCKED_DOMAINS_FILE, "r", encoding="utf-8") as file:
            for line in file:
                domain = line.partition("#")[0].strip().lower().rstrip(".")
                if domain:
                    blocked.add(domain)
    except FileNotFoundError:
        logger.warning("Blocked-domain file not found: %s", BLOCKED_DOMAINS_FILE)
    except OSError:
        logger.exception("Could not read blocked-domain file")
    return blocked


BLOCKED_DOMAINS = load_blocked_domains()


def is_blocked(host):
    host = (host or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in BLOCKED_DOMAINS)


cache_lock = threading.Lock()


def get_cache_path(url):
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, key + ".cache")


def read_cache(url):
    path = get_cache_path(url)
    with cache_lock:
        try:
            if not os.path.isfile(path):
                return None
            if time.time() - os.path.getmtime(path) >= CACHE_TTL:
                os.remove(path)
                logger.info("cache_expired url=%s", url)
                return None
            with open(path, "rb") as file:
                data = file.read()
            return data or None
        except OSError:
            logger.exception("cache_read_failed url=%s", url)
            return None


def save_cache(url, response):
    """Cache only HTTP 200 responses that do not opt out of caching."""
    header_end = response.find(b"\r\n\r\n")
    if header_end < 0 or not response.startswith(b"HTTP/"):
        return
    status_line = response.split(b"\r\n", 1)[0].split()
    if len(status_line) < 2 or status_line[1] != b"200":
        return
    headers = response[:header_end].lower()
    if (b"no-store" in headers or b"private" in headers or
            b"no-cache" in headers or b"set-cookie:" in headers or
            b"vary: *" in headers):
        return
    path = get_cache_path(url)
    temp_path = path + "." + str(threading.get_ident()) + ".tmp"
    with cache_lock:
        try:
            with open(temp_path, "wb") as file:
                file.write(response)
            os.replace(temp_path, path)
        except OSError:
            logger.exception("cache_write_failed url=%s", url)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                logger.exception("cache_temp_cleanup_failed url=%s", url)


REASONS = {
    400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed",
    431: "Request Header Fields Too Large", 500: "Internal Server Error",
    501: "Not Implemented", 502: "Bad Gateway", 504: "Gateway Timeout",
}


def send_error(client_socket, status, message=None):
    message = message or REASONS.get(status, "Error")
    body = (message + "\n").encode("utf-8")
    response = (
        f"HTTP/1.1 {status} {message}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    client_socket.sendall(response)


def receive_headers(client_socket):
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = client_socket.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("headers too large")
    if not data:
        return b""
    if b"\r\n\r\n" not in data:
        raise ValueError("incomplete HTTP headers")
    return bytes(data)


def parse_request(request_bytes):
    try:
        request_text = request_bytes.decode("iso-8859-1")
    except UnicodeDecodeError as exc:
        raise ValueError("invalid request encoding") from exc
    head = request_text.split("\r\n\r\n", 1)[0]
    lines = head.split("\r\n")
    parts = lines[0].split()
    if len(parts) != 3:
        raise ValueError("malformed request line")
    method, target, version = parts
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise ValueError("unsupported HTTP version")
    if method.upper() != "GET":
        raise NotImplementedError("only GET is supported")

    host_header = None
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        if ":" not in line:
            raise ValueError("malformed header")
        name, value = line.split(":", 1)
        name, value = name.strip(), value.strip()
        if not name:
            raise ValueError("empty header name")
        if name.lower() == "host":
            if host_header is not None:
                raise ValueError("duplicate Host header")
            host_header = value
        if name.lower() not in ("connection", "proxy-connection"):
            headers.append((name, value))

    if target.lower().startswith("https://"):
        raise NotImplementedError("HTTPS CONNECT tunneling is not supported")

    if target.lower().startswith("http://"):
        parsed = urlsplit(target)
        if parsed.scheme.lower() != "http" or not parsed.hostname:
            raise ValueError("invalid absolute URL")
        host = parsed.hostname
        try:
            port = parsed.port or 80
        except ValueError as exc:
            raise ValueError("invalid destination port") from exc
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
    else:
        if not target.startswith("/") or not host_header:
            raise ValueError("origin-form request requires a Host header")
        parsed_host = urlsplit("//" + host_header)
        if not parsed_host.hostname:
            raise ValueError("invalid Host header")
        host = parsed_host.hostname
        try:
            port = parsed_host.port or 80
        except ValueError as exc:
            raise ValueError("invalid Host port") from exc
        path = target

    if not (1 <= port <= 65535):
        raise ValueError("invalid destination port")
    if any(ch in host for ch in "\r\n\t "):
        raise ValueError("invalid hostname")
    return method.upper(), host.lower().rstrip("."), port, path, version, headers


def build_upstream_request(method, path, version, host, port, headers):
    lines = [f"{method} {path} {version}"]
    host_value = host if port == 80 else f"{host}:{port}"
    host_added = False
    for name, value in headers:
        if name.lower() == "host":
            if not host_added:
                lines.append(f"Host: {host_value}")
                host_added = True
        else:
            lines.append(f"{name}: {value}")
    if not host_added:
        lines.append(f"Host: {host_value}")
    lines.extend(("Connection: close", "", ""))
    return "\r\n".join(lines).encode("iso-8859-1")


def response_status(response):
    try:
        first_line = response.split(b"\r\n", 1)[0].decode("ascii", "replace")
        parts = first_line.split()
        if len(parts) >= 2 and parts[0].startswith("HTTP/"):
            return int(parts[1])
    except (ValueError, IndexError):
        pass
    return 502


def handle_client(client_socket, client_address):
    started = time.monotonic()
    client_ip = client_address[0]
    method, url, status, cache_state, detail = "-", "-", 500, "N/A", "internal_error"
    destination_socket = None
    request_logged = False

    def finish_log():
        nonlocal request_logged
        if not request_logged:
            log_request(client_ip, method, url, status, cache_state,
                        time.monotonic() - started, detail)
            request_logged = True

    try:
        client_socket.settimeout(CLIENT_TIMEOUT)
        raw_request = receive_headers(client_socket)
        if not raw_request:
            status, detail = 400, "empty_request"
            send_error(client_socket, status)
            return
        try:
            method, host, port, path, version, headers = parse_request(raw_request)
        except NotImplementedError as exc:
            status, detail = 501, str(exc)
            send_error(client_socket, status)
            return
        except ValueError as exc:
            status = 431 if "too large" in str(exc) else 400
            detail = str(exc)
            send_error(client_socket, status)
            return

        url = f"http://{host}:{port}{path}"
        if is_blocked(host):
            status, cache_state, detail = 403, "BLOCKED", "domain_blocked"
            send_error(client_socket, status)
            return

        # GET request bodies are outside this project's scope.
        remainder = raw_request.split(b"\r\n\r\n", 1)[1]
        if remainder.strip():
            status, detail = 400, "GET_request_body_not_supported"
            send_error(client_socket, status)
            return

        cached = read_cache(url)
        if cached is not None:
            status = response_status(cached)
            cache_state, detail = "HIT", "served_from_cache"
            client_socket.sendall(cached)
            return

        cache_state, detail = "MISS", "forwarded_to_origin"
        try:
            destination_socket = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
            destination_socket.settimeout(UPSTREAM_TIMEOUT)
            destination_socket.sendall(build_upstream_request(
                method, path, version, host, port, headers
            ))
            response_data = bytearray()
            while True:
                chunk = destination_socket.recv(BUFFER_SIZE)
                if not chunk:
                    break
                response_data.extend(chunk)
            if not response_data:
                status, detail = 502, "empty_origin_response"
                send_error(client_socket, status)
                return
            complete_response = bytes(response_data)
            status = response_status(complete_response)
            if status == 502:
                detail = "invalid_origin_status_line"
            save_cache(url, complete_response)
            client_socket.sendall(complete_response)
        except socket.timeout:
            status, detail = 504, "upstream_timeout"
            send_error(client_socket, status)
        except socket.gaierror:
            status, detail = 502, "destination_dns_failure"
            send_error(client_socket, status)
        except ConnectionRefusedError:
            status, detail = 502, "destination_connection_refused"
            send_error(client_socket, status)
        except OSError as exc:
            status, detail = 502, f"upstream_socket_error:{exc}"
            logger.exception("upstream socket error client=%s url=%s", client_ip, url)
            try:
                send_error(client_socket, status)
            except OSError:
                pass
    except socket.timeout:
        status, detail = 504, "client_or_header_timeout"
        try:
            send_error(client_socket, status)
        except OSError:
            pass
    except ValueError as exc:
        status, detail = 400, str(exc)
        try:
            send_error(client_socket, status)
        except OSError:
            pass
    except OSError as exc:
        status, detail = 502, f"client_socket_error:{exc}"
        logger.exception("client socket error client=%s", client_ip)
    except Exception as exc:
        status, detail = 500, f"unexpected_error:{type(exc).__name__}"
        logger.exception("unexpected handler error client=%s", client_ip)
        try:
            send_error(client_socket, status)
        except OSError:
            pass
    finally:
        finish_log()
        if destination_socket is not None:
            try:
                destination_socket.close()
            except OSError:
                pass
        try:
            client_socket.close()
        except OSError:
            pass


def serve_forever():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(50)
        print(f"Proxy server listening on {HOST}:{PORT}")
        print(f"Cache TTL: {CACHE_TTL} seconds")
        while True:
            client_socket, client_address = server_socket.accept()
            threading.Thread(
                target=handle_client,
                args=(client_socket, client_address),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        print("\nProxy server shutting down")
    finally:
        server_socket.close()


if __name__ == "__main__":
    serve_forever()
