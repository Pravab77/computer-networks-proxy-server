import socket

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

client.connect(("127.0.0.1", 8080))

request = "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"

client.send(request.encode())

client.close()