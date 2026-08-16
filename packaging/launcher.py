"""Entry point for the packaged app.

A separate file because ``dwarf2siril/gui/app.py`` uses relative imports and
so cannot be run as a top-level script. This gives PyInstaller something
plain to start from.

It also turns a crash before the window exists into a message box rather than
a silent exit: the packaged build is windowed, so there is no console for a
traceback to land in and a bare failure would look like nothing happened at
all.
"""

from __future__ import annotations

import sys
import traceback
from types import SimpleNamespace


def _diagnose() -> int:
    """Print what the BUNDLE can actually do, and exit.

    Exists because "works when I run the source" is not evidence about the
    exe. Qt's image format support in particular comes from plugins that
    PyInstaller has to find and copy, and when one is missing an image load
    simply returns null with no error at all.

    Run:  set DWARF2SIRIL_DIAGNOSE=1 && Dwarf2Siril.exe
    """
    import os

    from PySide6.QtCore import QCoreApplication, QLibraryInfo
    from PySide6.QtGui import QImageReader
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)  # noqa: F841 - plugins load with the app
    formats = sorted(bytes(f).decode() for f in QImageReader.supportedImageFormats())
    print("frozen           :", getattr(sys, "frozen", False))
    print("meipass          :", getattr(sys, "_MEIPASS", "-"))
    print("plugin path      :", QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    print("library paths    :", QCoreApplication.libraryPaths())
    print("image formats    :", ", ".join(formats))
    print("JPEG readable    :", "jpeg" in formats or "jpg" in formats)

    # WHAT THE BUNDLE CHANGES ABOUT QT'S WORLD.
    # A layout defect shows in the packaged build and nowhere else, and every
    # layout check runs from source -- so whatever differs here is invisible
    # to all of them. That gap matters more than the pixels do.
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QGuiApplication

    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        print("screen           :", screen.name(), screen.geometry().width(),
              "x", screen.geometry().height())
        print("devicePixelRatio :", screen.devicePixelRatio())
        print("logical DPI      :", round(screen.logicalDotsPerInch(), 2))
        print("physical DPI     :", round(screen.physicalDotsPerInch(), 2))
    print("style            :", QApplication.style().objectName())
    default = QFont()
    print("default font     :", default.family(), default.pointSizeF(),
          "pt /", default.pixelSize(), "px")
    sample = QFont("Segoe UI Variable Text", 9)
    metrics = QFontMetrics(sample)
    print("sample metrics   : height", metrics.height(),
          "ascent", metrics.ascent(),
          "width('Denoise')", metrics.horizontalAdvance("Denoise"))
    families = QFontDatabase.families()
    print("font families    :", len(families))
    for wanted in ("Segoe UI Variable Text", "Segoe UI", "Inter"):
        print(f"  has {wanted:24}: {wanted in families}")

    target = os.environ.get("DWARF2SIRIL_DIAGNOSE_FILE", "")
    if target:
        from PySide6.QtGui import QImage

        image = QImage(target)
        print(f"direct load {target}")
        print(f"  null={image.isNull()} size={image.width()}x{image.height()}")

        # The path that actually matters: the worker thread, the queued
        # hand-back and the viewer. This is here so the viewer can be
        # exercised INSIDE THE BUNDLE without needing a mouse click -- the
        # gap that let a hang ship once already.
        from PySide6.QtCore import QTimer

        from dwarf2siril.gui.album import AlbumWindow

        window = AlbumWindow("Diagnostic", target)
        window.show()

        state = {"ticks": 0}

        def check() -> None:
            state["ticks"] += 1
            pixmap = window.view.pixmap()
            shown = pixmap is not None and not pixmap.isNull()
            if shown:
                print(f"  VIEWER: image shown after {state['ticks'] * 0.5:.1f}s "
                      f"({pixmap.width()}x{pixmap.height()})")
                app.quit()
            elif state["ticks"] >= 30:
                print(f"  VIEWER: STILL NOT SHOWN after 15s — "
                      f"text is {window.view.text()!r}")
                app.quit()
            else:
                QTimer.singleShot(500, check)

        QTimer.singleShot(500, check)
        app.exec()

    # The whole click path, end to end, in the packaged app.
    walk = os.environ.get("DWARF2SIRIL_WALKTHROUGH", "")
    if walk:
        return _walk_through(
            app, walk, os.environ.get("DWARF2SIRIL_WALKTHROUGH_OUT", "")
        )

    card = os.environ.get("DWARF2SIRIL_DIAGNOSE_CARD", "")
    if card:
        _diagnose_real_app(app, card)
    return 0


def find_clipping(window) -> list[str]:
    """Every visible thing that is cut off or crushed, at this window size.

    HORIZONTAL faults, which shipped once:

    * A widget whose right edge is past the window's own right edge. That
      is a whole column being too wide -- the sidebar overflowing took a
      BUTTON off screen, which is a broken feature, not a cosmetic one.
    * A widget that fits its parent but cannot draw its own text: a label
      that does not wrap and is narrower than the sentence it holds, or a
      button narrower than its own caption. This is the one that reads as
      "ends mid-word".

    VERTICAL faults, which shipped once as well, and which the horizontal
    checks were blind to. When a layout is given less height than its
    contents need, Qt does not refuse -- it squeezes every child below its
    minimum and then simply DRAWS THEM ON TOP OF EACH OTHER. On screen that
    is a slider painted across a label and buttons sliced in half.

    * A widget shorter than its own minimum height.
    * Two SIBLING widgets whose rectangles intersect. Siblings in a box
      layout can never legitimately overlap, so this one assertion catches
      the whole failure outright, whatever caused it.
    * A scroll area whose content cannot fit its viewport in either
      direction, which is the cause rather than the symptom.

    Neither scroll area here scrolls horizontally, so a right edge past the
    window is always a real defect and never something the user can reach.
    """
    from PySide6.QtWidgets import (
        QAbstractScrollArea,
        QCheckBox,
        QComboBox,
        QLabel,
        QPushButton,
    )

    problems: list[str] = []
    limit = window.width()

    # findChildren takes one type at a time, so gather then de-duplicate:
    # a QCheckBox is not a QLabel, but the lists can still overlap by
    # subclassing.
    candidates: list = []
    for kind in (QLabel, QPushButton, QCheckBox, QComboBox):
        for widget in window.findChildren(kind):
            if widget not in candidates:
                candidates.append(widget)

    for widget in candidates:
        if not widget.isVisible() or widget.width() <= 0:
            continue
        raw = widget.text() if hasattr(widget, "text") else widget.currentText()
        text = (raw or "").replace("\n", " ")[:44]

        right = widget.mapTo(window, widget.rect().topRight()).x()
        if right > limit:
            problems.append(
                f"{type(widget).__name__} runs {right - limit}px past the "
                f"window edge: {text!r}"
            )
            continue

        # Text wider than the widget that has to draw it. Wrapping labels are
        # exempt -- they are allowed to be narrow, they just get taller.
        if isinstance(widget, QLabel):
            if widget.wordWrap() or not (raw or "").strip():
                continue
            # A label showing a picture reports the PICTURE's size as its
            # hint, which says nothing about clipped text: the thumbnails are
            # deliberately a fixed size and scale their image to fit.
            if widget.pixmap() is not None and not widget.pixmap().isNull():
                continue
        # Rich text reports a sizeHint for the whole unwrapped run, which is
        # not a fair comparison; those are checked by eye in the screenshots.
        if isinstance(widget, QLabel) and "<" in (raw or ""):
            continue
        needed = widget.sizeHint().width()
        if needed > widget.width() + 1:
            problems.append(
                f"{type(widget).__name__} is {needed - widget.width()}px too "
                f"narrow for its own text: {text!r}"
            )

    # A scroll area whose contents are wider than its viewport clips them
    # silently, because both of ours have the horizontal bar switched off.
    for area in window.findChildren(QAbstractScrollArea):
        content = area.widget() if hasattr(area, "widget") else None
        if content is None or not area.isVisible():
            continue
        need = content.minimumSizeHint().width()
        have = area.viewport().width()
        if need > have:
            problems.append(
                f"{area.objectName() or 'scroll area'} content needs {need}px "
                f"in a {have}px viewport - clipped, with no way to scroll to it"
            )

    problems.extend(_find_squashing(window))
    problems.extend(_find_overlaps(window))
    return problems


def _find_squashing(window) -> list[str]:
    """Widgets drawn shorter than they can be drawn.

    Below its minimum a widget does not simply get smaller -- a button loses
    the bottom half of its own glyphs, a text box loses its last line. The
    tolerance is 1px for rounding, not for judgement.
    """
    from PySide6.QtWidgets import QAbstractScrollArea, QWidget

    problems = []
    for widget in window.findChildren(QWidget):
        if not widget.isVisible() or widget.height() <= 0:
            continue
        # A scroll area is ALLOWED to be shorter than its contents; that is
        # what scrolling is for. Its viewport is checked separately.
        if isinstance(widget, QAbstractScrollArea):
            continue

        # A DELIBERATELY fixed height is a decision, not an accident. The
        # group cards are all pinned to one height on purpose so a row of
        # them has a clean bottom edge, and the thumbnail is pinned to 16:9
        # so it is not letterboxed. Qt would prefer both a couple of pixels
        # taller; that preference is not a defect, and treating it as one
        # only teaches you to ignore the check. What this is looking for is
        # a widget squeezed by a layout that ran out of room.
        if widget.minimumHeight() and widget.minimumHeight() == widget.maximumHeight():
            continue

        floor = max(widget.minimumSizeHint().height(), widget.minimumHeight())
        if floor and widget.height() + 1 < floor:
            problems.append(
                f"{_name(widget)} is squashed to {widget.height()}px, "
                f"{floor - widget.height()}px below its minimum"
            )
    return problems


def _find_overlaps(window) -> list[str]:
    """Two siblings drawn on top of each other.

    THE ONE THAT WOULD HAVE CAUGHT THE OPERATOR'S SCREENSHOT OUTRIGHT.
    Children of a box layout are placed one after another and can never
    legitimately intersect, so any intersection means the layout ran out of
    room and started stacking things -- whatever the underlying cause. It
    needs no knowledge of what went wrong, only of what cannot be true.
    """
    from PySide6.QtWidgets import QLayout, QWidget

    problems = []
    for parent in window.findChildren(QWidget):
        layout = parent.layout()
        if layout is None or not parent.isVisible():
            continue
        managed = _laid_out(layout)
        for index, first in enumerate(managed):
            for second in managed[index + 1:]:
                overlap = first.geometry().intersected(second.geometry())
                # A shared edge is not an overlap; real collisions are many
                # pixels deep.
                if overlap.width() > 1 and overlap.height() > 1:
                    one, two = first.geometry(), second.geometry()
                    problems.append(
                        f"{_name(first)} [y{one.y()}+{one.height()}] and "
                        f"{_name(second)} [y{two.y()}+{two.height()}] are drawn "
                        f"on top of each other ({overlap.width()}x"
                        f"{overlap.height()}px) inside {_name(parent)} "
                        f"[{parent.width()}x{parent.height()}]"
                    )
    return problems


def _laid_out(layout) -> list:
    """Every visible widget this layout positions, nested layouts included."""
    from PySide6.QtWidgets import QLayout

    found = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is not None and widget.isVisible():
            found.append(widget)
        elif isinstance(item, QLayout):
            found.extend(_laid_out(item))
        elif item.layout() is not None:
            found.extend(_laid_out(item.layout()))
    return found


def _name(widget) -> str:
    label = widget.objectName() or type(widget).__name__
    text = getattr(widget, "text", None)
    if callable(text):
        try:
            words = (text() or "").replace("\n", " ").strip()[:28]
            if words:
                return f"{label}({words!r})"
        except Exception:  # noqa: BLE001
            pass
    return label


def _dump_column(window) -> None:
    """Every child of the sidebar column, with its numbers.

    So the packaged run and a source run can be compared line for line
    rather than by hypothesis. A defect that appears in one and not the
    other is a difference in numbers somewhere, and this is where it will
    show.
    """
    scroll = getattr(window, "sidebar_scroll", None)
    if scroll is None or scroll.widget() is None:
        return
    content = scroll.widget()
    print(f"      column: {content.width()}x{content.height()} "
          f"hint={content.sizeHint().height()} "
          f"viewport={scroll.viewport().height()} "
          f"scroll={scroll.verticalScrollBar().maximum()}")
    layout = content.layout()
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        if widget is None:
            print(f"        [{index}] spacer {item.sizeHint().height()}")
            continue
        if not widget.isVisible():
            continue
        geometry = widget.geometry()
        print(f"        [{index}] {_name(widget)[:34]:36} "
              f"y={geometry.y():5} h={geometry.height():5} "
              f"hint={widget.sizeHint().height():5} "
              f"minHint={widget.minimumSizeHint().height():5} "
              f"minH={widget.minimumHeight():5}")


def _click(widget) -> None:
    """A real mouse press and release on this widget, at its centre.

    Posted as actual QMouseEvents rather than calling click(): the point of
    this harness is to exercise the path a person takes, and a synthetic
    call skips everything between the button and the handler. This is as
    close to a finger on a trackpad as can be reached from inside the app.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    centre = QPointF(widget.rect().center())
    globally = QPointF(widget.mapToGlobal(widget.rect().center()))
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(
            widget,
            QMouseEvent(
                kind, centre, globally,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress
                else Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )


def _walk_through(app, card: str, output: str) -> int:
    """The whole path a person takes, in the artefact a person runs.

    Pick the drive, tick some extras, Prepare, Stack now, watch it, look at
    the result. Driven with real mouse events on the real window inside the
    packaged build, because every previous verification drove the code
    directly and the one time that diverged from a real click path, a hang
    shipped.

    The folder picker is the one step not driven here: it is an operating
    system dialog rather than anything this app draws, so the output folder
    is set the way the dialog would have set it.
    """
    import time
    from pathlib import Path

    from PySide6.QtCore import QTimer

    from dwarf2siril.gui import theme
    from dwarf2siril.gui.app import MainWindow

    app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(1636, 1171)
    window.show()

    started = time.monotonic()
    state = {"phase": "scan", "ticks": 0, "marks": [], "card": None}

    def mark(what: str) -> None:
        elapsed = time.monotonic() - started
        state["marks"].append((elapsed, what))
        print(f"  [{elapsed:7.1f}s] {what}", flush=True)

    mark(f"window open, scanning {card}")
    QTimer.singleShot(400, lambda: window._start_scan(Path(card)))

    def tick() -> None:
        state["ticks"] += 1
        phase = state["phase"]

        if phase == "scan":
            if not window.group_cards:
                if state["ticks"] > 120:
                    mark("SCAN NEVER FINISHED")
                    app.quit()
                return
            mark(f"{len(window.group_cards)} targets on the card")
            biggest = max(window.group_cards, key=lambda c: c.group.total_frames)
            state["card"] = biggest
            mark(f"chose {biggest.group.display_target} "
                 f"({biggest.group.total_frames} frames, "
                 f"{'with' if biggest.group.has_calibration else 'no'} darks)")

            window.output_dir = Path(output)
            window.output_field.setText(output)
            mark(f"output set to {output}")

            # Tick two extras the way a person does: by clicking them.
            for row, name in ((window.layers_card.background, "background removal"),
                              (window.layers_card.denoise, "denoise")):
                _click(row.checkbox)
                mark(f"ticked {name} -> {row.checkbox.isChecked()}")

            state["phase"] = "prepare"
            state["ticks"] = 0
            mark("clicking Prepare")
            _click(state["card"].build_button)
            return

        if phase == "prepare":
            if window.run_panel.isVisible() and window.run_panel.script_path:
                mark("project built; step 4 appeared")
                mark(f"Stack now enabled: {window.run_panel.stack_button.isEnabled()}")
                state["phase"] = "stack"
                state["ticks"] = 0
                mark("clicking Stack now in Siril")
                _click(window.run_panel.stack_button)
                return
            if state["ticks"] > 600:
                mark("BUILD NEVER FINISHED")
                app.quit()
            return

        if phase == "stack":
            worker = window.run_panel.worker
            if worker is not None and worker.isRunning():
                if state["ticks"] % 40 == 0:
                    mark(f"running: {window.run_panel.stage_line.text()}")
                return
            if worker is None:
                if state["ticks"] > 40:
                    mark("STACK NEVER STARTED")
                    app.quit()
                return
            mark("stack finished")
            mark(f"verdict: {window.run_panel.verdict.text()[:160]}")
            mark(f"preview panel visible: {window.preview_panel.isVisible()}")
            if window.preview_panel.isVisible():
                mark(f"preview stages: "
                     f"{[c for _k, c, _p in window.preview_panel.previews]}")
                mark(f"finding: {window.preview_panel.finding.text()[:200]}")
            problems = find_clipping(window)
            mark(f"layout problems at the end: {len(problems)}")
            for problem in problems[:4]:
                mark(f"   {problem}")
            state["phase"] = "done"
            app.quit()
            return

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(500)
    app.exec()
    print("\n  --- timeline ---")
    previous = 0.0
    for elapsed, what in state["marks"]:
        print(f"  {elapsed:8.1f}s  (+{elapsed - previous:6.1f})  {what}")
        previous = elapsed
    return 0


def _start_grid(window, state) -> None:
    """Open the stack grid and, immediately, a frame from it.

    Deliberately without waiting: asking for one big image while a few
    hundred tiles are still decoding is exactly the load that exposed the
    original bug.
    """
    from dwarf2siril.gui.framegrid import FrameViewer, StackGridWindow

    target = next((c for c in window.group_cards if c.group.sessions), None)
    if target is None:
        state["phase"] = "grid"
        return
    session = target.group.sessions[0]
    grid = StackGridWindow(session, {}, window)
    grid.show()
    state["grid"] = grid
    print(f"  grid open with {len(grid.tiles)} tiles; opening a frame at once")

    if grid.tiles:
        gallery = FrameViewer([t.item for t in grid.tiles], 0, grid)
        gallery.show()
        state["gallery"] = gallery
    state["phase"] = "grid"


def _check_after_the_run(app, window, folder: str) -> None:
    """Everything the app does AFTER Siril finishes, inside the bundle.

    *** WHY THIS EXISTS ***
    The harness used to stop at the frame gallery, which means it stopped at
    the exact point the app starts talking about RESULTS. The before/after
    panel, the run panel's verdict and the failure message were verified
    offscreen and nowhere else -- and offscreen is the half that has never
    caught anything, because the defects that shipped were about real fonts,
    real DPI and a real window. The album hang came from this same region.

    Driven against an ALREADY FINISHED output folder, so nothing is stacked
    and nothing is written. It only reads.
    """
    from pathlib import Path

    from dwarf2siril.postprocess import PostOptions
    from dwarf2siril.siril import interpret

    where = Path(folder)
    print(f"\nafter the run, against {where}")
    if not where.is_dir():
        print("  RESULT FOLDER MISSING -- skipped")
        return

    stack = next(
        (
            p.stem
            for p in sorted(where.glob("*.fit"))
            if not p.stem.endswith("_processed")
            and not p.stem.startswith(("starless_", "starmask_"))
        ),
        None,
    )
    if stack is None:
        print("  no stacked .fit in there -- skipped")
        return

    present = {p.stem for p in (where / "previews").glob("*.jpg")}
    print(f"  stack {stack!r}, {len(present)} previews on disk")

    # 1. THE PANEL LOADS AND SHOWS REAL PIXELS.
    panel = window.preview_panel
    ticked = PostOptions(background_removal=True, denoise=True, stretch=True)
    shown = panel.load_from(where, stack, ticked, solvable=True)
    print(f"  panel loads: {shown}, {len(panel.previews)} stages offered")
    if not shown:
        print("  PANEL REFUSED TO LOAD")
        return

    panel.show()
    for _ in range(12):
        app.processEvents()

    before = panel.swipe.before
    after = panel.swipe.after
    for name, pixmap in (("before", before), ("after", after)):
        if pixmap is None or pixmap.isNull():
            print(f"  SWIPE {name.upper()} IMAGE IS NULL -- nothing is drawn")
        else:
            print(f"  swipe {name}: {pixmap.width()}x{pixmap.height()}")

    # 2. THE MISSING-LAYER EXPLANATION, BOTH WAYS ROUND.
    # Ticked above but certainly absent from an old folder, so the panel has
    # to account for them rather than drop them.
    if panel.missing.isHidden():
        print("  MISSING LINE HIDDEN while ticked layers are absent")
    else:
        text = panel.missing.text()
        named = [n for n in ("Denoise", "Stretch") if n in text]
        print(f"  missing line names: {', '.join(named) or 'NOTHING'}")

    # And the other direction: nothing ticked, so nothing to explain.
    panel.load_from(where, stack, PostOptions(), solvable=True)
    for _ in range(6):
        app.processEvents()
    print(f"  with nothing ticked, missing line hidden: {panel.missing.isHidden()}")
    panel.load_from(where, stack, ticked, solvable=True)

    # 3. THE VERDICT, SUCCESS AND FAILURE, IN THE REAL PANEL.
    built = SimpleNamespace(
        script_path=where / f"{stack}.ssf",
        output_dir=where,
        lights_copied=350,
        darks_copied=30,
        linked=False,
        warnings=[],
        stages=[],
    )
    run = window.run_panel
    run.show_result(built, stack)
    run.show()

    image = where / f"{stack}.fit"
    run._on_finished(interpret(["log: Script execution finished successfully."],
                               exit_code=0, expected_image=image))
    for _ in range(6):
        app.processEvents()
    print(f"  verdict, success: {_plain(run.verdict.text())[:72]!r}")

    # The failure path, which no in-bundle check has ever seen. Real Siril
    # output from a real failed run, through the real interpreter.
    run._on_finished(interpret(
        [
            "log: Error in line 22 ('stack'): not enough images.",
            "log: Script execution failed.",
        ],
        exit_code=1,
        expected_image=None,
    ))
    for _ in range(6):
        app.processEvents()
    print(f"  verdict, failure: {_plain(run.verdict.text())[:72]!r}")

    run._on_failed("Siril could not be started.")
    for _ in range(6):
        app.processEvents()
    print(f"  verdict, no siril: {_plain(run.verdict.text())[:72]!r}")

    # 4. AND NONE OF IT MAY CLIP. This is the state the window has never
    # been measured in: the result panel is only built after a run, so every
    # clipping check so far has run on a window that did not have one.
    original = window.size()
    for wide, high in ((1636, 1171), (1280, 880), (1000, 680)):
        window.resize(wide, high)
        for _ in range(24):
            app.processEvents()
        clipped = find_clipping(window)
        print(f"  {wide}x{high} with the result showing: "
              + (f"CLIPPED - {len(clipped)} problems" if clipped
                 else "nothing clipped"))
        for problem in clipped[:8]:
            print(f"      {problem}")
    window.resize(original)
    app.processEvents()


def _plain(markup: str) -> str:
    """Rich text with the tags taken out, so a verdict prints readably."""
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", markup)).strip()


def _finish(app, window, state) -> None:
    """Close the grid, run the after-the-run checks if asked, then quit.

    The grid and gallery are shut first: they are separate windows sitting
    over the main one, and find_clipping measures the main window, so
    leaving them open would measure the wrong thing.
    """
    import os

    for key in ("gallery", "grid"):
        extra = state.get(key)
        if extra is not None:
            try:
                extra.close()
            except Exception:  # noqa: BLE001 - closing a window is not worth failing on
                pass
    app.processEvents()

    folder = os.environ.get("DWARF2SIRIL_DIAGNOSE_RESULT", "")
    if folder:
        try:
            _check_after_the_run(app, window, folder)
        except Exception:  # noqa: BLE001
            import traceback as tb

            print("  AFTER-THE-RUN CHECK RAISED:")
            print("    " + tb.format_exc().replace("\n", "\n    "))
    app.quit()


def _diagnose_real_app(app, card: str) -> int:
    """Open the REAL window on a real card and open a viewer, inside the exe.

    This exists because the viewer hang shipped once already, in the one
    path that could not be exercised in the bundle: a click on a plain
    QLabel, which synthetic input does not reach. Driving the real window
    here closes that gap -- the album loads under exactly the conditions
    that matter, with a full card scanned and every card thumbnail decoding
    at the same time.
    """
    from pathlib import Path

    from PySide6.QtCore import QTimer

    from dwarf2siril.gui import theme
    from dwarf2siril.gui.app import MainWindow

    app.setStyleSheet(theme.stylesheet())
    window = MainWindow()
    window.resize(1280, 900)
    window.show()
    print(f"scanning {card} ...")
    QTimer.singleShot(300, lambda: window._start_scan(Path(card)))

    state = {"phase": "scan", "ticks": 0, "viewer": None}

    def tick() -> None:
        state["ticks"] += 1
        elapsed = state["ticks"] * 0.5

        if state["phase"] == "scan":
            if window.group_cards:
                shown = sum(
                    1 for c in window.group_cards if c._thumbnail_holder.isVisible()
                )
                print(f"  {len(window.group_cards)} cards, {shown} thumbnails shown")
                if shown or elapsed > 8:
                    target = next(
                        (c for c in window.group_cards if c.group.album_image), None
                    )
                    if target is None:
                        print("  no card has an album image")
                        app.quit()
                        return
                    # Same check the layout test runs, but here it runs on a
                    # real card inside the packaged app, where the fonts and
                    # the DPI are the operator's rather than the test's.
                    original = window.size()
                    for wide, high in ((1636, 1171), (1280, 880), (1000, 680)):
                        window.resize(wide, high)
                        # Several passes, not one. A Qt layout settles over
                        # a few turns of the event loop -- a wrapping label
                        # cannot say how tall it is until it knows how wide
                        # it is, and its panel cannot until the label has.
                        # A real user gets those turns between one frame and
                        # the next; measuring after a single one reports a
                        # half-finished layout as a defect.
                        for _ in range(24):
                            app.processEvents()
                        clipped = find_clipping(window)
                        print(f"  {wide}x{high}: "
                              + (f"CLIPPED - {len(clipped)} problems"
                                 if clipped else "nothing clipped"))
                        for problem in clipped[:8]:
                            print(f"      {problem}")
                        if wide == 1636:
                            _dump_column(window)
                    window.resize(original)
                    app.processEvents()

                    print(f"  opening the album for {target.group.display_target}")
                    target._open_album()
                    state["viewer"] = getattr(target, "_album_window", None)
                    state["phase"] = "viewer"
                    state["ticks"] = 0
            elif elapsed > 30:
                print("  scan never produced cards")
                app.quit()
                return

        elif state["phase"] == "viewer":
            viewer = state["viewer"]
            if viewer is None:
                print("  VIEWER NEVER OPENED")
                app.quit()
                return
            pixmap = viewer.view.pixmap()
            if pixmap is not None and not pixmap.isNull():
                print(f"  ALBUM OK: image shown after {elapsed:.1f}s "
                      f"({pixmap.width()}x{pixmap.height()})")
                viewer.accept()
                _start_grid(window, state)
                state["ticks"] = 0
                QTimer.singleShot(500, tick)
                return
            if elapsed >= 25:
                print(f"  ALBUM FAILED: still {viewer.view.text()!r} after {elapsed}s")
                app.quit()
                return

        elif state["phase"] == "grid":
            # The heavy case: a frame gallery opened while a few hundred
            # tile thumbnails are still decoding. This is the combination
            # that broke, so it is the combination worth proving.
            gallery = state.get("gallery")
            if gallery is None:
                if elapsed > 20:
                    print("  GALLERY NEVER OPENED")
                    app.quit()
                    return
            else:
                pixmap = gallery.view.pixmap()
                if pixmap is not None and not pixmap.isNull():
                    print(f"  GALLERY OK: frame shown after {elapsed:.1f}s "
                          f"({pixmap.width()}x{pixmap.height()})")
                    _finish(app, window, state)
                    return
                if elapsed >= 25:
                    print(f"  GALLERY FAILED: still {gallery.view.text()!r} "
                          f"after {elapsed}s")
                    _finish(app, window, state)
                    return

        QTimer.singleShot(500, tick)

    QTimer.singleShot(500, tick)
    app.exec()
    return 0


def main() -> int:
    import os

    if os.environ.get("DWARF2SIRIL_DIAGNOSE") == "1":
        return _diagnose()
    try:
        from dwarf2siril.gui.app import main as gui_main

        return gui_main()
    except Exception:
        detail = traceback.format_exc()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            box = QMessageBox()
            box.setWindowTitle("Dwarf2Siril could not start")
            box.setText("Dwarf2Siril could not start.")
            box.setInformativeText(
                "Something went wrong before the window opened. The details "
                "below are worth reporting."
            )
            box.setDetailedText(detail)
            box.setIcon(QMessageBox.Icon.Critical)
            box.exec()
        except Exception:
            # If even Qt is unavailable there is nowhere left to show this.
            sys.stderr.write(detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
