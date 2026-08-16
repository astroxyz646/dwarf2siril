"""Tests for locating Siril and judging a finished run.

The parts that matter here are the ones that would otherwise fail silently:
quoting a path that contains a space, and deciding whether a run worked when
Siril's exit code alone does not say.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dwarf2siril.siril import (
    SUCCESS_MARKER,
    expected_output,
    find_siril,
    interpret,
    run_command,
)


class RunCommandTests(unittest.TestCase):
    def test_quotes_a_script_path_containing_spaces(self) -> None:
        command = run_command(Path(r"C:\Astro Output\C 27\C 27.ssf"))
        self.assertIn('"C:\\Astro Output\\C 27\\C 27.ssf"', command)

    def test_quotes_the_executable_too(self) -> None:
        command = run_command(
            Path("/out/x.ssf"), Path(r"C:\Program Files\Siril\bin\siril-cli.exe")
        )
        self.assertIn('"C:\\Program Files\\Siril\\bin\\siril-cli.exe"', command)

    def test_falls_back_to_the_bare_name(self) -> None:
        self.assertTrue(run_command(Path("/out/x.ssf")).startswith('"siril-cli"'))


class FindSirilTests(unittest.TestCase):
    def test_an_explicit_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "siril-cli.exe"
            fake.write_bytes(b"")
            self.assertEqual(find_siril(fake), fake)

    def test_a_missing_explicit_path_does_not_crash(self) -> None:
        # Falls through to the normal search, which may or may not find one.
        result = find_siril(Path("/definitely/not/here/siril-cli"))
        self.assertTrue(result is None or result.is_file())


class InterpretTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.image = Path(self._tmp.name) / "stack.fit"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_success_needs_both_a_clean_exit_and_siril_agreeing(self) -> None:
        result = interpret([f"log: {SUCCESS_MARKER}"], 0, None)
        self.assertTrue(result.ok)

    def test_an_error_in_the_log_beats_a_zero_exit_code(self) -> None:
        # Siril logs a failed script and can still exit 0, so the log wins.
        lines = [
            "log: Error in line 18 ('cd'): directory not found.",
            "log: Script execution failed.",
        ]
        result = interpret(lines, 0, None)
        self.assertFalse(result.ok)
        self.assertTrue(result.error_lines)

    def test_a_produced_file_counts_as_success(self) -> None:
        self.image.write_bytes(b"x")
        result = interpret(["log: something"], 0, self.image)
        self.assertTrue(result.ok)
        self.assertEqual(result.output_image, self.image)

    def test_a_missing_file_is_not_success(self) -> None:
        result = interpret(["log: something"], 0, self.image)
        self.assertFalse(result.ok)
        self.assertIsNone(result.output_image)

    def test_a_nonzero_exit_is_never_success(self) -> None:
        self.image.write_bytes(b"x")
        result = interpret([f"log: {SUCCESS_MARKER}"], 1, self.image)
        self.assertFalse(result.ok)

    def test_cancellation_is_reported_as_cancelled_not_failed(self) -> None:
        result = interpret([], -1, None)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.ok)


class ExpectedOutputTests(unittest.TestCase):
    def test_lands_beside_the_script(self) -> None:
        script = Path(r"C:\Astro Out\C 27\C_27_350x15s_gain100.ssf")
        self.assertEqual(
            expected_output(script, "C_27_350x15s_gain100"),
            script.parent / "C_27_350x15s_gain100.fit",
        )


if __name__ == "__main__":
    unittest.main()
