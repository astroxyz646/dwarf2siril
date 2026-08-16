"""The progress bar's promises, tested against real Siril output.

Every line below is copied verbatim from the log of an actual 350-frame
C 27 run, because the log is the specification and the two defects this
module has had were both invisible to a made-up one.
"""

from __future__ import annotations

import unittest

from dwarf2siril.postprocess import PostOptions
from dwarf2siril.progress import RunProgress, plan_stages


def track(lines, stages=None, frames=350):
    tracker = RunProgress(stages or plan_stages(350, 10), frames)
    seen = []
    for line in lines:
        update = tracker.feed(line)
        if update is not None:
            seen.append(update)
    return tracker, seen


class PlanTests(unittest.TestCase):
    def test_weights_add_up_to_one(self) -> None:
        total = sum(s.weight for s in plan_stages(350, 10, layers=("starnet",)))
        self.assertAlmostEqual(1.0, total, places=6)

    def test_the_long_stages_dominate(self) -> None:
        """A bar where the trivial steps take a quarter of it is a bad bar."""
        stages = {s.command: s.weight for s in plan_stages(350, 10)}
        self.assertGreater(stages["calibrate"], 0.4)

    def test_a_dwarf_master_dark_still_gets_a_calibrate_stage(self) -> None:
        """No dark frames to stack, but the lights are still calibrated.

        Getting this wrong would leave the bar with a stage that never
        starts, or a calibrate the bar does not know is coming.
        """
        stages = plan_stages(350, dark_count=0, has_calibration=True)
        commands = [s.command for s in stages]
        self.assertIn("calibrate", commands)
        self.assertEqual(1, commands.count("convert"))

    def test_layers_appear_in_script_order(self) -> None:
        post = PostOptions(
            background_removal=True, plate_solve=True,
            colour_calibration=True, star_reduction=True,
        )
        self.assertEqual(
            ["subsky", "platesolve", "pcc", "starnet", "pm"],
            post.siril_stages(),
        )


class ParsingTests(unittest.TestCase):
    def test_a_stale_hundred_percent_does_not_slam_the_new_stage(self) -> None:
        """The defect that froze the bar for 168 seconds of a 297-second run.

        Siril prints the PREVIOUS operation's closing 100% after the next
        command has already started. Believed, it finishes the new stage on
        its first line, and every real reading afterwards looks like going
        backwards and is refused.
        """
        _tracker, seen = track([
            "log: Running command: convert",
            "log: Running command: stack",
            "log: Running command: convert",
            "progress: , 100.00%",
            "log: Running command: calibrate",
            "progress: 100.00%",          # still the convert talking
            "progress: 100.00%",
            "progress: 0.00%",
            "progress: Preprocessing. Processing image 182 (light_00182.fit), 0.57%",
        ])
        self.assertLess(seen[-1].fraction, 0.05, "the bar ran away on a stale 100%")
        self.assertIn("Subtracting the darks", seen[-1].label)

    def test_the_frame_count_only_goes_up(self) -> None:
        """Siril reports image NUMBERS, and 16 threads finish out of order.

        A real run showed "333 of 350" and then "22 of 350", which reads as
        something having gone wrong. What the user is owed is how many are
        done, which only ever increases.
        """
        _tracker, seen = track([
            "log: Running command: convert",
            "log: Running command: stack",
            "log: Running command: convert",
            "log: Running command: calibrate",
            "progress: Preprocessing. Processing image 182 (light_00182.fit), 0.57%",
            "progress: Preprocessing. Processing image 3 (light_00003.fit), 0.86%",
            "progress: Preprocessing. Processing image 97 (light_00097.fit), 1.14%",
        ])
        counted = [s.label for s in seen if "of 350" in s.label]
        self.assertEqual(
            ["1 of 350", "2 of 350", "3 of 350"],
            [label.split("— ")[1] for label in counted],
        )

    def test_it_never_goes_backwards(self) -> None:
        """Registration counts 0-100 twice: once measuring, once transforming."""
        _tracker, seen = track([
            "log: Running command: convert",
            "log: Running command: stack",
            "log: Running command: convert",
            "log: Running command: calibrate",
            "progress: 50.00%",
            "log: Running command: register",
            "progress: 0.10%",
            "progress: 90.00%",
            "progress: 0.10%",     # second pass restarts
            "progress: 20.00%",
        ])
        fractions = [s.fraction for s in seen]
        self.assertEqual(sorted(fractions), fractions)

    def test_it_never_reaches_one_before_siril_says_so(self) -> None:
        lines = ["log: Running command: convert",
                 "log: Running command: stack",
                 "log: Running command: convert",
                 "log: Running command: calibrate",
                 "progress: 1.00%"] + ["progress: 100.00%"] * 5
        tracker, seen = track(lines)
        self.assertLess(max(s.fraction for s in seen), 1.0)
        self.assertFalse(tracker.finished)

        update = tracker.feed("log: Script execution finished successfully.")
        self.assertEqual(1.0, update.fraction)
        self.assertTrue(tracker.finished)

    def test_a_finished_stage_sweeps_rather_than_freezing(self) -> None:
        """Siril goes quiet while it writes the result -- 26s on a 350 stack.

        A determinate bar standing still at 99% is exactly the "is it stuck?"
        the bar exists to prevent, so a stage with nothing left to report
        hands back an honest sweep instead.
        """
        _tracker, seen = track([
            "log: Running command: convert",
            "log: Running command: stack",
            "log: Running command: convert",
            "log: Running command: calibrate",
            "progress: 1.00%",
            "progress: 100.00%",
        ])
        self.assertFalse(seen[-1].determinate)
        self.assertIn("writing the result", seen[-1].label)

    def test_layers_with_no_signal_are_honest_about_it(self) -> None:
        stages = plan_stages(350, 10, layers=("starnet",))
        tracker = RunProgress(stages, 350)
        update = None
        for line in ("log: Running command: convert",
                     "log: Running command: stack",
                     "log: Running command: convert",
                     "log: Running command: calibrate",
                     "log: Running command: register",
                     "log: Running command: seqapplyreg",
                     "log: Running command: stack",
                     "log: Running command: starnet"):
            result = tracker.feed(line)
            if result is not None:
                update = result
        self.assertIsNotNone(update)
        self.assertFalse(update.determinate)
        self.assertIn("Separating the stars", update.label)

    def test_unknown_output_is_ignored_rather_than_fatal(self) -> None:
        tracker = RunProgress(plan_stages(350, 10), 350)
        for line in ("something entirely different",
                     "progress: nonsense%",
                     "log: Running command: teleport"):
            self.assertIsNone(tracker.feed(line))
        self.assertEqual(0.0, tracker.fraction)


if __name__ == "__main__":
    unittest.main()
