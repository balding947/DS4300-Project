# INC-02: Sorted list point lookups scan linearly instead of using binary search

## Summary

`SortedListIndex.search` walked the sorted key list from the start, one key at a time, instead of binary searching it. At n = 114,000 a hit cost 43,515 comparisons and about 3.9 ms, where binary search needs about 17 comparisons. The miss cost was 84,007 comparisons and 7.7 ms. I fixed it by making `search` call the class's own `_bisect_left`, which `insert` and `range_search` already used. After the fix a hit costs 16.5 comparisons and about 1.9 µs, roughly 2,100× faster.

## Detection

E2 (`E2_point_lookups`), the counters-vs-n plot in `analysis/E2_point_lookups.ipynb`. The sorted list's comparisons per lookup sat on the `n/2` reference line, next to the unsorted list, instead of on the `log2(n)` line with the AVL tree and the B+ tree. Two indexes that should both be O(log n) (sorted list and `ref_bisect`) were about 2,000× apart at n = 114,000. That is far too big a gap to be just Python vs C.

## Expected vs. observed

Theory: binary search over D distinct keys examines about log2(D) keys per lookup, hit or miss. At n = 114,000 (D = 89,741 distinct track ids), that is 16.5.

| n | op | comparisons/op before | comparisons/op after | log2(distinct) | µs/op before | µs/op after |
|---|---|---|---|---|---|---|
| 1,000 | hit | 466 | 10.0 | 10.0 | 13.0 | 0.75 |
| 1,000 | miss | 946 | 9.1 | 10.0 | 28.6 | 0.61 |
| 10,000 | hit | 4,764 | 13.2 | 13.2 | 179 | 0.90 |
| 10,000 | miss | 8,754 | 13.0 | 13.2 | 318 | 0.84 |
| 114,000 | hit | 43,515 | 16.5 | 16.5 | 3,945 | 1.86 |
| 114,000 | miss | 84,007 | 16.1 | 16.5 | 7,708 | 1.13 |

Before the fix, comparisons grew linearly: about 0.48 × D for hits and 0.94 × D for misses. Misses cost almost twice as much because of how the miss queries are made. Every real Spotify `track_id` starts with `0`–`7`, but `point_queries` builds misses from all 62 characters in the ids, so about 54 of 62 misses start with a letter and sort *after every stored key*. The linear scan's early exit (`k > key`) never fires for those, and it reads the whole list. Expected: (54/62)·D + (8/62)·D/2 ≈ 0.935·D. Observed: 0.936·D.

## Evidence

- Counters are deterministic, so the "before" numbers match exactly across machines: zaid-mbp's E2 rows (`code_version` 45879fa) and my run on ike-mba (ea02147) both show 43,514.996 comparisons per hit at n = 114,000.
- "Before" = code_version `ea02147`, "after" = `7c43369`. Both measured on ike-mba with the E2 workload (same sizes, `point_queries(..., seed=SEED + n)`, 500 queries). The table above comes from that run. Official E2 rows for `7c43369` (5 reps) are in `results/timings.csv`.
- After the fix, the sorted list's comparisons per lookup match `log2(distinct_keys)` (from `structure_info()`) to within 0.5 at every n.

## Root cause

`indexes/sorted_list.py`, `search`, lines 53–65 (before the fix). The loop `for i, k in enumerate(self._keys)` checks keys in order from index 0, returns when `k == key`, and stops early only once `k > key`. Because the list is sorted, this always returns the right answer. It just looks at every key before the match, which is O(n). The class already had a correct O(log n) binary search, `_bisect_left` (lines 27–42), and `insert` and `range_search` both use it; `search` simply didn't. The answers were right, so every correctness test passed, but each lookup cost thousands of comparisons instead of about 17.

## Fix

```diff
diff --git a/indexes/sorted_list.py b/indexes/sorted_list.py
index 3519135..4255076 100644
--- a/indexes/sorted_list.py
+++ b/indexes/sorted_list.py
@@ -51,17 +51,11 @@ class SortedListIndex(Index):
         self._size += 1
 
     def search(self, key: Any) -> list[Any]:
-        # The keys are sorted, so we can stop as soon as we have passed the
-        # place where ``key`` would be.
-        comparisons = 0
-        for i, k in enumerate(self._keys):
-            comparisons += 1
-            if k == key:
-                self.stats.comparisons += comparisons
-                return self._values[i]
-            if k > key:
-                break
-        self.stats.comparisons += comparisons
+        # The keys are sorted, so binary search jumps straight to the only
+        # place ``key`` could be (O(log n)), the same way ``insert`` does.
+        pos = self._bisect_left(key)
+        if pos < len(self._keys) and self._keys[pos] == key:
+            return self._values[pos]
         return []
```

Commit: 7c43369

`_bisect_left` adds its own comparisons to `stats.comparisons`. The final `== key` check examines the same key that binary search ended on, so it isn't counted again, the same as in `insert`.

## Verification

Same workload and seeds before and after (table above). The official `E2_point_lookups` run on ike-mba at `7c43369` (5 reps) agrees: at n = 114,000, 16.54 comparisons per hit and 16.06 per miss, with median 1.98 µs per hit and 1.25 µs per miss. Before the fix, zaid-mbp at `45879fa` measured 6,305 µs and 13,833 µs. `make test` after the fix: 168 passed, 3 skipped. Later, commit `bc253d0` also counts the final `== key` check in `search`, so rows from that commit on show up to one more comparison per lookup (about 17.5 per hit at n = 114,000). The search is still O(log n). E4 isn't affected: `prefix_search` goes through `range_search`, which already used `_bisect_left`.

## Impact on recommendations

Yes, for F1 (track page, point lookups). Before the fix, the sorted list looked like a bad candidate for point lookups, costing as much as the unsorted baseline. After the fix it costs about 1–2 µs, the same range as the AVL tree and the hash table. For F2 (prefix) and F3 (range) the sorted list was never slowed down by this bug, because those queries already used binary search.

## Why the tests didn't catch it

`tests/test_indexes.py` only checks *what* `search` returns, and a linear scan returns the same thing. A test that would catch it: build a sorted list with, for example, 10,000 distinct keys, call `reset_stats()`, run one lookup, and assert `stats.comparisons <= ceil(log2(10_000)) + 1` (about 15). A linear scan does thousands.
