"""Load images without stalling the window, and without losing the result.

Images are decoded on a worker thread and handed back to the UI thread,
because a 3840x2160 JPEG is not something to open on the UI thread and a
grid that hitches while scrolling is a regression.

*** WHY THE OWNERSHIP HERE LOOKS FUSSY ***
The obvious version of this puts the result signal on the QRunnable itself.
It works when you try it, and then it hangs on "Loading..." forever in a
packaged build, with no error anywhere. The reason:

    QThreadPool DELETES the runnable as soon as run() returns. A queued
    cross-thread signal is delivered later, on the receiving thread's event
    loop -- and Qt silently DISCARDS a queued invocation whose sender was
    destroyed in the meantime. The result never arrives, nothing raises,
    and the placeholder stays up.

Whether the deletion wins the race depends on timing, which is why it can
look fine in a source run and fail in the bundle, and why a small thumbnail
survives while a large image does not.

So the signal lives on its OWN object with its own lifetime, held in a
module-level registry until it has actually delivered. The runnable may be
destroyed the instant it finishes; the result no longer depends on it.

The second rule here: a load must always end. Every branch calls back
exactly once -- with an image or with None -- and a watchdog turns a hang
into a plain message rather than an eternal "Loading...".
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal

# Card-sized, and deliberately small. The thumbnail is there to be recognised
# at a glance, not examined; the numbers beside it are the headline.
THUMBNAIL_WIDTH = 104

# No single image should take longer than this. If one does, something is
# wrong -- an unreadable file on a slow removable drive, a thread that never
# ran -- and the user is told rather than left watching a placeholder.
DEFAULT_TIMEOUT_MS = 20_000

# Loads that have not yet delivered. This is what keeps the receiving object
# alive long enough for a queued signal to arrive; without it the loader can
# be collected and the delivery is dropped in silence.
_in_flight: set["_Loader"] = set()


class _Loader(QObject):
    """Owns the result signal, independently of the worker that produces it."""

    done = Signal(object)   # QImage, or None if it could not be read

    def __init__(self, on_ready, timeout_ms: int) -> None:
        super().__init__()
        self._on_ready = on_ready
        self._delivered = False

        self.done.connect(self._deliver)

        # Belt and braces: if the worker never reports back at all, this
        # turns the silence into an answer.
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setInterval(timeout_ms)
        self._watchdog.timeout.connect(self._on_timeout)
        self._watchdog.start()

    def _deliver(self, image) -> None:
        # Exactly once, whichever arrives first.
        if self._delivered:
            return
        self._delivered = True
        self._watchdog.stop()
        try:
            self._on_ready(image)
        finally:
            _in_flight.discard(self)

    def _on_timeout(self) -> None:
        if not self._delivered:
            self._deliver(None)


class _LoadTask(QRunnable):
    """Decodes one image. May be destroyed the moment it finishes."""

    def __init__(self, loader: _Loader, path: Path, width: int) -> None:
        super().__init__()
        self._loader = loader
        self._path = path
        self._width = width

    def run(self) -> None:
        from PySide6.QtGui import QImage

        try:
            image = QImage(str(self._path))
            if image.isNull():
                # Present but not readable as an image: a truncated write, or
                # something else wearing a .jpg name.
                self._loader.done.emit(None)
                return
            # width <= 0 means full size, which is what the viewers want:
            # they scale to the window and rescale when it changes.
            if self._width > 0 and image.width() > self._width:
                image = image.scaledToWidth(
                    self._width, Qt.TransformationMode.SmoothTransformation
                )
            self._loader.done.emit(image)
        except Exception:  # noqa: BLE001 - an image is never worth a crash
            self._loader.done.emit(None)


def load_async(
    path: Path,
    on_ready,
    width: int = THUMBNAIL_WIDTH,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> None:
    """Decode ``path`` off the UI thread and hand the result back on it.

    ``on_ready`` is called EXACTLY ONCE: with a QImage, or with None if the
    image could not be read or took too long. Callers must treat None as a
    real answer and say so on screen -- never leave a placeholder up.
    """
    loader = _Loader(on_ready, timeout_ms)
    _in_flight.add(loader)
    QThreadPool.globalInstance().start(_LoadTask(loader, Path(path), width))
