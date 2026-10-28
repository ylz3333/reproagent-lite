"""Regression tests for stable source-tree evidence hashing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reproagent_lite.hashing import sha256_tree


class HashingTests(unittest.TestCase):
    """Protect the distinction between experiment inputs and mutable caches."""

    def test_unreadable_source_directory_does_not_produce_partial_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            blocked = root / "inputs"
            blocked.mkdir()
            (blocked / "data.csv").write_bytes(b"experiment input")
            original_scandir = os.scandir

            def deny_input_directory(path):
                if Path(path).resolve() == blocked:
                    raise PermissionError("cannot scan experiment inputs")
                return original_scandir(path)

            with patch("os.scandir", side_effect=deny_input_directory):
                with self.assertRaisesRegex(PermissionError, "cannot scan experiment inputs"):
                    sha256_tree(root)

    def test_excluded_directories_are_not_traversed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "experiment.py").write_text("print('stable')\n", encoding="utf-8")
            for name in (".git", "__pycache__"):
                (root / name / "nested").mkdir(parents=True)
                (root / name / "nested" / "ignored").write_bytes(b"metadata")
            scanned = []
            original_scandir = os.scandir

            def record_scandir(path):
                scanned.append(Path(path).resolve())
                return original_scandir(path)

            with patch("os.scandir", side_effect=record_scandir):
                sha256_tree(root)
            self.assertIn(root, scanned)
            self.assertFalse(any(
                {".git", "__pycache__"}.intersection(path.relative_to(root).parts)
                for path in scanned
            ))

    def test_source_hash_does_not_exclude_files_based_on_ancestor_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ordinary = base / "ordinary"
            ordinary.mkdir()
            content = "print('stable')\n"
            (ordinary / "experiment.py").write_text(content, encoding="utf-8")
            baseline = sha256_tree(ordinary)
            for name in (".git", "__pycache__"):
                with self.subTest(ancestor=name):
                    root = base / name / "source"
                    root.mkdir(parents=True)
                    source = root / "experiment.py"
                    source.write_text(content, encoding="utf-8")
                    self.assertEqual(sha256_tree(root), baseline)
                    source.write_text("print('changed')\n", encoding="utf-8")
                    self.assertNotEqual(sha256_tree(root), baseline)

    def test_source_hash_ignores_git_metadata_and_python_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "experiment.py").write_text("print('stable')\n", encoding="utf-8")
            baseline = sha256_tree(root)

            git_directory = root / ".git"
            cache_directory = root / "__pycache__"
            git_directory.mkdir()
            cache_directory.mkdir()
            (git_directory / "index").write_bytes(b"mutable metadata")
            (cache_directory / "experiment.pyc").write_bytes(b"cache")

            self.assertEqual(sha256_tree(root), baseline)


if __name__ == "__main__":
    unittest.main()
