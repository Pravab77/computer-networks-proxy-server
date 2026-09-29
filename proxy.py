import socket

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
server_socket.bind((HOST, PORT))
server_socket.listen(5)

print(f"Proxy server listening on {HOST}:{PORT}")

while True:
    client_socket, client_address = server_socket.accept()
    print(f"\nClient connected: {client_address}")

    try:
        request = client_socket.recv(4096)
        request = request.decode("utf-8", errors="ignore")

        print("HTTP Request:")
        print(request)

        lines = request.split("\r\n")

        if not lines or not lines[0].strip():
            print("Empty HTTP request")
            continue

        request_line = lines[0]
        parts = request_line.split()

        if len(parts) != 3:
            print("Malformed HTTP request")
            continue

        method = parts[0]
        path = parts[1]
        version = parts[2]

        host = ""

        for line in lines:
            if line.lower().startswith("host:"):
                host = line.split(":", 1)[1].strip()
                break

        print("Method:", method)
        print("Path:", path)
        print("Version:", version)
        print("Host:", host)

        if not host:
            print("Host header is missing")
            continue

        # Day 6: Connect to the destination website
        destination_socket = connect_to_destination(host, 80)

        if destination_socket:
            print("Destination connection successful")
            destination_socket.close()

    finally:
        client_socket.close()
