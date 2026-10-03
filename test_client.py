
import socket

HOST = "127.0.0.1"
PORT = 8080


def send_request():
    # Create a socket for the client
    client_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    client_socket.settimeout(10)

    try:
        # Connect to the proxy server
        client_socket.connect((HOST, PORT))
        print("Connected to proxy server")

        # Prepare an HTTP GET request
        request = (
            "GET http://example.com/ HTTP/1.1\r\n"
            "Host: example.com\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        # Send the request to the proxy
        client_socket.sendall(request.encode("utf-8"))
        print("HTTP request sent to proxy")

        # Receive the response from the proxy
        response = b""

        while True:
            data = client_socket.recv(4096)

            if not data:
                break

            response += data

        # Display the HTTP response
        print("\nHTTP Response:")
        print(response.decode("utf-8", errors="ignore"))

    except ConnectionRefusedError:
        print("Could not connect. Make sure the proxy server is running.")

    except socket.timeout:
        print("Connection timed out")

    except OSError as error:
        print(f"Client error: {error}")

    finally:
        # Close the client socket
        client_socket.close()
        print("\nClient connection closed")


# First request
print("\n========== FIRST REQUEST ==========")
send_request()

# Second request to test caching
print("\n========== SECOND REQUEST ==========")
send_request()
