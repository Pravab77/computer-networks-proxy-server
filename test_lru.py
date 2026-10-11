
import os
import time
import tempfile
import shutil
from pathlib import Path
import proxy

# Create a temporary cache folder
test_dir = Path(tempfile.mkdtemp(prefix="lru_test_"))

old_dir = proxy.CACHE_DIR
old_limit = proxy.CACHE_MAX_ENTRIES

try:
    proxy.CACHE_DIR = str(test_dir)
    proxy.CACHE_MAX_ENTRIES = 3

    # Create four cache files
    for i in range(4):
        file_path = test_dir / f"test{i}.cache"
        file_path.write_text("test")

        # Give each file a different access time
        os.utime(file_path, (time.time() + i, time.time()))

    # Enforce the cache limit
    proxy.enforce_cache_limit()

    remaining = sorted(
        file.name for file in test_dir.glob("*.cache")
    )

    print("Remaining files:", remaining)

    if len(remaining) == 3 and "test0.cache" not in remaining:
        print("LRU test: PASS")
    else:
        print("LRU test: CHECK RESULT")

finally:
    proxy.CACHE_DIR = old_dir
    proxy.CACHE_MAX_ENTRIES = old_limit
    shutil.rmtree(test_dir, ignore_errors=True)
