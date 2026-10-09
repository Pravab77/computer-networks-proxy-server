import socket
import threading
import os
import hashlib
import time
import logging
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080

CACHE_DIR = "cache"
CACHE_TTL = 60
CACHE_MAX_ENTRIES = 100
BLOCKED_DOMAINS_FILE = "blocked_domains.txt"
LOG_FILE = "proxy.log"

MAX_HEADER_SIZE = 16384

os.makedirs(CACHE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

cache_lock = threading.Lock()


# -------------------- CACHE FUNCTIONS --------------------

def get_cache_path(url):
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, url_hash + ".cache")


def enforce_cache_limit():
    current_time = time.time()
    cache_files = []

    try:
        filenames = os.listdir(CACHE_DIR)
    except OSError as error:
        logging.error("Could not list cache directory: %s", error)
        return

    for filename in filenames:
        if not filename.endswith(".cache"):
            continue

        path = os.path.join(CACHE_DIR, filename)

        try:
            file_info = os.stat(path)
            age = current_time - file_info.st_mtime

            if age >= CACHE_TTL:
                os.remove(path)
                logging.info("CACHE EXPIRED: %s", filename)
            else:
                cache_files.append((file_info.st_atime, path))

        except OSError as error:
            logging.warning("Cache cleanup error: %s", error)

    # Least recently used files are removed first.
    cache_files.sort(key=lambda item: item[0])

    while len(cache_files) > CACHE_MAX_ENTRIES:
        _, oldest_path = cache_files.pop(0)

        try:
            os.remove(oldest_path)
            logging.info("LRU EVICTED: %s", os.path.basename(oldest_path))
        except OSError as error:
            logging.warning("LRU eviction error: %s", error)


def read_cache(url):
    cache_path = get_cache_path(url)

    with cache_lock:
        if not os.path.exists(cache_path):
            return None

        try:
            file_info = os.stat(cache_path)
            modified_time = file_info.st_mtime

            if time.time() - modified_time >= CACHE_TTL:
                os.remove(cache_path)
                logging.info("CACHE EXPIRED")
                return None

            with open(cache_path, "rb") as file:
                response = file.read()

            # Update access time without changing TTL.
            os.utime(cache_path, (time.time(), modified_time))

            return response

        except OSError as error:
            logging.error("Cache read error: %s", error)
            return None


def save_cache(url, response):
    if not response.startswith(b"HTTP/"):
        return

    header_end = response.find(b"\r\n\r\n")

    if header_end == -1:
        return

    headers = response[:header_end].lower()
    status_line = response.split(b"\r\n", 1)[0].split()

    # Cache only HTTP 200 responses.
    if len(status_line) < 2 or status_line[1] != b"200":
        return

    # Do not cache private or non-cacheable responses.
    if (
        b"no-store" in headers
        or b"private" in headers
        or b"no-cache" in headers
        or b"set-cookie:" in headers
        or b"vary: *" in headers
    ):
        logging.info("Response is not suitable for caching")
        return

    cache_path = get_cache_path(url)
    temp_path = cache_path + ".tmp"

    with cache_lock:
        try:
            with open(temp_path, "wb") as file:
                file.write(response)

            os.replace(temp_path, cache_path)
            enforce_cache_limit()

            logging.info("Response saved to cache")

        except OSError as error:
            logging.error("Cache write error: %s", error)

        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


# -------------------- DOMAIN BLOCKING --------------------

def load_blocked_domains():
    blocked = set()

    if not os.path.exists(BLOCKED_DOMAINS_FILE):
        try:
            with open(BLOCKED_DOMAINS_FILE, "w", encoding="utf-8") as file:
                file.write(
                    "# Add one domain per line.\n"
                    "# Example: example.com\n"
                )
        except OSError as error:
            logging.error("Could not create blocklist: %s", error)

        return blocked

    try:
        with open(BLOCKED_DOMAINS_FILE, "r", encoding="utf-8") as file:
            for line in file:
                domain = line.strip().lower()

                if domain and not domain.startswith("#"):
                    blocked.add(domain.lstrip("."))

    except OSError as error:
        logging.error("Could not read blocklist: %s", error)

    return blocked


