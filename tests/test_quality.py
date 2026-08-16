"""Tests for dropping frames the weather ruined.

The log fixtures below are verbatim lines from a real Siril 1.4.4 run over
the 350-frame C 27 group, so the parser is pinned to wording that actually
occurred rather than wording I imagined.
"""

from __future__ import annotations

import unittest

from dwarf2siril.quality import (
    ALARM_KEPT_FRACTION,
    DEFAULT_STRENGTH,
    QualityFilter,
    parse_log,
)

# From the real two-night C 27 run.
REAL_LOG = [
    "log: Warning: some images don't have information available for best "
    "images selection, using only available data (303 images on 350).",
    "log: Using selected images filter (303/350 of the sequence)",
    "log: Processing images of the sequence with a weighted FWHM lower or "
    "equal than 11.447 (286), processing images of the sequence with a "
    "roundness higher or equal than 0.726814 (285), processing images of the "
    "sequence with a background lower or equal than 0.000870093 (299), "
    "processing images of the sequence with a number of stars higher or "
    "equal than 198 (292), for a total of images processed of 280)",
    "log: Integration of 10 images on 10 of the sequence:",
    "log: Integration of 280 images on 280 of the sequence:",
]


class FilterSettingTests(unittest.TestCase):
    def test_on_by_default(self) -> None:
        # Dropping obviously ruined frames is what a beginner wants and would
        # never think to ask for.
        options = QualityFilter()
        self.assertTrue(options.enabled)
        self.assertTrue(options.active)
        self.assertEqual(options.strength, DEFAULT_STRENGTH)

    def test_off_produces_no_arguments(self) -> None:
        options = QualityFilter(enabled=False)
        self.assertFalse(options.active)
        self.assertEqual(options.filter_arguments(), [])

    def test_covers_all_four_faults(self) -> None:
        arguments = " ".join(QualityFilter().filter_arguments())
        # Cloud needs background AND star count; FWHM alone would miss it.
        self.assertIn("-filter-bkg=", arguments)
        self.assertIn("-filter-nbstars=", arguments)
        self.assertIn("-filter-wfwhm=", arguments)
        self.assertIn("-filter-round=", arguments)

    def test_uses_k_sigma_not_absolute_thresholds(self) -> None:
        # k-sigma adapts to the night; an absolute FWHM would be wrong on
        # every night but the one it was tuned on.
        for argument in QualityFilter().filter_arguments():
            self.assertTrue(argument.endswith("k"), argument)

    def test_gentler_settings_keep_more(self) -> None:
        gentle = QualityFilter(strength="gentle").k
        balanced = QualityFilter(strength="balanced").k
        strict = QualityFilter(strength="strict").k
        self.assertGreater(gentle, balanced)
        self.assertGreater(balanced, strict)


class ParseRealLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = parse_log(REAL_LOG, total_frames=350)

    def test_counts_are_against_the_original_total(self) -> None:
        # Siril's own "on 280 of the sequence" refers to the already-filtered
        # sequence, so reporting it would claim 280 of 280.
        self.assertEqual(self.report.total, 350)
        self.assertEqual(self.report.used, 280)
        self.assertEqual(self.report.dropped, 70)

    def test_separates_unregisterable_from_quality_drops(self) -> None:
        self.assertEqual(self.report.unregistered, 47)
        self.assertEqual(self.report.filtered, 23)

    def test_explains_faults_in_english_not_numbers(self) -> None:
        detail = " ".join(self.report.detail())
        self.assertIn("could not be aligned", detail)
        self.assertIn("trailed", detail)
        self.assertIn("clouded", detail)
        for number in ("11.447", "0.7268", "wFWHM"):
            self.assertNotIn(number, detail)

    def test_says_the_faults_overlap(self) -> None:
        self.assertTrue(any("overlap" in line for line in self.report.detail()))

    def test_a_normal_run_is_not_flagged_as_wrong(self) -> None:
        self.assertAlmostEqual(self.report.kept_fraction, 0.8)
        self.assertFalse(self.report.looks_wrong)


class GuardrailTests(unittest.TestCase):
    def test_losing_most_of_a_session_is_flagged(self) -> None:
        # Quietly handing back a stack of four frames would be worse than
        # saying something is wrong.
        report = parse_log(
            ["log: Integration of 20 images on 20 of the sequence:"], total_frames=350
        )
        self.assertTrue(report.looks_wrong)
        self.assertLess(report.kept_fraction, ALARM_KEPT_FRACTION)

    def test_nothing_dropped_reads_cleanly(self) -> None:
        report = parse_log(
            ["log: Integration of 350 images on 350 of the sequence:"], total_frames=350
        )
        self.assertEqual(report.dropped, 0)
        self.assertIn("All 350", report.summary())
        self.assertEqual(report.detail(), [])

    def test_an_unparsable_log_is_not_a_failure(self) -> None:
        report = parse_log(["log: something entirely different"], total_frames=350)
        self.assertEqual(report.used, 0)
        self.assertEqual(report.reasons, [])


if __name__ == "__main__":
    unittest.main()
