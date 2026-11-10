# INC-04: B+ range queries traverse every subtree

## Summary

The original B+ range method recursively visited every subtree and tested every leaf key, even for tiny ranges. The fix finds the lower-bound leaf and follows `next` until the upper bound. In the recorded historical runs, the narrowest-range median changes from 3,498.708 to 8.191 microseconds per query, about 427.12 times before/after.

## Detection

Code review identified an unpruned traversal in `_collect_range`. E3 verifies the excess work: the pre-fix B+ tree performs exactly 45,653 comparisons and visits 2,197 nodes per query at every selectivity. Those are all distinct tempo keys and all tree nodes, even when the range covers only five distinct keys.

## Expected vs. observed

Let d be distinct keys and r be returned row IDs. An ordered range query should cost O(log d + r) for a fixed B+ order: navigate to the start, then collect the matching interval. The original implementation instead costs O(d + r). With order 32, the fixed method should visit the descent path plus the leaves needed by the interval.

The table uses actual saved E3 rows on oscar-omen, all 114,000 tempo pairs, order 32, seed 4300, 200 queries per batch, five replicates. Before is `9598854-dirty` and after is `bc253d0-dirty`. Times are medians with interquartile ranges. These are historical dirty-source measurements, not clean verification runs.

| Selectivity | Before us/query [Q25, Q75] | After us/query [Q25, Q75] | Comparisons before | Comparisons after | Nodes before | Nodes after |
|---:|---:|---:|---:|---:|---:|---:|
| 0.0001 | 3,498.708 [3,484.800, 3,499.959] | 8.191 [7.618, 8.656] | 45,653.000 | 21.870 | 2,197.000 | 4.210 |
| 0.001 | 3,753.706 [3,523.744, 3,936.809] | 28.456 [24.794, 30.037] | 45,653.000 | 62.875 | 2,197.000 | 6.130 |
| 0.01 | 3,696.974 [3,690.218, 5,313.863] | 287.112 [238.189, 349.397] | 45,653.000 | 473.885 | 2,197.000 | 25.050 |
| 0.05 | 4,644.550 [4,231.903, 4,914.374] | 1,322.572 [1,213.019, 1,373.140] | 45,653.000 | 2,299.885 | 2,197.000 | 108.965 |
| 0.1 | 4,903.161 [4,674.923, 6,778.938] | 2,539.509 [2,139.179, 2,797.283] | 45,653.000 | 4,581.845 | 2,197.000 | 214.050 |
| 0.25 | 6,014.273 [5,986.667, 11,168.709] | 6,182.986 [5,449.453, 6,846.122] | 45,653.000 | 11,429.805 | 2,197.000 | 529.025 |

## Evidence

- Raw rows: `results/timings.csv`, `experiment=E3_range_tempo`, `index_type=bplus_tree`, `machine_id=oscar-omen`, with the exact code-version labels above.
- Analysis: `analysis/E3_range_tempo.ipynb`, the B+ before/after section. The simplified notebook exports the comparison figure to `report/figures/e3/E3_Bplus_before_after.png` when run.
- The fixed narrowest range examines about 21.87 keys per query rather than all 45,653. Node visits fall from 2,197 to 4.21 per query. Work grows with range width after the fix instead of scanning the entire tree for every range.
- Broad ranges still return many values. The recorded 25% case does not show a median timing improvement, so the narrow-range speedup should not be generalized to every workload.

## Root cause

In the pre-fix `indexes/bplus_tree.py`, `range_search` calls `_collect_range(self._root, ...)`. `_collect_range` visits every child without using separator keys to prune or the leaf chain to restrict the interval. It appends the right values in order, so correctness tests pass, but narrow queries still scan the whole tree.

## Fix

Commit `bc253d0` uses `_find_leaf(lo)`, binary-searches the first leaf for the lower bound, follows `leaf.next`, and stops as soon as a key exceeds `hi`. The unused full-tree `_collect_range` is removed. The first leaf is counted by `_find_leaf`; each additional leaf increments `nodes_visited` once.

```diff
diff --git a/indexes/bplus_tree.py b/indexes/bplus_tree.py
index 7005649..2df0d71 100644
--- a/indexes/bplus_tree.py
+++ b/indexes/bplus_tree.py
@@ -172,21 +172,31 @@ class BPlusTreeIndex(Index):
 
     def range_search(self, lo: Any, hi: Any) -> list[Any]:
         result: list[Any] = []
-        if lo <= hi:
-            self._collect_range(self._root, lo, hi, result)
-        return result
 
-    def _collect_range(self, node: _Node, lo: Any, hi: Any, out: list[Any]) -> None:
-        """Gather values for keys in [lo, hi] from the subtree under ``node``, in key order."""
-        self.stats.nodes_visited += 1
-        if isinstance(node, _Leaf):
-            for key, values in zip(node.keys, node.values):
-                if lo <= key <= hi:
-                    out.extend(values)
-            self.stats.comparisons += len(node.keys)
-            return
-        for child in node.children:
-            self._collect_range(child, lo, hi, out)
+        if lo > hi:
+            return result
+
+        leaf = self._find_leaf(lo)
+        i = self._bisect_left(leaf.keys, lo)
+
+        while leaf is not None:
+            while i < len(leaf.keys):
+                self.stats.comparisons += 1
+
+                if leaf.keys[i] > hi:
+                    return result
+
+                result.extend(leaf.values[i])
+                i += 1
+
+            leaf = leaf.next
+
+            if leaf is not None:
+                self.stats.nodes_visited += 1
+
+            i = 0
+
+        return result
 
     # ------------------------------------------------------------------ structure
     def structure_info(self) -> dict[str, Any]:
```

## Verification

The historical before/after E3 runs use matching workload notes, seeds, query counts and insertion order, and were recorded in Docker with five replicates. Both source labels end in `-dirty`, so clean-source verification is still needed.

**TODO: clean verification.** Rerun E3 at the committed pre-fix revision `fa70927` and at the agreed final fix revision. Add their code versions and session IDs, update or supplement the table and notebook figure, and record the actual Docker test result. Keep the historical rows and labels unchanged. Check prefix correctness too, since inherited `prefix_search` calls `range_search`.

## Impact on recommendations

The fix makes B+ a strong F3 candidate for selective tempo ranges. It also changes F2 prefix performance because prefix search delegates to the range method. Final F2 recommendations should use the retained `E4_prefix_track_name` experiment on fixed code; E6 should tune order for the relevant operation. The E3 broad-range results still show that B+ is not automatically the best structure for every selectivity.

## Why the tests didn't catch it

A full-tree scan returns the same correct sorted results. Tests of returned values therefore do not detect the extra work. A diagnostic asserting that a narrow range visits much less than the full tree would reveal the problem. The supplied correctness tests remain unchanged.