def is_blocked(host):
    host = (host or "").lower().rstrip(".")

    for domain in load_blocked_domains():
        if host == domain or host.endswith("." + domain):
            return True

    return False


# -------------------- HTTP HELPERS --------------------

def send_error(client_socket, status, message):
    body = message.encode("utf-8")

    response = (
        f"HTTP/1.1 {status} {message}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("latin-1") + body

    client_socket.sendall(response)


def receive_request(client_socket):
    """Receive the complete HTTP header or reject oversized headers."""
    data = bytearray()

    while b"\r\n\r\n" not in data:
        remaining = MAX_HEADER_SIZE - len(data)

        if remaining <= 0:
            raise ValueError("Request headers too large")

        chunk = client_socket.recv(min(4096, remaining))

        if not chunk:
            break

        data.extend(chunk)

    if len(data) >= MAX_HEADER_SIZE and b"\r\n\r\n" not in data:
        raise ValueError("Request headers too large")

    if b"\r\n\r\n" not in data:
        raise ValueError("Incomplete HTTP request")

    return bytes(data)


def connect_to_destination(host, port=80):
    try:
        destination_socket = socket.create_connection(
            (host, port),
            timeout=5
        )

        destination_socket.settimeout(10)

        logging.info("Connected to destination %s:%s", host, port)

        return destination_socket

    except socket.timeout:
        logging.warning("Connection timed out: %s:%s", host, port)

    except socket.gaierror:
        logging.warning("Could not resolve host: %s", host)

    except OSError as error:
        logging.warning(
            "Connection failed to %s:%s: %s",
            host, port, error
        )

    return None


# -------------------- CLIENT HANDLER --------------------

def handle_client(client_socket, client_address):
    destination_socket = None
    start_time = time.time()

    request_url = "-"
    status_for_log = "unknown"
    cache_state = "not checked"

    try:
        logging.info("Client connected: %s", client_address)

        client_socket.settimeout(10)

        # Receive the full HTTP header.
        try:
            request_bytes = receive_request(client_socket)
        except ValueError as error:
            send_error(client_socket, 431, "Request Header Fields Too Large")
            status_for_log = 431
            logging.warning("%s from %s", error, client_address)
            return

        if not request_bytes:
            return

        header_end = request_bytes.find(b"\r\n\r\n")
        header_bytes = request_bytes[:header_end]
        request = header_bytes.decode("latin-1")

        lines = request.split("\r\n")
        parts = lines[0].split()

        if len(parts) != 3:
            send_error(client_socket, 400, "Bad Request")
            status_for_log = 400
            return

        method, target, version = parts

        # This proxy supports GET requests only.
        if method.upper() != "GET":
            send_error(client_socket, 501, "Not Implemented")
            status_for_log = 501
            return

        if version not in ("HTTP/1.0", "HTTP/1.1"):
            send_error(client_socket, 400, "Bad Request")
            status_for_log = 400
            return

        headers = []
        host_header = ""

        for line in lines[1:]:
            if not line:
                break

            if line.lower().startswith("host:"):
                host_header = line.split(":", 1)[1].strip()

            headers.append(line)

        # Parse the URL.
        if target.lower().startswith("http://"):
            try:
                url = urlsplit(target)

                if url.scheme.lower() != "http" or not url.hostname:
                    raise ValueError("Invalid URL")

                host = url.hostname
                port = url.port or 80

                path = url.path or "/"

                if url.query:
                    path += "?" + url.query

            except ValueError:
                send_error(client_socket, 400, "Bad Request")
                status_for_log = 400
                return

        else:
            # Handle requests such as GET /index.html HTTP/1.1.
            path = target

            if not host_header:
                send_error(client_socket, 400, "Bad Request")
                status_for_log = 400
                return

            try:
                host_info = urlsplit("//" + host_header)

                host = host_info.hostname
                port = host_info.port or 80

            except ValueError:
                send_error(client_socket, 400, "Bad Request")
                status_for_log = 400
                return

            if not host or not path.startswith("/"):
                send_error(client_socket, 400, "Bad Request")
                status_for_log = 400
                return

        host = host.lower().rstrip(".")

        # Include the port when it is not the default HTTP port.
        if port == 80:
            request_url = f"http://{host}{path}"
        else:
            request_url = f"http://{host}:{port}{path}"

        logging.info(
            "Method: %s | Host: %s | Path: %s",
            method, host, path
        )

        # Check domain blocking before checking the cache.
        if is_blocked(host):
            logging.warning("BLOCKED domain: %s", host)

            send_error(client_socket, 403, "Forbidden")
            status_for_log = 403
            return

        # Check cache.
        cached_response = read_cache(request_url)

        if cached_response is not None:
            cache_state = "HIT"

            logging.info("CACHE HIT: %s", request_url)

            client_socket.sendall(cached_response)

            try:
                status_for_log = (
                    cached_response.split(b"\r\n", 1)[0]
                    .split()[1].decode("ascii")
                )
            except (IndexError, UnicodeDecodeError):
                status_for_log = "cached"

            return

        cache_state = "MISS"

        logging.info("CACHE MISS: %s", request_url)

        # Connect to the destination.
        destination_socket = connect_to_destination(host, port)

        if destination_socket is None:
            send_error(client_socket, 502, "Bad Gateway")
            status_for_log = 502
            return

        # Forward the request to the destination.
        new_request = f"{method} {path} {version}\r\n"

        host_value = host if port == 80 else f"{host}:{port}"
        new_request += f"Host: {host_value}\r\n"

        for line in headers:
            lower_line = line.lower()

            if lower_line.startswith("host:"):
                continue

            if lower_line.startswith("connection:"):
                continue

            if lower_line.startswith("proxy-connection:"):
                continue

            new_request += line + "\r\n"

        new_request += "Connection: close\r\n\r\n"

        destination_socket.sendall(new_request.encode("latin-1"))

        logging.info("Request forwarded to destination")

        # Receive the destination response.
        response_data = bytearray()

        while True:
            try:
                chunk = destination_socket.recv(4096)
            except socket.timeout:
                logging.warning("Destination response timed out")
                break

            if not chunk:
                break

            response_data.extend(chunk)

        complete_response = bytes(response_data)

        if not complete_response:
            send_error(client_socket, 502, "Bad Gateway")
            status_for_log = 502
            return

        # Cache suitable responses and return the response to the client.
        save_cache(request_url, complete_response)

        client_socket.sendall(complete_response)

        logging.info("Response forwarded to client")

        try:
            status_for_log = (
                complete_response.split(b"\r\n", 1)[0]
                .split()[1].decode("ascii")
            )
        except (IndexError, UnicodeDecodeError):
            status_for_log = "unknown"

    except socket.timeout:
        logging.warning("Client request timed out: %s", client_address)

        status_for_log = 504

        try:
            send_error(client_socket, 504, "Gateway Timeout")
        except OSError:
            pass

    except OSError as error:
        logging.error(
            "Error handling client %s: %s",
            client_address, error
        )

        status_for_log = "connection error"

        try:
            send_error(client_socket, 502, "Bad Gateway")
        except OSError:
            pass

    finally:
        if destination_socket is not None:
            try:
                destination_socket.close()
            except OSError:
                pass

        try:
            client_socket.close()
        except OSError:
            pass

        elapsed = time.time() - start_time

        logging.info(
            "Client disconnected: %s | URL: %s | Status: %s | "
            "Cache: %s | Time: %.3fs",
            client_address,
            request_url,
            status_for_log,
            cache_state,
            elapsed
        )


# -------------------- START PROXY SERVER --------------------

def main():
    server_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    server_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(50)

        logging.info(
            "Proxy server listening on %s:%s",
            HOST, PORT
        )

        logging.info("Cache TTL: %s seconds", CACHE_TTL)
        logging.info("Maximum cache entries: %s", CACHE_MAX_ENTRIES)
        logging.info("Blocked domains file: %s", BLOCKED_DOMAINS_FILE)

        while True:
            client_socket, client_address = server_socket.accept()

            client_thread = threading.Thread(
                target=handle_client,
                args=(client_socket, client_address),
                daemon=True
            )

            client_thread.start()

    except KeyboardInterrupt:
        logging.info("Proxy server shutting down")

    except OSError as error:
        logging.error("Proxy server error: %s", error)

    finally:
        server_socket.close()


if __name__ == "__main__":
    main()