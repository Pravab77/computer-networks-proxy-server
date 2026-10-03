
import socket
import threading
import os
import hashlib
import time
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080

CACHE_DIR = "cache"
CACHE_TTL = 60  # Cache expires after 60 seconds

os.makedirs(CACHE_DIR, exist_ok=True)

cache_lock = threading.Lock()


# Generate a unique cache file for each URL
def get_cache_path(url):
    url_hash = hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()

    return os.path.join(CACHE_DIR, url_hash + ".cache")


# Read response from cache if it is still valid
def read_cache(url):
    cache_path = get_cache_path(url)

    with cache_lock:
        if not os.path.exists(cache_path):
            return None

        try:
            # Get the last modified time of the cache file
            modified_time = os.path.getmtime(cache_path)

            # Calculate how old the cached response is
            cache_age = time.time() - modified_time

            # Check whether the cache has expired
            if cache_age >= CACHE_TTL:
                os.remove(cache_path)
                print("CACHE EXPIRED")
                return None

            # Cache is still valid, so read it
            with open(cache_path, "rb") as file:
                cached_response = file.read()

            print(f"Cache age: {cache_age:.2f} seconds")
            return cached_response

        except OSError as error:
            print(f"Cache read error: {error}")
            return None


# Save successful response to cache
def save_cache(url, response):
    # Check whether response is a valid HTTP response
    if not response.startswith(b"HTTP/"):
        return

    header_end = response.find(b"\r\n\r\n")

    if header_end == -1:
        return

    # Extract response headers
    headers = response[:header_end].lower()

    # Extract HTTP status line
    status_line = response.split(b"\r\n", 1)[0].split()

    # Cache only HTTP 200 responses
    if len(status_line) < 2 or status_line[1] != b"200":
        return

    # Do not cache responses that prohibit storage
    if (b"no-store" in headers or
            b"private" in headers or
            b"no-cache" in headers):
        print("Response is not suitable for caching")
        return

    cache_path = get_cache_path(url)
    temp_path = cache_path + ".tmp"

    with cache_lock:
        try:
            # Write response to a temporary file first
            with open(temp_path, "wb") as file:
                file.write(response)

            # Replace old cache file safely
            os.replace(temp_path, cache_path)

            print("Response saved to cache")

        except OSError as error:
            print(f"Cache write error: {error}")

        finally:
            # Remove temporary file if it still exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


# Send an HTTP error response to the client
def send_error(client_socket, status, message):
    response = (
        f"HTTP/1.1 {status} {message}\r\n"
        f"Content-Type: text/plain\r\n"
        f"Content-Length: {len(message.encode('utf-8'))}\r\n"
        f"Connection: close\r\n"
        f"\r\n"
        f"{message}"
    )

    client_socket.sendall(response.encode("utf-8"))


# Connect to destination server
def connect_to_destination(host, port=80):
    try:
        destination_socket = socket.create_connection(
            (host, port),
            timeout=5
        )

        destination_socket.settimeout(10)

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
            send_error(client_socket, 400, "Bad Request")
            return

        method, target, version = parts

        # This proxy currently supports GET only
        if method != "GET":
            send_error(client_socket, 501, "Not Implemented")
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
                send_error(client_socket, 400, "Bad Request")
                return

            try:
                port = url.port or 80
            except ValueError:
                send_error(client_socket, 400, "Bad Request")
                return

            if url.scheme.lower() != "http":
                send_error(client_socket, 400, "Bad Request")
                return

            path = url.path or "/"

            if url.query:
                path += "?" + url.query

        else:
            # Handle origin-form request
            path = target

            if not host:
                send_error(client_socket, 400, "Bad Request")
                return

            try:
                host_info = urlsplit("//" + host)
                host = host_info.hostname
                port = host_info.port or 80

            except ValueError:
                send_error(client_socket, 400, "Bad Request")
                return

            if not host or not path.startswith("/"):
                send_error(client_socket, 400, "Bad Request")
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
            send_error(client_socket, 502, "Bad Gateway")
            return

        # Build HTTP request for destination server
        new_request = f"{method} {path} {version}\r\n"

        host_header_added = False

        for line in headers:
            lower_line = line.lower()

            # Remove proxy-specific connection headers
            if lower_line.startswith("connection:"):
                continue

            if lower_line.startswith("proxy-connection:"):
                continue

            if lower_line.startswith("host:"):
                new_request += f"Host: {host}\r\n"
                host_header_added = True
                continue

            new_request += line + "\r\n"

        # Add Host header if missing
        if not host_header_added:
            new_request += f"Host: {host}\r\n"

        # Ask destination to close connection after response
        new_request += "Connection: close\r\n\r\n"

        # Forward request to destination
        destination_socket.sendall(
            new_request.encode("latin-1")
        )

        print("Request forwarded to destination")

        # Receive complete response until server closes connection
        response_data = bytearray()

        while True:
            response = destination_socket.recv(4096)

            if not response:
                break

            response_data.extend(response)

        complete_response = bytes(response_data)

        # Save response if suitable for caching
        save_cache(cache_url, complete_response)

        # Send response back to client
        if complete_response:
            client_socket.sendall(complete_response)
            print("Response forwarded to client")
        else:
            send_error(client_socket, 502, "Bad Gateway")

    except socket.timeout:
        print("Connection timed out")

        try:
            send_error(client_socket, 504, "Gateway Timeout")
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
print(f"Cache TTL: {CACHE_TTL} seconds")

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
