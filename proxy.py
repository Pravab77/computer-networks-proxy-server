
import socket
from urllib.parse import urlsplit

HOST = "127.0.0.1"
PORT = 8080

# Connect to the destination website
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


# Create the proxy server
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((HOST, PORT))
server_socket.listen(5)

print(f"Proxy server listening on {HOST}:{PORT}")

while True:
    client_socket, client_address = server_socket.accept()
    print(f"\nClient connected: {client_address}")

    destination_socket = None

    try:
        # Receive the client's HTTP request
        request = client_socket.recv(4096)

        if not request:
            continue

        request = request.decode("latin-1")
        print("HTTP Request:")
        print(request)

        # Separate request line and headers
        lines = request.split("\r\n")
        parts = lines[0].split()

        if len(parts) != 3:
            print("Malformed HTTP request")
            client_socket.sendall(
                b"HTTP/1.1 400 Bad Request\r\n"
                b"Connection: close\r\n\r\n"
            )
            continue

        method = parts[0]
        target = parts[1]
        version = parts[2]

        if method != "GET":
            client_socket.sendall(
                b"HTTP/1.1 501 Not Implemented\r\n"
                b"Connection: close\r\n\r\n"
            )
            continue

        # Find the Host header
        host = ""
        headers = []

        for line in lines[1:]:
            if not line:
                break
            if line.lower().startswith("host:"):
                host = line.split(":", 1)[1].strip()
            headers.append(line)

        # Extract host and path from the URL
        if target.startswith("http://"):
            url = urlsplit(target)
            host = url.hostname
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
                continue

            host_info = urlsplit("//" + host)
            port = host_info.port or 80
            host = host_info.hostname

        print("Method:", method)
        print("Host:", host)
        print("Path:", path)

        if not host or port != 80:
            client_socket.sendall(
                b"HTTP/1.1 400 Bad Request\r\n"
                b"Connection: close\r\n\r\n"
            )
            continue

        # Day 7: Connect to the destination
        destination_socket = connect_to_destination(host, port)

        if destination_socket is None:
            client_socket.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\n"
                b"Connection: close\r\n\r\n"
            )
            continue

        # Create a request for the destination server
        new_request = f"{method} {path} {version}\r\n"

        for line in headers:
            if line.lower().startswith("connection:"):
                continue
            if line.lower().startswith("proxy-connection:"):
                continue
            new_request += line + "\r\n"

        new_request += "Connection: close\r\n\r\n"

        # Forward the request to the destination
        destination_socket.sendall(
            new_request.encode("latin-1")
        )
        print("Request forwarded to destination")

        # Receive the response and send it to the client
        while True:
            response = destination_socket.recv(4096)

            if not response:
                break

            client_socket.sendall(response)

        print("Response forwarded to client")

    except socket.timeout:
        print("Connection timed out")
    except OSError as error:
        print(f"Error: {error}")

    finally:
        if destination_socket:
            destination_socket.close()

        client_socket.close()
