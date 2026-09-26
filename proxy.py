import socket

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

server_socket.bind(("127.0.0.1", 8080))

server_socket.listen()

print("proxy server is running on port 8080")