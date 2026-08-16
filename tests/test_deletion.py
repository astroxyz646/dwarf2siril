"""Tests for the delete engine and the card classification.

The deleting itself is tested against a temp folder, never against a card.
The behaviour that matters most is not "did it delete" but "did it tell the
truth about what happened" -- a locked file counted as deleted would be the
worst bug this app could have.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dwarf2siril.cardinfo import KEEP, SAFE, YOURS, KNOWN
from dwarf2siril.deletion import (
    DeleteResult,
    delete,
    describe_size,
    folder_size,
    recycle_bin_available,
)


class SizeTests(unittest.TestCase):
    def test_reads_like_a_human_wrote_it(self) -> None:
        self.assertEqual(describe_size(0), "0 B")
        self.assertEqual(describe_size(999), "999 B")
        self.assertEqual(describe_size(2048), "2 KB")
        self.assertEqual(describe_size(5 * 1024**2), "5.0 MB")
        self.assertEqual(describe_size(3 * 1024**3), "3.0 GB")

    def test_folder_size_counts_everything_below(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "a" / "one.bin").write_bytes(b"x" * 1000)
            (root / "two.bin").write_bytes(b"x" * 500)
            size, files = folder_size(root)
        self.assertEqual(size, 1500)
        self.assertEqual(files, 2)

    def test_missing_path_is_zero_not_an_error(self) -> None:
        self.assertEqual(folder_size(Path("/definitely/not/here")), (0, 0))


class DeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_deletes_files_and_reports_what_it_freed(self) -> None:
        files = []
        for index in range(3):
            path = self.root / f"frame_{index}.fits"
            path.write_bytes(b"x" * 1000)
            files.append(path)
        result = delete(files)
        self.assertEqual(len(result.deleted), 3)
        self.assertEqual(result.failed, [])
        self.assertEqual(result.bytes_freed, 3000)
        self.assertTrue(all(not f.exists() for f in files))

    def test_deletes_a_whole_folder(self) -> None:
        session = self.root / "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_A"
        (session / "Thumbnail").mkdir(parents=True)
        (session / "frame.fits").write_bytes(b"x" * 2000)
        (session / "shotsInfo.json").write_bytes(b"{}")
        (session / "Thumbnail" / "frame.jpg").write_bytes(b"x" * 100)

        result = delete([session])
        self.assertTrue(result.ok)
        self.assertFalse(session.exists())
        # The whole folder goes, not only the frames.
        self.assertGreaterEqual(result.bytes_freed, 2100)

    def test_a_missing_file_is_reported_not_counted_as_done(self) -> None:
        result = delete([self.root / "never_existed.fits"])
        self.assertEqual(result.deleted, [])
        self.assertEqual(len(result.failed), 1)
        self.assertIn("already gone", result.failed[0][1])
        self.assertFalse(result.ok)

    def test_nothing_to_do_is_not_a_failure(self) -> None:
        result = delete([])
        self.assertTrue(result.ok)
        self.assertEqual(result.summary(), "nothing to delete")

    def test_summary_names_the_destination(self) -> None:
        recycled = DeleteResult(deleted=[Path("a")], bytes_freed=1024, recycled=True)
        permanent = DeleteResult(deleted=[Path("a")], bytes_freed=1024, recycled=False)
        self.assertIn("Recycle Bin", recycled.summary())
        self.assertIn("permanently", permanent.summary())

    def test_recycle_bin_query_never_raises(self) -> None:
        # Whatever the volume is, this must answer rather than explode --
        # the answer decides what the dialog says.
        self.assertIn(recycle_bin_available(self.root), (True, False))


class ClassificationTests(unittest.TestCase):
    """The advice is the point of the cleanup view, so it is pinned here."""

    def test_darks_and_calibration_are_keep(self) -> None:
        for name in ("DWARF_DARK", "CALI_FRAME"):
            with self.subTest(name=name):
                kind, reason = KNOWN[name]
                self.assertEqual(kind, KEEP)
                self.assertIn("REUSABLE" if name == "DWARF_DARK" else "reused", reason)

    def test_regenerable_leftovers_are_safe(self) -> None:
        for name in ("Solving_Failed", "RESTACKED", "STARTRAILS", ".log"):
            with self.subTest(name=name):
                self.assertEqual(KNOWN[name][0], SAFE)

    def test_the_users_own_media_gets_no_opinion(self) -> None:
        for name in ("Normal_Photos", "Videos", "Panoramas", "Burst"):
            with self.subTest(name=name):
                kind, reason = KNOWN[name]
                self.assertEqual(kind, YOURS)
                # No advice about the user's own photos, just what they are.
                self.assertNotIn("safe", reason.lower())
                self.assertNotIn("delete", reason.lower())


if __name__ == "__main__":
    unittest.main()
