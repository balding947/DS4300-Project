# INC-01: AVL tree rotations update heights in the wrong order, causing excess rotations and a too-tall tree

## Summary

In indexes/avl_tree.py, both rotation functions were updating the heights in the wrong order. They updated the new top node before the node below it, which caused incorrect heights to be stored. This made the tree sometimes rotate when it didn't need to and sometimes fail to rotate when it did, leading to 102,078 rotations for 10,000 random inserts, compared to only 6,948 after the fix. The tree also had a height of 21. I fixed this by switching the order of the two _update_height calls in both rotation functions.

## Detection

I built an AVL tree with 10,000 keys from random_keys(10000, seed=1) and read structure_info(). Height was 21. A valid AVL tree with 10,000 keys can be at most 18 levels tall, because height 19 needs at least 10,945 keys. The rotation counter was also far too high: each insert needs at most one single or double rotation, so at most about 20,000 rotations total. I confirmed it with the CORE rows for code_version a590d16, which show the AVL height and rotation counts before the fix.

## Expected vs. observed

Theory: height about log2(n), at most 18 for n = 10,000; at most about 2n rotations.

| Workload | Metric | Observed (before) | Observed (after) |
|---|---|---|---|
| 10,000 random keys | height | 21 | 16 |
| 10,000 random keys | rotations | 102,078 | 6,948 |
| 1,000 sorted keys | height | 14 | 10 |
| 1,000 sorted keys | rotations | 5,928 | 990 |

## Evidence

Shell measurements with structure_info() and the stats counters. Rows before the fix come from code_version a590d16, and rows after from 4c0a6c4. Shell measurements, with CORE rows to be added.

## Root cause

In indexes/avl_tree.py, the issue was in _rotate_right (lines 62–63) and _rotate_left (lines 80–81). The _update_height(node) function calculates a node's height using the heights of its children. After a rotation, the lower node needs to have its height updated first. However, the code updated the top node first, which used the old height of the lower node. This caused incorrect heights and balance factors, so the tree sometimes rotated unnecessarily and sometimes failed to rotate, leaving it too tall. Searches still worked correctly because the nodes were still in the right order, but the tree was less efficient because of its structure.

## Fix

diff --git a/indexes/avl_tree.py b/indexes/avl_tree.py
index bef0b73..c376556 100644
--- a/indexes/avl_tree.py
+++ b/indexes/avl_tree.py
@@ -59,8 +59,8 @@ class AVLTreeIndex(Index):
         y.left = x.right
         x.right = y
         # x and y swapped places; refresh their stored heights.
-        _update_height(x)
         _update_height(y)
+        _update_height(x)
         self.stats.rotations += 1
         return x
 
@@ -77,8 +77,8 @@ class AVLTreeIndex(Index):
         x.right = y.left
         y.left = x
         # x and y swapped places; refresh their stored heights.
-        _update_height(y)
         _update_height(x)
+        _update_height(y)
         self.stats.rotations += 1
         return y

Commit: 4c0a6c4

## Verification

Same workloads and seeds before and after (see the table above). make test after the fix: 168 passed, 3 skipped. <Add the CORE "after" comparison when it is run.>

## Impact on recommendations

<Fill in after E1 and E2: did the buggy AVL's extra height and rotations make it look worse than the B+ tree on build or lookup cost? Would the ranking have changed?>

## Why the tests didn't catch it

The tests only check returned values, and a lopsided tree returns the right answers. A test that would catch it: insert many keys (random and sorted) and assert that structure_info()["height"] is at most about 1.44 * log2(n + 2), and that stats.rotations is at most 2n.
