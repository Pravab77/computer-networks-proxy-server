import urllib.request
import urllib.error

proxy = urllib.request.ProxyHandler({
    "http": "http://127.0.0.1:8080"
})

opener = urllib.request.build_opener(proxy)

try:
    response = opener.open("http://forever.com/", timeout=10)
    print("HTTP Status:", response.status)
except urllib.error.HTTPError as error:
    print("HTTP Status:", error.code)
    if error.code == 403:
        print("SUCCESS: Domain blocked by proxy.")
    else:
        print("Unexpected HTTP error.")
except Exception as error:
    print("Request failed:", error)
