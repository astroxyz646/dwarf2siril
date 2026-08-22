"""Make Windows draw its own title bar in the app's colours.

Windows 11 (build 22000 and later) lets an application set the caption
colour, caption text colour and border colour of the REAL title bar through
DwmSetWindowAttribute. That is worth far more than drawing our own: snap
layouts, drag-to-edge, double-click to maximise, rounded corners, the system
menu, multi-monitor and per-monitor DPI all keep working, because Windows is
still the one drawing the frame.

Reached through ctypes, which is in the standard library, so this costs no
dependency.

Everything here fails silently by design. On Windows 10, on another OS, or if
any call fails for any reason, the window simply keeps its ordinary title
bar. A cosmetic touch is never worth an error message, let alone a crash.

The constants below were read out of the Windows SDK on this machine
(10.0.26100 dwmapi.h) rather than recalled:

    DWMWA_USE_IMMERSIVE_DARK_MODE   = 20
    DWMWA_WINDOW_CORNER_PREFERENCE  = 33
    DWMWA_BORDER_COLOR              = 34
    DWMWA_CAPTION_COLOR             = 35
    DWMWA_TEXT_COLOR                = 36
"""

from __future__ import annotations

import sys

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_BORDER_COLOR = 34
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

# Caption colouring arrived with Windows 11. Asking for it on Windows 10
# returns a failure code, which is handled, but there is no reason to try.
MIN_BUILD_FOR_CAPTION_COLOUR = 22000


def _colorref(hex_colour: str) -> int:
    """Turn '#RRGGBB' into a Win32 COLORREF.

    COLORREF is 0x00BBGGRR -- blue in the HIGH byte -- per the SDK's own
    RGB macro: r | (g << 8) | (b << 16). Getting this backwards does not
    fail, it just quietly paints the wrong colour, which is why it is one
    small function with the byte order written down.
    """
    value = hex_colour.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return red | (green << 8) | (blue << 16)


def _windows_build() -> int:
    try:
        return sys.getwindowsversion().build  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0


def apply_titlebar(
    window_id, caption: str, text: str, border: str, dark: bool = True
) -> bool:
    """Colour one window's native title bar. True if Windows accepted it.

    ``window_id`` is whatever ``QWidget.winId()`` returned. Call it after the
    window has been shown, because the native handle does not exist before
    then.

    ``dark`` is the app's own palette telling Windows which way round the
    caption is. It used to be hard-coded on, which was right while there was
    only ever a dark theme; on the light palette it makes Windows draw light
    caption text on our light caption, and the buttons vanish.
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(window_id))
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]

        def set_attribute(attribute: int, value: ctypes.c_int) -> bool:
            # S_OK is 0; anything else means Windows declined, which is a
            # normal answer on an older build rather than a problem.
            return (
                dwm.DwmSetWindowAttribute(
                    hwnd,
                    wintypes.DWORD(attribute),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                == 0
            )

        # Dark mode first. On its own this already gives a dark caption and
        # light caption text, so it is the part that matters most and the
        # only part Windows 10 (2004+) will honour. It is also the ONLY
        # signal a light palette has on Windows 10, where the explicit
        # caption colours below are refused.
        set_attribute(
            DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(1 if dark else 0)
        )

        if _windows_build() < MIN_BUILD_FOR_CAPTION_COLOUR:
            return False

        accepted = set_attribute(
            DWMWA_CAPTION_COLOR, ctypes.c_int(_colorref(caption))
        )
        set_attribute(DWMWA_TEXT_COLOR, ctypes.c_int(_colorref(text)))
        set_attribute(DWMWA_BORDER_COLOR, ctypes.c_int(_colorref(border)))
        return accepted
    except Exception:  # noqa: BLE001 - a title bar is never worth failing over
        return False
