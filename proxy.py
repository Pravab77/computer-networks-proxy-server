import socket

HOST = "127.0.0.1"
PORT = 8080

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server_socket.bind((HOST, PORT))

server_socket.listen(5)

print(f"Proxy server listening on {HOST}:{PORT}")

while True:
    client_socket, client_address = server_socket.accept()

    print(f"\nClient connected: {client_address}")

    request = client_socket.recv(4096)

    request = request.decode("utf-8", errors="ignore")

    print("HTTP Request:")
    print(request)

    client_socket.close()
