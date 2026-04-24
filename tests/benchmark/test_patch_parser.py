from benchmark.adapters.patch_parser import (
    average_precision_at_k,
    extract_changed_files_from_patch,
    file_recall_at_k,
    hit_at_k,
)


def test_extract_changed_files_from_patch_excludes_tests_by_default():
    patch = """diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test_foo.py b/tests/test_foo.py
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1 +1 @@
-old
+new
"""
    assert extract_changed_files_from_patch(patch) == ["src/foo.py"]
    assert extract_changed_files_from_patch(patch, include_tests=True) == [
        "src/foo.py",
        "tests/test_foo.py",
    ]


def test_metrics_are_file_level():
    predicted = ["a.py", "b.py", "c.py"]
    gold = ["b.py", "d.py"]
    assert hit_at_k(predicted, gold, 1) == 0
    assert hit_at_k(predicted, gold, 2) == 1
    assert file_recall_at_k(predicted, gold, 2) == 0.5
    assert average_precision_at_k(predicted, gold, 3) == 0.25
