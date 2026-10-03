


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

os.makedirs(CACHE_DIR, exist_ok=True)


# Load blocked domains
def load_blocked_domains():
    blocked_domains = set()

    try:
        with open("blocked_domains.txt", "r") as file:
            for line in file:
                domain = line.strip().lower()

                if domain:
                    blocked_domains.add(domain)

    except FileNotFoundError:
        print("blocked_domains.txt not found")

    return blocked_domains


BLOCKED_DOMAINS = load_blocked_domains()


# Create log file
logging.basicConfig(
    filename="proxy.log",
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)


# Lock for cache access
cache_lock = threading.Lock()


# Generate a unique cache file for each URL
def get_cache_path(url):
    url_hash = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()

    return os.path.join(
        CACHE_DIR,
        url_hash + ".cache"
    )


# Read response from cache
def read_cache(url):
    cache_path = get_cache_path(url)

    with cache_lock:

        if not os.path.exists(cache_path):
            return None

        try:
            modified_time = os.path.getmtime(cache_path)

            cache_age = time.time() - modified_time

            if cache_age >= CACHE_TTL:
                os.remove(cache_path)

                print("CACHE EXPIRED")

                return None

            with open(cache_path, "rb") as file:
                cached_response = file.read()

            print(f"Cache age: {cache_age:.2f} seconds")

            return cached_response

        except OSError as error:
            print(f"Cache read error: {error}")

            return None


# Save response to cache
def save_cache(url, response):

    if not response.startswith(b"HTTP/"):
        return

    header_end = response.find(b"\r\n\r\n")

    if header_end == -1:
        return

    headers = response[:header_end].lower()

    status_line = response.split(
        b"\r\n",
        1
    )[0].split()

    # Cache only HTTP 200 responses
    if len(status_line) < 2 or status_line[1] != b"200":
        return

    # Do not cache these responses
    if (
        b"no-store" in headers
        or b"private" in headers
        or b"no-cache" in headers
    ):
        print("Response is not suitable for caching")

        return

    cache_path = get_cache_path(url)

    temp_path = cache_path + ".tmp"

    with cache_lock:

        try:

            with open(temp_path, "wb") as file:
                file.write(response)

            os.replace(
                temp_path,
                cache_path
            )

            print("Response saved to cache")

        except OSError as error:

            print(f"Cache write error: {error}")

        finally:

            if os.path.exists(temp_path):

                try:
                    os.remove(temp_path)

                except OSError:
                    pass


# Send an HTTP error response
def send_error(client_socket, status, message):

    response = (
        f"HTTP/1.1 {status} {message}\r\n"
        f"Content-Type: text/plain\r\n"
        f"Content-Length: "
        f"{len(message.encode('utf-8'))}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{message}"
    )

    client_socket.sendall(
        response.encode("utf-8")
    )


# Connect to destination server
def connect_to_destination(host, port=80):

    try:

        destination_socket = socket.create_connection(
            (host, port),
            timeout=5
        )

        destination_socket.settimeout(10)

        print(
            f"Connected to {host}:{port}"
        )

        return destination_socket

    except socket.timeout:

        print("Connection timed out")

    except socket.gaierror:

        print(
            "Could not find the destination server"
        )

    except OSError as error:

        print(
            f"Connection failed: {error}"
        )

    return None


