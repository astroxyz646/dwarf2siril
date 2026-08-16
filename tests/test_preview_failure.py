"""A preview must never be able to fail somebody's stack.

Siril aborts a script the instant any command fails, and ``savejpg`` fails
for reasons that have nothing to do with the stack -- a folder that is not
there, a full disk. This happened for real: with the previews folder
missing, a run that stacked perfectly well reported failure and produced no
processed image at all, because the very first thumbnail was attempted
before any of the work.

Two defences, both tested here: the script is ordered so every .fit exists
before any JPEG is attempted, and a run whose ONLY failure was a preview is
reported as a success with a note.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dwarf2siril.postprocess import PostOptions
from dwarf2siril.siril import interpret

# Verbatim from a real failed run.
REAL_FAILURE = [
    "log: Running command: savejpg",
    "log: Error in line 18 ('savejpg'): generic error.",
    "log: Script execution failed.",
]


class InterpretTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.image = Path(self._temp.name) / "stack.fit"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_a_failed_preview_is_not_a_failed_stack(self) -> None:
        self.image.write_bytes(b"not really a fits, but it is on disk")
        result = interpret(REAL_FAILURE, exit_code=1, expected_image=self.image)
        self.assertTrue(result.ok, "a thumbnail took the whole run down")
        self.assertEqual([], result.error_lines)
        self.assertTrue(result.warnings)
        self.assertIn("preview", result.warnings[0].lower())

    def test_but_only_when_the_promised_image_actually_exists(self) -> None:
        """No output file means it really did fail, whatever failed first."""
        result = interpret(REAL_FAILURE, exit_code=1, expected_image=self.image)
        self.assertFalse(result.ok)
        self.assertTrue(result.error_lines)

    def test_a_real_failure_is_still_a_failure(self) -> None:
        self.image.write_bytes(b"on disk")
        lines = [
            "log: Error in line 22 ('stack'): not enough images.",
            "log: Script execution failed.",
        ]
        result = interpret(lines, exit_code=1, expected_image=self.image)
        self.assertFalse(result.ok)
        self.assertFalse(result.warnings)

    def test_a_real_failure_alongside_a_preview_one_is_still_a_failure(self) -> None:
        self.image.write_bytes(b"on disk")
        lines = REAL_FAILURE + ["log: Error in line 30 ('pm'): invalid input image."]
        result = interpret(lines, exit_code=1, expected_image=self.image)
        self.assertFalse(result.ok)


class ScriptOrderTests(unittest.TestCase):
    def _script(self, post: PostOptions) -> list[str]:
        from dwarf2siril.script import _post_processing_lines

        post.resolve()
        return [
            line.strip()
            for line in _post_processing_lines("NGC_7000", post)
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_no_jpeg_is_attempted_before_the_first_fit_is_saved(self) -> None:
        """The ordering rule, checked on the layer chain most likely to break.

        With the plain stack's snapshot taken first, a failed thumbnail meant
        none of the layers ran and there was no processed image at all.
        """
        lines = self._script(
            PostOptions(background_removal=True, denoise=True, previews=True)
        )
        first_jpeg = next(i for i, c in enumerate(lines) if c.startswith("savejpg"))
        first_save = next(i for i, c in enumerate(lines) if c.startswith("save "))
        self.assertLess(
            first_save,
            first_jpeg,
            "a preview is attempted before anything has been saved",
        )

    def test_the_plain_stack_preview_is_taken_last(self) -> None:
        lines = self._script(PostOptions(background_removal=True, previews=True))
        jpegs = [c for c in lines if c.startswith("savejpg")]
        self.assertTrue(jpegs[-1].endswith("00_stacked 90") or "00_stacked" in jpegs[-1])


if __name__ == "__main__":
    unittest.main()
