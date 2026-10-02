from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wiki22.knowledge.library_registry import (
    LibraryRegistry,
)


class LibraryRegistryTests(unittest.TestCase):

    def test_import_verify_remove_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki22"
            source = root / "source"

            wiki.mkdir()
            source.mkdir()

            original = (
                source
                / "document.txt"
            )

            original.write_text(
                "Personal local knowledge.",
                encoding="utf-8",
            )

            registry = LibraryRegistry(
                wiki
            )

            row = registry.import_library(
                source,
                name="Personal",
                library_id="personal",
            )

            self.assertEqual(
                row["id"],
                "personal",
            )

            self.assertEqual(
                registry.verify(
                    "personal"
                )["status"],
                "PASS",
            )

            self.assertEqual(
                registry.default_library()[
                    "id"
                ],
                "personal",
            )

            registry.set_enabled(
                "personal",
                False,
            )

            self.assertIsNone(
                registry.default_library()
            )

            registry.set_enabled(
                "personal",
                True,
            )

            registry.set_default(
                "personal"
            )

            registry.remove(
                "personal"
            )

            self.assertTrue(
                original.is_file()
            )

            self.assertIsNone(
                registry.get(
                    "personal"
                )
            )

    def test_two_libraries_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wiki = root / "wiki22"
            wiki.mkdir()

            a = root / "a"
            b = root / "b"

            a.mkdir()
            b.mkdir()

            (a / "a.txt").write_text(
                "Alpha knowledge",
                encoding="utf-8",
            )

            (b / "b.txt").write_text(
                "Beta knowledge",
                encoding="utf-8",
            )

            registry = LibraryRegistry(
                wiki
            )

            registry.import_library(
                a,
                name="A",
                library_id="a",
            )

            registry.import_library(
                b,
                name="B",
                library_id="b",
                set_default=False,
            )

            pa = registry.resolve_pack("a")
            pb = registry.resolve_pack("b")

            self.assertIsNotNone(pa)
            self.assertIsNotNone(pb)

            self.assertNotEqual(
                pa.parent,
                pb.parent,
            )


if __name__ == "__main__":
    unittest.main()
