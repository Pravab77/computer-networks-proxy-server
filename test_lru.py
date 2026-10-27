"""Focused unit tests for the in-memory TTL/LRU cache."""
import time
import unittest

from proxy import LRUCache


class LRUCacheTests(unittest.TestCase):
    def test_miss_then_hit_counts(self):
        cache = LRUCache(max_entries=3, default_ttl=5)
        key = ("http://example.test/", "")
        self.assertIsNone(cache.get(key))
        cache.put(key, b"response")
        self.assertEqual(cache.get(key), b"response")
        stats = cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_expired_entry_is_a_miss(self):
        cache = LRUCache(max_entries=3, default_ttl=0.02)
        key = ("http://example.test/", "")
        cache.put(key, b"response")
        time.sleep(0.04)
        self.assertIsNone(cache.get(key))
        stats = cache.stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 1)
        self.assertGreaterEqual(stats["expirations"], 1)

    def test_lru_evicts_least_recently_used(self):
        cache = LRUCache(max_entries=2, default_ttl=5)
        a, b, c = ("a", ""), ("b", ""), ("c", "")
        cache.put(a, b"A")
        cache.put(b, b"B")
        self.assertEqual(cache.get(a), b"A")  # A becomes most recently used.
        cache.put(c, b"C")
        self.assertEqual(cache.get(b), None)   # B is evicted.
        self.assertEqual(cache.get(a), b"A")
        self.assertEqual(cache.get(c), b"C")
        self.assertEqual(cache.stats()["evictions"], 1)

    def test_zero_capacity_does_not_store(self):
        cache = LRUCache(max_entries=0, default_ttl=5)
        cache.put(("a", ""), b"A")
        self.assertEqual(cache.stats()["entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
