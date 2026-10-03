
import socket
import threading
import os
import hashlib
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080

CACHE_DIR = "cache"
os.makedirs(CACHE_DIR, exist_ok=True)

cache_lock = threading.Lock()


# Generate a unique cache file for each URL
def get_cache_path(url):
    url_hash = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()

    return os.path.join(CACHE_DIR, url_hash + ".cache")


# Read response from cache
def read_cache(url):
    cache_path = get_cache_path(url)

    with cache_lock:
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as file:
                    return file.read()
            except OSError as error:
                print(f"Cache read error: {error}")

    return None


# Save successful response to cache
def save_cache(url, response):
    if not response.startswith(b"HTTP/"):
        return

    header_end = response.find(b"\r\n\r\n")

    if header_end == -1:
        return

    headers = response[:header_end].lower()
    status_line = response.split(b"\r\n", 1)[0].split()

    # Cache only HTTP 200 responses
    if len(status_line) < 2 or status_line[1] != b"200":
        return

    # Avoid caching responses that explicitly prohibit it
    if b"no-store" in headers or b"private" in headers:
        return

    cache_path = get_cache_path(url)
    temp_path = cache_path + ".tmp"

    with cache_lock:
        try:
            with open(temp_path, "wb") as file:
                file.write(response)

            os.replace(temp_path, cache_path)
            print("Response saved to cache")

        except OSError as error:
            print(f"Cache write error: {error}")

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


# Connect to destination server
def connect_to_destination(host, port=80):
    try:
        destination_socket = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        destination_socket.settimeout(5)
        destination_socket.connect((host, port))

        print(f"Connected to {host}:{port}")

        return destination_socket

    except socket.timeout:
        print("Connection timed out")

    except socket.gaierror:
        print("Could not find the destination server")

    except OSError as error:
        print(f"Connection failed: {error}")

    return None


# Handle each client request
def handle_client(client_socket, client_address):
    destination_socket = None

    try:
        print(f"\nClient connected: {client_address}")

        client_socket.settimeout(10)

        # Receive HTTP request
        request = client_socket.recv(4096)

        if not request:
            return

        request = request.decode("latin-1")

        print("HTTP Request:")
        print(request)

        # Parse request line
        lines = request.split("\r\n")
        parts = lines[0].split()

        if len(parts) != 3:
            print("Malformed HTTP request")

            client_socket.sendall(
                b"HTTP/1.1 400 Bad Request\r\n"
                b"Connection: close\r\n\r\n"
            )
            return

        method, target, version = parts

        # This proxy currently supports GET only
        if method != "GET":
            client_socket.sendall(
                b"HTTP/1.1 501 Not Implemented\r\n"
                b"Connection: close\r\n\r\n"
            )
            return

        # Read request headers
        host = ""
        headers = []

        for line in lines[1:]:
            if not line:
                break

            if line.lower().startswith("host:"):
                host = line.split(":", 1)[1].strip()

            headers.append(line)

        # Parse absolute URL or origin-form target
        if target.startswith("http://"):
            url = urlsplit(target)

            host = url.hostname

            if not host:
                client_socket.sendall(
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Connection: close\r\n\r\n"
                )
                return

            port = url.port or 80
            path = url.path or "/"

            if url.query:
                path += "?" + url.query

        else:
            path = target
            port = 80

            if not host:
                client_socket.sendall(
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Connection: close\r\n\r\n"
                )
                return

            try:
                host_info = urlsplit("//" + host)
                host = host_info.hostname
                port = host_info.port or 80

            except ValueError:
                client_socket.sendall(
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Connection: close\r\n\r\n"
                )
                return

            if not host:
                client_socket.sendall(
                    b"HTTP/1.1 400 Bad Request\r\n"
                    b"Connection: close\r\n\r\n"
                )
                return

        print("Method:", method)
        print("Host:", host)
        print("Path:", path)

        # Create cache key from destination URL
        cache_url = f"http://{host.lower()}:{port}{path}"

        # Check cache before connecting to destination
        cached_response = read_cache(cache_url)

        if cached_response is not None:
            print("CACHE HIT")

            client_socket.sendall(cached_response)
            return

        print("CACHE MISS")

        # Connect to destination server
        destination_socket = connect_to_destination(host, port)

        if destination_socket is None:
            client_socket.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\n"
                b"Connection: close\r\n\r\n"
            )
            return

        # Build HTTP request for destination server
        new_request = f"{method} {path} {version}\r\n"

        for line in headers:
            if line.lower().startswith("connection:"):
                continue

            if line.lower().startswith("proxy-connection:"):
                continue

            new_request += line + "\r\n"

        new_request += "Connection: close\r\n\r\n"

        # Forward request to destination
        destination_socket.sendall(
            new_request.encode("latin-1")
        )

        print("Request forwarded to destination")

        # Receive complete response
        response_data = bytearray()

        while True:
            response = destination_socket.recv(4096)

            if not response:
                break

            response_data.extend(response)

        complete_response = bytes(response_data)

        # Save response to file cache
        save_cache(cache_url, complete_response)

        # Send response to client
        if complete_response:
            client_socket.sendall(complete_response)

        print("Response forwarded to client")

    except socket.timeout:
        print("Connection timed out")

        try:
            client_socket.sendall(
                b"HTTP/1.1 504 Gateway Timeout\r\n"
                b"Connection: close\r\n\r\n"
            )
        except OSError:
            pass

    except OSError as error:
        print(f"Error: {error}")

    finally:
        if destination_socket:
            destination_socket.close()

        client_socket.close()

        print(f"Client disconnected: {client_address}")


# Create proxy server
server_socket = socket.socket(
    socket.AF_INET,
    socket.SOCK_STREAM
)

server_socket.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server_socket.bind((HOST, PORT))
server_socket.listen(5)

print(f"Proxy server listening on {HOST}:{PORT}")


# Accept multiple clients using threads
try:
    while True:
        client_socket, client_address = server_socket.accept()

        client_thread = threading.Thread(
            target=handle_client,
            args=(client_socket, client_address)
        )

        client_thread.start()

except KeyboardInterrupt:
    print("\nProxy server shutting down")

finally:
    server_socket.close()
