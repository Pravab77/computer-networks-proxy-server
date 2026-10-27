import urllib.request
import concurrent.futures
import time

PROXY = "http://127.0.0.1:8080"
URL = "http://httpforever.com/"
CLIENTS = 10

def send_request(client_id):
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY})
    )
    start = time.perf_counter()

    try:
        request = urllib.request.Request(
            URL,
            headers={"User-Agent": f"ProxyTestClient/{client_id}"}
        )
        with opener.open(request, timeout=25) as response:
            body = response.read()
            status = response.status

        elapsed = time.perf_counter() - start
        return (
            f"Client {client_id:02d} | HTTP {status} | "
            f"{len(body)} bytes | {elapsed:.3f}s"
        )

    except Exception as e:
        return f"Client {client_id:02d} | ERROR: {e}"

if __name__ == "__main__":
    print(f"Starting {CLIENTS} simultaneous clients...")
    start = time.perf_counter()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=CLIENTS
    ) as executor:
        futures = [
            executor.submit(send_request, i)
            for i in range(1, CLIENTS + 1)
        ]

        for future in concurrent.futures.as_completed(futures):
            print(future.result())

    print(f"\nTotal elapsed time: {time.perf_counter() - start:.3f}s")
    print("Concurrent client test completed.")