# Handle each client
def handle_client(
    client_socket,
    client_address
):

    destination_socket = None

    start_time = time.time()

    try:

        print(
            f"\nClient connected: "
            f"{client_address}"
        )

        client_socket.settimeout(10)

        # Receive HTTP request
        request = client_socket.recv(4096)

        if not request:
            return

        request = request.decode(
            "latin-1"
        )

        print("HTTP Request:")
        print(request)

        # Parse request
        lines = request.split("\r\n")

        parts = lines[0].split()

        if len(parts) != 3:

            print("Malformed HTTP request")

            send_error(
                client_socket,
                400,
                "Bad Request"
            )

            return

        method = parts[0]

        target = parts[1]

        version = parts[2]

        # Only GET supported
        if method != "GET":

            send_error(
                client_socket,
                501,
                "Not Implemented"
            )

            return

        # Read headers
        host = ""

        headers = []

        for line in lines[1:]:

            if not line:
                break

            if line.lower().startswith(
                "host:"
            ):

                host = line.split(
                    ":",
                    1
                )[1].strip()

            headers.append(line)

        # Parse absolute URL
        if target.startswith("http://"):

            url = urlsplit(target)

            host = url.hostname

            if not host:

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

            try:

                port = url.port or 80

            except ValueError:

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

            if url.scheme.lower() != "http":

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

            path = url.path or "/"

            if url.query:

                path += "?" + url.query

        # Parse origin-form request
        else:

            path = target

            if not host:

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

            try:

                host_info = urlsplit(
                    "//" + host
                )

                host = host_info.hostname

                port = host_info.port or 80

            except ValueError:

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

            if not host or not path.startswith("/"):

                send_error(
                    client_socket,
                    400,
                    "Bad Request"
                )

                return

        print("Method:", method)

        print("Host:", host)

        print("Path:", path)


        # -------------------------
        # DAY 11: DOMAIN BLOCKING
        # -------------------------

        if host.lower() in BLOCKED_DOMAINS:

            print(
                "BLOCKED:",
                host
            )

            logging.info(
                f"client={client_address[0]} | "
                f"method={method} | "
                f"url=http://{host}{path} | "
                f"status=403 | "
                f"cache=BLOCKED"
            )

            send_error(
                client_socket,
                403,
                "Forbidden"
            )

            return


        # Create cache URL
        cache_url = (
            f"http://"
            f"{host.lower()}:"
            f"{port}"
            f"{path}"
        )


        # -------------------------
        # DAY 10: CACHE CHECK
        # -------------------------

        cached_response = read_cache(
            cache_url
        )

        if cached_response is not None:

            print("CACHE HIT")

            logging.info(
                f"client={client_address[0]} | "
                f"method={method} | "
                f"url={cache_url} | "
                f"status=200 | "
                f"cache=HIT"
            )

            client_socket.sendall(
                cached_response
            )

            return


        print("CACHE MISS")

        logging.info(
            f"client={client_address[0]} | "
            f"method={method} | "
            f"url={cache_url} | "
            f"cache=MISS"
        )


        # Connect to destination
        destination_socket = (
            connect_to_destination(
                host,
                port
            )
        )

        if destination_socket is None:

            send_error(
                client_socket,
                502,
                "Bad Gateway"
            )

            logging.info(
                f"client={client_address[0]} | "
                f"method={method} | "
                f"url={cache_url} | "
                f"status=502"
            )

            return


        # Create request for destination
        new_request = (
            f"{method} "
            f"{path} "
            f"{version}\r\n"
        )

        host_header_added = False


        for line in headers:

            lower_line = line.lower()

            # Remove connection header
            if lower_line.startswith(
                "connection:"
            ):
                continue

            # Remove proxy connection header
            if lower_line.startswith(
                "proxy-connection:"
            ):
                continue

            # Replace Host header
            if lower_line.startswith(
                "host:"
            ):

                new_request += (
                    f"Host: {host}\r\n"
                )

                host_header_added = True

                continue

            new_request += (
                line + "\r\n"
            )


        # Add Host header if missing
        if not host_header_added:

            new_request += (
                f"Host: {host}\r\n"
            )


        # Close connection after response
        new_request += (
            "Connection: close\r\n"
            "\r\n"
        )


        # Forward request
        destination_socket.sendall(
            new_request.encode(
                "latin-1"
            )
        )

        print(
            "Request forwarded "
            "to destination"
        )


        # Receive response
        response_data = bytearray()

        while True:

            response = (
                destination_socket.recv(
                    4096
                )
            )

            if not response:
                break

            response_data.extend(
                response
            )


        complete_response = bytes(
            response_data
        )


        # Save response to cache
        save_cache(
            cache_url,
            complete_response
        )


        # Send response to client
        if complete_response:

            client_socket.sendall(
                complete_response
            )

            print(
                "Response forwarded "
                "to client"
            )

            response_time = (
                time.time() - start_time
            )

            logging.info(
                f"client={client_address[0]} | "
                f"method={method} | "
                f"url={cache_url} | "
                f"status=200 | "
                f"cache=MISS | "
                f"response_time="
                f"{response_time:.4f}s"
            )

        else:

            send_error(
                client_socket,
                502,
                "Bad Gateway"
            )


    except socket.timeout:

        print(
            "Connection timed out"
        )

        try:

            send_error(
                client_socket,
                504,
                "Gateway Timeout"
            )

        except OSError:
            pass


    except OSError as error:

        print(
            f"Error: {error}"
        )


    finally:

        if destination_socket:

            destination_socket.close()

        client_socket.close()

        print(
            f"Client disconnected: "
            f"{client_address}"
        )


# -------------------------
# CREATE PROXY SERVER
# -------------------------

server_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

server_socket.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server_socket.bind(
    (HOST, PORT)
)

server_socket.listen(5)

print(
    f"Proxy server listening "
    f"on {HOST}:{PORT}"
)

print(
    f"Cache TTL: "
    f"{CACHE_TTL} seconds"
)


# -------------------------
# DAY 8: MULTIPLE CLIENTS
# -------------------------

try:

    while True:

        client_socket, client_address = (
            server_socket.accept()
        )

        client_thread = threading.Thread(
            target=handle_client,
            args=(
                client_socket,
                client_address
            )
        )

        client_thread.start()


except KeyboardInterrupt:

    print(
        "\nProxy server shutting down"
    )


finally:

    server_socket.close()

