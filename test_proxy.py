"""Unit tests for cache policy and HTTP response framing helpers."""
import socket
import threading
import unittest

import proxy


class CachePolicyTests(unittest.TestCase):
    def test_authorization_and_cookie_bypass_cache(self):
        self.assertFalse(proxy._request_is_cacheable("GET", {"authorization": "Bearer x"}, b""))
        self.assertFalse(proxy._request_is_cacheable("GET", {"cookie": "session=x"}, b""))
        self.assertTrue(proxy._request_is_cacheable("GET", {"accept-encoding": "gzip"}, b""))
        self.assertFalse(proxy._request_is_cacheable("POST", {}, b"data"))

    def test_request_no_cache_bypasses_cache(self):
        self.assertFalse(proxy._request_is_cacheable("GET", {"cache-control": "no-cache"}, b""))
        self.assertFalse(proxy._request_is_cacheable("GET", {"cache-control": "max-age=0"}, b""))

    def test_origin_ttl_directives(self):
        old_ttl = proxy.CACHE_TTL
        proxy.CACHE_TTL = 60
        try:
            self.assertEqual(proxy._response_cache_ttl({"cache-control": "max-age=10"}), 10)
            self.assertEqual(proxy._response_cache_ttl({"cache-control": "s-maxage=20, max-age=10"}), 20)
            self.assertEqual(proxy._response_cache_ttl({"cache-control": "no-store"}), 0)
            self.assertEqual(proxy._response_cache_ttl({"cache-control": "max-age=10", "age": "4"}), 6)
        finally:
            proxy.CACHE_TTL = old_ttl

    def test_vary_unknown_or_set_cookie_is_not_cacheable(self):
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nVary: User-Agent\r\n\r\nok"
        self.assertEqual(proxy._cacheable_response(response, {}), 0)
        response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nSet-Cookie: id=x\r\n\r\nok"
        self.assertEqual(proxy._cacheable_response(response, {}), 0)


class ResponseFramingTests(unittest.TestCase):
    def _read_with_payload(self, payload, method="GET"):
        reader, writer = socket.socketpair()
        result = {}
        def run():
            try:
                result["value"] = proxy._read_response(reader, method)
            except Exception as error:  # surfaced to the test thread below
                result["error"] = error
        thread = threading.Thread(target=run)
        thread.start()
        writer.sendall(payload)
        writer.close()
        thread.join(2)
        reader.close()
        self.assertFalse(thread.is_alive(), "response parser did not finish")
        if "error" in result:
            raise result["error"]
        return result["value"]

    def test_content_length_response_is_complete(self):
        payload = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello"
        response, complete = self._read_with_payload(payload)
        self.assertTrue(complete)
        self.assertEqual(response, payload)

    def test_truncated_content_length_is_not_complete(self):
        payload = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhel"
        response, complete = self._read_with_payload(payload)
        self.assertFalse(complete)
        self.assertEqual(response, payload)

    def test_chunked_response_with_trailer_is_complete(self):
        payload = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                   b"2\r\nok\r\n0\r\nX-Trailer: yes\r\n\r\n")
        response, complete = self._read_with_payload(payload)
        self.assertTrue(complete)
        self.assertEqual(response, payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
