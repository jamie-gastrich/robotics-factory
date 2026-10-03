# Copyright 2026 jamie
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Node that draws the safe zone marker over the turtlesim canvas.

turtlesim cannot be given a custom image. ``/spawn`` carries no texture field,
the parameters on ``/turtlesim`` do not select an image, and every sprite the
window draws comes from the thirteen files turtlesim opened at startup, so the
only way to show a PNG on its canvas is to paint it in a window of our own,
exactly over the canvas. This node does that and nothing else.

It finds the turtlesim window through libX11 with ctypes, keeps a frameless,
translucent, input-transparent window over the canvas, and draws the marker into
the pixels the start zone occupies inside it. It is deliberately not part of the
rescue_manager: that node's state is scoped to one (rescuer, victim) pair, this
overlay is scoped to one canvas, and Version 3 will have several pairs on one
canvas, so the two are kept apart.

Nothing here reads or writes game state, and nothing is subscribed to. The
marker is not drawn into turtlesim's canvas, so ``/clear`` cannot erase it and
there is no clear to redeploy. What a click on the window, a move and a resize do
change is where the overlay is and whether it is on top, so one timer re-finds
the window and re-asserts the geometry and the stacking. That is the mechanism,
and it is also why the launch file forces turtlesim onto X11: a Wayland window
has no geometry another process can find.

PySide6 is imported inside the three functions that need it, so importing this
module requires neither Qt nor a display, and the headless path never gets that
far at all.

libX11's default error handler prints to stderr and calls ``exit(1)``, and the
lookup walks the whole window tree five calls deep ten times a second, so a
window destroyed between two of those calls would take the process with it: no
ROS log, no shutdown, exit code 1. Every display this module opens gets a
handler that counts the errors and swallows them instead, and the count is
logged, because swallowing is right for a window that went away and wrong for a
display that is permanently broken.
"""

import ctypes
from dataclasses import dataclass
import os
import sys
from typing import Any

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.exceptions import InvalidNodeNameException
from rclpy.exceptions import ParameterException
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from rclpy.timer import Timer

from .arg_overrides import parameter_overrides
from .geometry import Box
from .geometry import PixelRect
from .geometry import zone_to_pixel_rect
from .validation import safe_zone_configuration_errors

#: Zone defaults, half-width 0.6 around the measured start pose.
DEFAULT_ZONE_MIN = 4.944
DEFAULT_ZONE_MAX = 6.144

#: World extent of a stock turtlesim canvas, measured by driving a turtle into
#: each wall: the walls are at 11.088889, which is where the rescuer spawns from.
#: Not the 11.54 that older turtlesim builds reported.
DEFAULT_WORLD_WIDTH_M = 11.088889
DEFAULT_WORLD_HEIGHT_M = 11.088889

#: Canvas size in pixels, read out of this build's QImage and confirmed against
#: the window. Another build needs these two changed, and the node says so in
#: the log when the window it finds disagrees with them.
DEFAULT_CANVAS_WIDTH_PX = 500.0
DEFAULT_CANVAS_HEIGHT_PX = 500.0

#: Where the canvas sits inside the window's client area. Zero here because the
#: QImage is the same size as the client area, so the two origins are one origin.
DEFAULT_CANVAS_MARGIN_PX = 0.0

#: How often the window is re-found and the overlay is put back on top of it.
DEFAULT_TRACK_PERIOD_S = 0.1

#: Window identity as it actually appears on this machine, title and WM class
#: both matched exactly. The title is TurtleSim, capital S.
DEFAULT_WINDOW_TITLE = 'TurtleSim'
DEFAULT_WINDOW_CLASS = 'turtlesim_node'

#: Title of the overlay window itself, so a human can tell the two apart in the
#: window list. Deliberately not the turtlesim title, which would make the
#: overlay a second candidate for this node's own lookup.
DEFAULT_OVERLAY_WINDOW_TITLE = 'rescue_turtle_safe_zone'

#: Where the marker is installed, relative to this package's share directory.
PACKAGE_NAME = 'rescue_turtle'
MEDIA_SUBDIRECTORY = 'media'
DEFAULT_IMAGE_FILE = 'safe_zone.png'

#: The node's own name. Not derived from a pair: the overlay is scoped to a
#: canvas, and in Version 3 one canvas is shared by several pairs.
DEFAULT_NODE_NAME = 'safe_zone'

#: Logger name for a failure that happens before the node exists.
STARTUP_LOG_NAME = 'rescue_turtle_safe_zone'

#: X11 calls return this on success.
X_SUCCESS = 0

#: ``XWindowAttributes.map_state`` for a window that is on screen.
IS_VIEWABLE = 2

#: ``XWindowAttributes.class`` for a window that can be drawn on.
INPUT_OUTPUT = 1

#: ``XAnyPropertyType``, i.e. do not require a particular property type.
X_ANY_PROPERTY_TYPE = 0

#: How much of a window name to read. A title longer than this cannot match a
#: configured one anyway, so this only bounds the request.
MAX_NAME_LENGTH = 1024

#: How deep into the window tree the search will walk. The tree is not the
#: untrusted input here, but this timer runs ten times a second forever, so the
#: bound is cheap insurance against a pathological window manager.
MAX_TREE_DEPTH = 32

#: How often the swallowed X11 error count is reported. At the default 0.1 s
#: period that is every 30 s: often enough that a display broken for a minute is
#: not silent, rare enough not to bury the rest of the log.
ERROR_REPORT_EVERY_TICKS = 300

#: How often the overlay's realised geometry is re-stated even when nothing
#: changed, so a placement the window manager overrode and then kept is still
#: noticed rather than logged once and forgotten.
PLACEMENT_REPORT_EVERY_TICKS = 300

#: The X11 library the lookup binds to. Not a parameter: there is one of it, and
#: the version is chosen by the system rather than by us.
LIB_X11 = 'libX11.so.6'


class _XClassHint(ctypes.Structure):
    """The ``XClassHint`` libX11 fills in: the window's WM_NAME and WM_CLASS."""

    _fields_ = [
        ('res_name', ctypes.c_void_p),
        ('res_class', ctypes.c_void_p),
    ]


class _XWindowAttributes(ctypes.Structure):
    """
    The ``XWindowAttributes`` libX11 fills in.

    Only three fields are read, but the struct is declared whole because its
    offsets depend on every field before them: pulling the last field forward
    would make ctypes read whatever happens to sit in memory instead.
    """

    _fields_ = [
        ('x', ctypes.c_int),
        ('y', ctypes.c_int),
        ('width', ctypes.c_int),
        ('height', ctypes.c_int),
        ('border_width', ctypes.c_int),
        ('depth', ctypes.c_int),
        ('visual', ctypes.c_void_p),
        ('root', ctypes.c_ulong),
        # The C field is called class, which is a python keyword, so the name
        # here ends in an underscore. ctypes matches on position, not name.
        ('class_', ctypes.c_int),
        ('bit_gravity', ctypes.c_int),
        ('win_gravity', ctypes.c_int),
        ('backing_store', ctypes.c_int),
        ('backing_planes', ctypes.c_ulong),
        ('backing_pixel', ctypes.c_ulong),
        ('save_under', ctypes.c_int),
        ('colormap', ctypes.c_ulong),
        ('map_installed', ctypes.c_int),
        ('map_state', ctypes.c_int),
        ('all_event_masks', ctypes.c_long),
        ('your_event_mask', ctypes.c_long),
        ('do_not_propagate_mask', ctypes.c_long),
        ('override_redirect', ctypes.c_int),
        ('screen', ctypes.c_void_p),
    ]


class _XErrorEvent(ctypes.Structure):
    """
    The ``XErrorEvent`` libX11 passes to an error handler.

    No field is read: the handler counts and swallows. The struct is declared
    anyway because the callback signature has to name a real pointer type, and
    because a future reader who wants to tell BadWindow from BadDrawable has
    somewhere to read it from instead of guessing at an ``XErrorEvent``'s layout.
    """

    _fields_ = [
        ('type', ctypes.c_int),
        ('display', ctypes.c_void_p),
        ('resourceid', ctypes.c_ulong),
        ('serial', ctypes.c_ulong),
        ('error_code', ctypes.c_ubyte),
        ('request_code', ctypes.c_ubyte),
        ('minor_code', ctypes.c_ubyte),
    ]


#: ``XErrorHandler``, which is ``int (*)(Display *, XErrorEvent *)``. Declared as
#: a real callback type rather than left to ctypes to guess: libX11 calls it on
#: the thread that made the failing request, with the two pointers it documents,
#: and a guessed signature is how a handler ends up reading the wrong argument.
#: Returning 0 from it is the documented way to say the error was handled.
X_ERROR_HANDLER = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_XErrorEvent))


# Module-level error count and handler trampoline. libX11 installs a *process-wide*
# handler pointer; if the trampoline is a bound method of an instance, the instance
# and the trampoline form a reference cycle (instance -> handler -> __self__ ->
# instance). Cyclic GC can then collect the trampoline while libX11 still holds the
# global pointer, and the next X error segfaults. A module-level function and counter
# have no cycle, no instance lifetime coupling, and survive ``del x; gc.collect()``.
_X_ERROR_COUNT = 0


def _x_error_handler(display: Any, event: Any) -> int:
    """
    Module-level X11 error handler: count one error and tell libX11 to carry on.

    Called by libX11 on the thread that made the failing request (here, the timer
    callback). It does the least work possible and cannot raise: an exception inside
    a ctypes callback is printed and turned into a zero return by ctypes, which
    happens to be the right answer, but would print on every tick. The arguments
    are the documented ``Display *`` and ``XErrorEvent *``; neither is read.
    """
    global _X_ERROR_COUNT
    _X_ERROR_COUNT += 1
    return 0


# The trampoline is created once at import time and never dies. It has no
# reference to any instance, so there is no cycle and no lifetime coupling.
_X_ERROR_HANDLER_TRAMPOLINE = X_ERROR_HANDLER(_x_error_handler)


def _install_x_error_handler() -> None:
    """
    Install the module-level error handler once.

    libX11's XSetErrorHandler is process-wide. We install our counting handler
    before the first XOpenDisplay so that errors during display opening are also
    caught. The handler is never uninstalled; close() leaves it in place because
    restoring the default would re-arm the exit(1) behaviour.
    """
    global _X_ERROR_HANDLER_INSTALLED
    if not _X_ERROR_HANDLER_INSTALLED:
        _lib = ctypes.CDLL(LIB_X11)
        _lib.XSetErrorHandler.argtypes = [X_ERROR_HANDLER]
        _lib.XSetErrorHandler.restype = ctypes.c_void_p
        _lib.XSetErrorHandler(_X_ERROR_HANDLER_TRAMPOLINE)
        _X_ERROR_HANDLER_INSTALLED = True


_X_ERROR_HANDLER_INSTALLED = False


@dataclass(frozen=True)
class WindowRect:
    """A window's client rectangle, in root-relative screen pixels."""

    x: int
    y: int
    width: int
    height: int


class _Xlib:
    """
    The handful of libX11 entry points the window lookup calls.

    Bound through ctypes rather than python-xlib, which is not installed here,
    and rather than xdotool or wmctrl, which would mean a subprocess per lookup
    and two more packages to install. The signatures are declared once, on the
    library this instance owns, so the defaults ctypes guesses at are never used.

    A module-level X11 error handler is installed at import time (before any
    X11 call can happen). libX11's default handler prints to stderr and calls
    ``exit(1)``, which for a walk that asks about windows other processes are
    free to destroy would make the node die on a race with no log line and no
    shutdown. The module-level handler counts and returns 0, so a window that
    went away is simply not found this tick, and :attr:`error_count` is what
    makes that visible rather than silent. The handler is process-wide and stays
    installed for the life of the process; closing a display does not uninstall it.
    """

    def __init__(self) -> None:
        """Load the library, declare the signatures, and open the display."""
        self._lib = ctypes.CDLL(LIB_X11)
        self._declare_signatures()
        # Install the error handler before any X11 call, including XOpenDisplay.
        _install_x_error_handler()
        # Any, because the handle is a pointer that also has to be settable to
        # None by close(): ctypes returns it as a plain int.
        self._display: Any = self._lib.XOpenDisplay(None)
        self._root = 0
        self._name_atom = 0
        if self.is_open():
            self._root = self._lib.XDefaultRootWindow(self._display)
            self._name_atom = self._lib.XInternAtom(
                self._display, b'_NET_WM_NAME', True)

    @property
    def error_count(self) -> int:
        """Return how many X11 errors the installed handler has swallowed."""
        return _X_ERROR_COUNT

    def _declare_signatures(self) -> None:
        """
        Declare the argument and return types of every call used here.

        The return conventions are not uniform and are the trap in this file:
        ``XQueryTree``, ``XGetWindowAttributes``, ``XGetClassHint`` and
        ``XTranslateCoordinates`` all return non-zero on success, while
        ``XGetWindowProperty`` returns ``Success``, which is zero. Getting one of
        them the wrong way round does not raise, it silently finds nothing.
        """
        library = self._lib
        display = ctypes.c_void_p
        window = ctypes.c_ulong
        integer = ctypes.c_int
        cardinal = ctypes.c_ulong
        library.XOpenDisplay.argtypes = [ctypes.c_char_p]
        library.XOpenDisplay.restype = display
        library.XDefaultRootWindow.argtypes = [display]
        library.XDefaultRootWindow.restype = window
        library.XInternAtom.argtypes = [display, ctypes.c_char_p, integer]
        library.XInternAtom.restype = cardinal
        library.XQueryTree.argtypes = [
            display, window,
            ctypes.POINTER(window), ctypes.POINTER(window),
            ctypes.POINTER(ctypes.POINTER(window)), ctypes.POINTER(ctypes.c_uint),
        ]
        library.XQueryTree.restype = integer
        library.XGetWindowProperty.argtypes = [
            display, window, cardinal,
            ctypes.c_long, ctypes.c_long, integer, cardinal,
            ctypes.POINTER(cardinal), ctypes.POINTER(integer),
            ctypes.POINTER(cardinal), ctypes.POINTER(cardinal),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        library.XGetWindowProperty.restype = integer
        library.XGetClassHint.argtypes = [display, window, ctypes.POINTER(_XClassHint)]
        library.XGetClassHint.restype = integer
        library.XGetWindowAttributes.argtypes = [
            display, window, ctypes.POINTER(_XWindowAttributes)]
        library.XGetWindowAttributes.restype = integer
        library.XTranslateCoordinates.argtypes = [
            display, window, window, integer, integer,
            ctypes.POINTER(integer), ctypes.POINTER(integer), ctypes.POINTER(window),
        ]
        library.XTranslateCoordinates.restype = integer
        library.XFree.argtypes = [ctypes.c_void_p]
        library.XFree.restype = integer
        library.XSetErrorHandler.argtypes = [X_ERROR_HANDLER]
        # The previous handler comes back as a bare function pointer and is
        # deliberately not wrapped in a callable: libX11's default handler calls
        # exit(1), and making a Python callable of it would keep that around.
        library.XSetErrorHandler.restype = ctypes.c_void_p
        library.XCloseDisplay.argtypes = [display]
        library.XCloseDisplay.restype = integer

    def is_open(self) -> bool:
        """Return whether a display is open at all, X11 or not."""
        return bool(self._display)

    def close(self) -> None:
        """
        Close the display, if one was opened.

        The error handler stays installed: see :meth:`__init__`. Counting errors
        on a display nobody asks about any more costs nothing.
        """
        if self._display:
            self._lib.XCloseDisplay(self._display)
            self._display = None

    def attributes(self, window: int) -> _XWindowAttributes | None:
        """
        Return a window's attributes, or ``None`` when X11 refuses them.

        ``XGetWindowAttributes`` returns 1 on success, like ``XQueryTree``,
        ``XGetClassHint`` and ``XTranslateCoordinates``, and unlike
        ``XGetWindowProperty``, which returns ``Success`` and is therefore 0.
        A window destroyed between the walk reaching it and this call lands here
        as ``None`` rather than as an X11 error, and the installed handler is
        what keeps that from being fatal.
        """
        result = _XWindowAttributes()
        if not self._lib.XGetWindowAttributes(self._display, window, ctypes.byref(result)):
            return None
        return result

    def window_name(self, window: int) -> str | None:
        """
        Return a window's ``_NET_WM_NAME``, or ``None`` when it has none.

        Read through the property rather than through ``XFetchName``, because
        ``_NET_WM_NAME`` is what a Qt client sets and ``XFetchName`` returns the
        legacy ``WM_NAME``, which is usually empty.
        """
        atom_type = ctypes.c_ulong()
        atom_format = ctypes.c_int()
        item_count = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        status = self._lib.XGetWindowProperty(
            self._display, window, self._name_atom, 0, MAX_NAME_LENGTH, False,
            X_ANY_PROPERTY_TYPE, ctypes.byref(atom_type), ctypes.byref(atom_format),
            ctypes.byref(item_count), ctypes.byref(bytes_after), ctypes.byref(data))
        if status != X_SUCCESS:
            return None
        try:
            if not item_count.value or not data:
                return None
            return ctypes.string_at(data, item_count.value).decode('utf-8', 'replace')
        finally:
            # Only allocated when the property exists, and ours either way: the
            # lookup runs ten times a second and leaking a name every tick would
            # be a slow leak that nobody notices until the machine is busy.
            self._lib.XFree(data)

    def window_class(self, window: int) -> str | None:
        """
        Return a window's ``WM_CLASS`` res_class, or ``None`` when it has none.

        The hint is zeroed first and the res_class pointer is what decides, so a
        window that never set ``WM_CLASS`` reads as ``None`` rather than as
        whatever was in the struct.
        """
        hint = _XClassHint(res_name=None, res_class=None)
        if not self._lib.XGetClassHint(self._display, window, ctypes.byref(hint)):
            return None
        try:
            return _as_text(hint.res_class)
        finally:
            self._lib.XFree(hint.res_name)
            self._lib.XFree(hint.res_class)

    def children(self, window: int) -> list[int]:
        """
        Return the direct children of a window.

        ``XQueryTree`` hands them back in stacking order, bottom first, which is
        also the order :meth:`find_window` walks them in, so the first match is
        the one nearest the bottom of the stack.
        """
        root = ctypes.c_ulong()
        parent = ctypes.c_ulong()
        child_list = ctypes.POINTER(ctypes.c_ulong)()
        child_count = ctypes.c_uint()
        if not self._lib.XQueryTree(
                self._display, window, ctypes.byref(root), ctypes.byref(parent),
                ctypes.byref(child_list), ctypes.byref(child_count)):
            return []
        try:
            return [int(child_list[index]) for index in range(child_count.value)]
        finally:
            self._lib.XFree(child_list)

    def translate(self, window: int, x: int, y: int) -> tuple[int, int] | None:
        """
        Return a point inside a window in root coordinates.

        Needed because the turtlesim window is a child of a reparenting window
        manager's frame, so the ``x`` and ``y`` its own attributes report are
        relative to that frame and not to the screen.
        """
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        child = ctypes.c_ulong()
        if not self._lib.XTranslateCoordinates(
                self._display, window, self._root, x, y,
                ctypes.byref(root_x), ctypes.byref(root_y), ctypes.byref(child)):
            return None
        return root_x.value, root_y.value

    def find_window(
        self, title: str, window_class: str
    ) -> tuple[int, WindowRect] | None:
        """
        Return the first viewable window with that title and class, and its rect.

        Both the title and the class have to match. The title alone would also
        match this node's own overlay if the two were ever confused, and the
        class alone would match every turtlesim node on the display. What the
        pair does *not* do is make the result unique: two turtlesim windows
        share both, so two overlay instances would each get the same first match
        and cover one canvas twice. One overlay per canvas is a property of the
        launch file starting one, not of this search.

        The walk is breadth first over the whole tree and returns the first match
        in that order. It descends only into windows that are viewable,
        InputOutput and not override-redirect, which is what bounds it: a
        window manager full of unmapped or override-redirect clients costs one
        round trip each rather than a subtree each. That pruning is also the
        limitation worth stating, because a viewable client reparented under an
        override-redirect window, or under a parent that is momentarily unmapped
        while the manager restyles it, is invisible to the walk and comes back as
        no match. It does not bite turtlesim on this session's manager, where
        the client sits under a plain frame, and a miss is a warning plus a
        marker that is absent rather than a wrong marker, so the pruning stays
        for this version.
        """
        if not self.is_open():
            return None
        pending: list[tuple[int, int]] = [(self._root, 0)]
        while pending:
            window, depth = pending.pop(0)
            if depth >= MAX_TREE_DEPTH:
                continue
            attributes = self.attributes(window)
            if attributes is None:
                continue
            if attributes.map_state != IS_VIEWABLE or attributes.class_ != INPUT_OUTPUT:
                continue
            if attributes.override_redirect:
                # An override-redirect window is always on top and unmanaged, so
                # it cannot be the managed application window being looked for.
                continue
            if self.window_name(window) != title:
                pending.extend((child, depth + 1) for child in self.children(window))
                continue
            if self.window_class(window) != window_class:
                pending.extend((child, depth + 1) for child in self.children(window))
                continue
            origin = self.translate(window, 0, 0)
            if origin is None:
                continue
            return window, WindowRect(
                origin[0], origin[1], attributes.width, attributes.height)
        return None


def _as_text(pointer: int | None) -> str | None:
    """Return a ``char *`` libX11 handed us as a string, or ``None`` for NULL."""
    if not pointer:
        return None
    text = ctypes.cast(pointer, ctypes.c_char_p).value
    if text is None:
        return None
    return text.decode('utf-8', 'replace')


def _overlay_widget_class() -> type:
    """
    Return the overlay widget class, importing PySide6 to build it.

    A ``QWidget`` subclass has to exist before the widget can be made, and the
    subclass statement needs the real base class, so the class is built here
    rather than at module scope. That is the same reason the PySide6 import is
    inside this function: importing :mod:`rescue_turtle.safe_zone` must not need
    Qt to be installed, let alone a display.
    """
    from PySide6.QtCore import QPointF
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPaintEvent
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QWidget

    class SafeZoneOverlay(QWidget):
        """
        The frameless window the marker is painted into.

        The window covers the whole canvas and the marker is painted at the
        rectangle the start zone occupies inside it, so following the window is
        a matter of moving the window, and resizing turtlesim needs nothing more
        than a new geometry for it.
        """

        def __init__(self) -> None:
            """Start with nothing painted: no source image and no rectangle."""
            super().__init__()
            self._marker: Any = None
            self._zone: PixelRect = (0.0, 0.0, 0.0, 0.0)

        def place(self, marker: Any, zone: PixelRect) -> None:
            """
            Paint ``marker`` at ``zone`` from now on, and repaint immediately.

            Scaling happens here, once per placement rather than once per paint
            event. The zone is 54 px across and the art is 256, so the smooth
            downscale is worth doing once and the paint is then a blit.
            """
            _, _, width, height = zone
            self._marker = marker.scaled(
                max(1, round(width)), max(1, round(height)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self._zone = zone
            self.update()

        def paintEvent(self, event: QPaintEvent) -> None:
            """Draw the marker at the zone rectangle, and nothing anywhere else."""
            if self._marker is None:
                return
            painter = QPainter(self)
            painter.drawPixmap(QPointF(self._zone[0], self._zone[1]), self._marker)
            painter.end()

    return SafeZoneOverlay


def resolve_image_path(image_path: str) -> str:
    """
    Return the marker file to load, resolving an empty path to the installed one.

    The installed copy is found through the ament index rather than a path built
    out of the source tree, so it is the file that was actually installed and the
    lookup still works from a different prefix.
    """
    if image_path:
        return image_path
    from ament_index_python.packages import get_package_share_directory
    return os.path.join(
        get_package_share_directory(PACKAGE_NAME), MEDIA_SUBDIRECTORY, DEFAULT_IMAGE_FILE)


class SafeZoneNode(Node):
    """Draws the safe zone marker over one turtlesim canvas, and owns nothing else."""

    def __init__(self, node_name: str) -> None:
        """Read every knob from parameters, then start the tracking timer."""
        super().__init__(node_name)

        self._image_path = self._declare_str('image_path', '')
        self._window_title = self._declare_str(
            'turtlesim_window_title', DEFAULT_WINDOW_TITLE)
        self._window_class = self._declare_str(
            'turtlesim_window_class', DEFAULT_WINDOW_CLASS)
        self._overlay_title = self._declare_str(
            'overlay_window_title', DEFAULT_OVERLAY_WINDOW_TITLE)
        self._gui = self._declare_bool('turtlesim_gui', True)
        self._check_node_name(self._declare_str('node_name', ''))

        self._zone_x_min = self._declare_float('start_zone_x_min', DEFAULT_ZONE_MIN)
        self._zone_x_max = self._declare_float('start_zone_x_max', DEFAULT_ZONE_MAX)
        self._zone_y_min = self._declare_float('start_zone_y_min', DEFAULT_ZONE_MIN)
        self._zone_y_max = self._declare_float('start_zone_y_max', DEFAULT_ZONE_MAX)
        self._world_width_m = self._declare_float(
            'world_width_m', DEFAULT_WORLD_WIDTH_M)
        self._world_height_m = self._declare_float(
            'world_height_m', DEFAULT_WORLD_HEIGHT_M)
        self._canvas_width_px = self._declare_float(
            'canvas_width_px', DEFAULT_CANVAS_WIDTH_PX)
        self._canvas_height_px = self._declare_float(
            'canvas_height_px', DEFAULT_CANVAS_HEIGHT_PX)
        self._canvas_margin_px = self._declare_float(
            'canvas_margin_px', DEFAULT_CANVAS_MARGIN_PX)
        self._track_period_s = self._declare_float(
            'track_period_s', DEFAULT_TRACK_PERIOD_S)
        self._validate()

        # Instance state only, like the other two nodes: two overlays in one
        # process, or two processes on the machine, cannot see each other.
        self._xlib: _Xlib | None = None
        self._app: Any = None
        self._marker_path = ''
        self._marker: Any = None
        self._overlay: Any = None
        self._last_zone: PixelRect | None = None
        self._announced_missing_window = False
        self._reported_canvas_size: tuple[int, int] | None = None
        self._requested_rect: WindowRect | None = None
        self._reported_rect: WindowRect | None = None
        self._placement_ticks = 0
        self._error_ticks = 0
        self._reported_error_count = 0
        self._timer: Timer | None = None

        if not self._gui:
            self.get_logger().info(
                'turtlesim_gui is False, so no window is created and the turtlesim '
                'window is not looked for: the node stays idle unless an external '
                'turtlesim on X11 is provided and turtlesim_gui is True'
            )
            return

        self._open_marker()
        self._open_overlay()
        # Once at startup, so the marker is up and the numbers are in the log
        # within a moment of the node starting, and then on the timer, which is
        # what keeps it there.
        self._track_window()
        self._timer = self.create_timer(self._track_period_s, self._track_window)

    # ------------------------------------------------------------------ setup

    def _declare_str(self, name: str, default: str) -> str:
        """Declare a string parameter and return its value."""
        self.declare_parameter(name, default)
        return str(self.get_parameter(name).value)

    def _declare_float(self, name: str, default: float) -> float:
        """Declare a float parameter and return its value."""
        self.declare_parameter(name, default)
        return float(self.get_parameter(name).value)

    def _declare_bool(self, name: str, default: bool) -> bool:
        """Declare a boolean parameter and return its value."""
        self.declare_parameter(name, default)
        return bool(self.get_parameter(name).value)

    def _check_node_name(self, requested: str) -> None:
        """Warn when the node name parameter disagrees with the live name."""
        if requested and requested != self.get_name():
            self.get_logger().warning(
                f'node_name is {requested!r} but this node is called '
                f'{self.get_name()!r}: a name supplied through --params-file '
                'cannot be read before the node exists'
            )

    def _validate(self) -> None:
        """
        Reject parameter values the overlay cannot be drawn from.

        :raises ValueError: on a bad zone, world, canvas, margin, period, title
            or class, so that :func:`main` can log it and exit instead of an
            overlay that cannot find its window or that lands off the canvas. The
            rules themselves are pure functions in
            :mod:`rescue_turtle.validation`, so they are unit tested.
        """
        errors = safe_zone_configuration_errors(
            zone=self._zone(),
            world_size=(self._world_width_m, self._world_height_m),
            canvas_size_px=(self._canvas_width_px, self._canvas_height_px),
            canvas_margin_px=self._canvas_margin_px,
            track_period_s=self._track_period_s,
            window_title=self._window_title,
            window_class=self._window_class,
        )
        if errors:
            raise ValueError(errors[0])

    def _zone(self) -> Box:
        """Return the start zone this overlay draws."""
        return (self._zone_x_min, self._zone_x_max, self._zone_y_min, self._zone_y_max)

    def _open_marker(self) -> None:
        """
        Load the marker image, refusing to run without it.

        :raises ValueError: when the file is missing or unreadable, because a
            node that cannot draw anything would sit there silently looking for
            a window it could never fill.
        :raises ModuleNotFoundError: when PySide6 is not installed, which
            :func:`main` turns into one line and exit 2 rather than a traceback.

        The path is checked before Qt is imported, so a mistyped ``image_path``
        on a machine without PySide6 is reported as the mistyped path it is,
        rather than as the missing module that is also true.
        """
        self._marker_path = resolve_image_path(self._image_path)
        if not os.path.isfile(self._marker_path):
            raise ValueError(
                f'the safe zone marker {self._marker_path!r} is not a file: pass '
                'image_path, or install this package so the marker is in its '
                'share directory'
            )

        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QApplication

        # sys.argv is truncated to the program name: these are ROS arguments,
        # not Qt's, and there is nothing here that Qt should be parsing.
        self._app = QApplication.instance() or QApplication(sys.argv[:1])
        self._marker = QPixmap(self._marker_path)
        if self._marker.isNull():
            raise ValueError(
                f'the safe zone marker {self._marker_path!r} could not be loaded')

    def _open_overlay(self) -> None:
        """
        Create the overlay window, invisible and click-through for now.

        Created here but not shown: its geometry is not known until a turtlesim
        window has been found, and a window flashed up in the wrong place is more
        confusing than one that appears with it. :meth:`_track_window` runs
        immediately afterwards and is what shows it, on the first tick rather
        than a moment later.
        """
        from PySide6.QtCore import Qt

        self._overlay = _overlay_widget_class()()
        self._overlay.setWindowTitle(self._overlay_title)
        # Frameless so it adds nothing to the window it annotates, always on top
        # so it is not behind the canvas, transparent for input so clicks reach
        # the turtlesim window underneath, and no focus so it never steals the
        # keyboard from teleop. Qt.Tool is deliberately not among them: it makes
        # the window transient for a Qt group leader that is never mapped, and
        # the window manager then places it at -32768, -32768 instead of over
        # the canvas. Verified on this session's Weston: without it the window
        # lands exactly where it was asked to.
        self._overlay.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        # Translucent, so only the marker itself is drawn and the canvas shows
        # through everywhere else, and transparent for the mouse, so the two
        # settings agree about clicks. Without activating is what keeps a redraw
        # from pulling focus away from whatever the human is typing into.
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.get_logger().info(
            f'drawing {self._marker_path!r} over the turtlesim window titled '
            f'{self._window_title!r} of class {self._window_class!r}, every '
            f'{self._track_period_s} s'
        )

    # --------------------------------------------------------------- tracking

    def _track_window(self) -> None:
        """
        Re-find the window, put the overlay back over it, then show Qt.

        The display is opened once, on the first tick, and never retried. A
        ``DISPLAY`` that appears after startup is therefore not picked up: retrying
        would mean an ``XOpenDisplay`` per tick forever, and while a bad
        ``DISPLAY`` fails cheaply, a display that answers slowly enough to hang
        would hang the timer callback, which owns the only event loop in this
        process. The launch file sets the environment anyway, and the recovery
        from a display that was not there at startup is to start the node again.
        """
        if self._xlib is None:
            self._xlib = _Xlib()
        found = self._xlib.find_window(self._window_title, self._window_class)
        self._report_xlib_errors()
        if found is None:
            self._report_missing_window()
            self._app.processEvents()
            return
        window, client = found
        if self._announced_missing_window:
            self.get_logger().info('the turtlesim window is there')
        self._announced_missing_window = False
        self._place_overlay(window, client)
        # rclpy's loop is the only event loop in this process, so Qt's queued
        # show, move and paint requests are served from here. Calling
        # processEvents every tick is what makes the window appear at all
        # without a second thread owning Qt.
        self._app.processEvents()
        # Read back after processEvents, because that is when Qt has actually sent
        # the geometry and the window manager has had a chance to answer it.
        self._report_placement()

    def _place_overlay(self, window: int, client: WindowRect) -> None:
        """Put the overlay over the canvas of the window just found."""
        self._check_canvas_size(client)
        canvas_x = client.x + self._canvas_margin_px
        canvas_y = client.y + self._canvas_margin_px
        zone = zone_to_pixel_rect(
            self._zone(),
            world_width_m=self._world_width_m,
            world_height_m=self._world_height_m,
            canvas_width_px=self._canvas_width_px,
            canvas_height_px=self._canvas_height_px,
        )
        overlay = self._overlay
        # The whole canvas, not just the zone, so that the marker keeps its
        # place inside the canvas when the window moves or grows.
        self._requested_rect = WindowRect(
            round(canvas_x), round(canvas_y),
            round(self._canvas_width_px), round(self._canvas_height_px))
        overlay.setGeometry(
            self._requested_rect.x, self._requested_rect.y,
            self._requested_rect.width, self._requested_rect.height)
        if zone != self._last_zone:
            # Only when the rectangle actually changes, which on a still
            # turtlesim is once: the placement is arithmetic, not a measurement,
            # so it cannot drift while the window stays still.
            self._last_zone = zone
            overlay.place(self._marker, zone)
            self._log_zone(window, client, zone)
        if not overlay.isVisible():
            overlay.show()
        # Re-raised every tick, which is the point of the tick: on X11 clicking
        # the turtlesim window raises it, and a raise beats an ordinary
        # always-on-top window, so without this the marker ends up behind the
        # canvas it is annotating.
        overlay.raise_()

    def _check_canvas_size(self, client: WindowRect) -> None:
        """
        Say once per measured size that the window is not the size assumed.

        A warning rather than a refusal, and only once per distinct size: the
        marker is still worth showing if it is a little out, a human can see
        that it is out, and refusing to run would leave a request for the overlay
        with no marker on the screen at all and nothing explaining why.
        """
        measured = (client.width, client.height)
        if measured == self._reported_canvas_size:
            return
        self._reported_canvas_size = measured
        assumed = (round(self._canvas_width_px), round(self._canvas_height_px))
        if measured != assumed:
            self.get_logger().warning(
                f'the turtlesim client area measures {measured[0]} x {measured[1]} px '
                f'but canvas_width_px/canvas_height_px say {assumed[0]} x '
                f'{assumed[1]} px: the marker is placed as though the canvas were '
                f'{assumed[0]} x {assumed[1]} px, so change those two parameters for '
                'this build'
            )

    def _log_zone(self, window: int, client: WindowRect, zone: PixelRect) -> None:
        """
        Log what was found and the rectangle it puts the marker in.

        The canvas origin here is what the overlay is *asked* to cover;
        :meth:`_report_placement` says where the window ended up.
        """
        x_min, x_max, y_min, y_max = self._zone()
        left, top, width, height = zone
        self.get_logger().info(
            f'found the turtlesim window 0x{window:x} at ({client.x}, {client.y}) '
            f'{client.width} x {client.height} px'
        )
        self.get_logger().info(
            f'safe zone x [{x_min}, {x_max}] m, y [{y_min}, {y_max}] m on a '
            f'{self._world_width_m} x {self._world_height_m} m world at '
            f'{self._canvas_width_px / self._world_width_m:.4f} px/m is '
            f'{width:.2f} x {height:.2f} px, drawn at ({left:.2f}, {top:.2f}) on '
            f'the {self._canvas_width_px:.0f} x {self._canvas_height_px:.0f} px '
            f'canvas, over a canvas whose top left the overlay is asked to sit at '
            f'({client.x + self._canvas_margin_px:.0f}, '
            f'{client.y + self._canvas_margin_px:.0f}) on screen'
        )

    def _report_placement(self) -> None:
        """
        Say where the overlay window actually is, not just where it was asked to go.

        ``setGeometry`` is a request, and the window manager may place the window
        somewhere else entirely: measured on this session, a request for
        ``(-32730, -32709)`` was realised as ``(-32736, -32736)``, 6 px and 27 px
        out, which is enough to put the marker off the canvas it annotates. So
        the geometry is read back out of X11 and logged whenever it moves, and
        every :data:`PLACEMENT_REPORT_EVERY_TICKS` ticks even when it does not,
        because the first tick can run before the manager has answered the first
        request and a placement that is wrong once can be right later.

        A disagreement is a warning, because that is the case where the marker
        may not be over the canvas at all. Agreement is the expected case, so it
        is only worth saying at debug.
        """
        xlib = self._xlib
        requested = self._requested_rect
        if xlib is None or requested is None:
            return
        overlay_window = int(self._overlay.winId())
        attributes = xlib.attributes(overlay_window)
        origin = xlib.translate(overlay_window, 0, 0)
        if attributes is None or origin is None:
            return
        realised = WindowRect(
            origin[0], origin[1], attributes.width, attributes.height)
        self._placement_ticks += 1
        settled = realised == self._reported_rect
        if settled and self._placement_ticks < PLACEMENT_REPORT_EVERY_TICKS:
            return
        self._placement_ticks = 0
        self._reported_rect = realised
        message = (
            f'the overlay window is at ({realised.x}, {realised.y}) '
            f'{realised.width} x {realised.height} px'
        )
        if realised == requested:
            self.get_logger().debug(f'{message}, which is where it was asked to be')
        else:
            self.get_logger().warning(
                f'{message}, not the ({requested.x}, {requested.y}) '
                f'{requested.width} x {requested.height} px it was asked for: the '
                'window manager placed it, so the marker may not be over the canvas'
            )

    def _report_xlib_errors(self) -> None:
        """
        Say how many X11 errors the installed handler has swallowed.

        Swallowing them is right for a window that went away between two of the
        walk's calls, and wrong for a display that is permanently in error, where
        the node would otherwise look healthy while finding nothing. So the count
        is reported every :data:`ERROR_REPORT_EVERY_TICKS` ticks, but only when
        it has actually moved.

        The level depends on whether the overlay is up. Errors while the overlay
        is placed are the ones that can mean the placement is wrong, so those are
        warnings; errors on a display where no turtlesim window has been found are
        debug, because the warning about the missing window has already said
        that.
        """
        xlib = self._xlib
        if xlib is None:
            return
        self._error_ticks += 1
        if self._error_ticks < ERROR_REPORT_EVERY_TICKS:
            return
        self._error_ticks = 0
        total = xlib.error_count
        if total == self._reported_error_count:
            return
        swallowed = total - self._reported_error_count
        self._reported_error_count = total
        message = (
            f'{swallowed} X11 error(s) swallowed since the last report, {total} in '
            'total; a window destroyed mid-lookup is the usual cause'
        )
        if self._reported_rect is None:
            self.get_logger().debug(message)
        else:
            self.get_logger().warning(message)

    def _report_missing_window(self) -> None:
        """
        Say the window was not found, once at warning level and then quietly.

        Missing for ten ticks is one problem, not ten, and the usual cause is
        turtlesim running on the native Wayland session where there is no window
        to find. Repeating it at that rate would bury the rest of the log.
        """
        if self._xlib is None or not self._xlib.is_open():
            message = (
                f'there is no X display to search (DISPLAY='
                f'{os.environ.get("DISPLAY", "")!r}), so the overlay cannot look for '
                'a window: it needs X11, so run turtlesim with QT_QPA_PLATFORM=xcb'
            )
        else:
            message = (
                f'no window titled {self._window_title!r} of class '
                f'{self._window_class!r} on that display; the marker cannot be '
                f'placed until turtlesim is there, retrying every '
                f'{self._track_period_s} s'
            )
        if self._announced_missing_window:
            self.get_logger().debug(message)
        else:
            self.get_logger().warning(message)
        self._announced_missing_window = True

    # --------------------------------------------------------------- lifecycle

    def destroy_node(self) -> None:
        """
        Cancel the timer, drop the window, then destroy the node.

        The timer runs for the life of the process and owns a native window, so
        both are released explicitly rather than left to the garbage collector.
        Both are read defensively, for the reason the spawner documents: a
        startup failure part way through ``__init__`` must exit on the error that
        caused it, not on an ``AttributeError`` from here.
        """
        timer = getattr(self, '_timer', None)
        if timer is not None:
            timer.cancel()
        overlay = getattr(self, '_overlay', None)
        if overlay is not None:
            overlay.close()
        xlib = getattr(self, '_xlib', None)
        if xlib is not None:
            xlib.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    """Run the safe zone overlay node until interrupted."""
    overrides = parameter_overrides(sys.argv[1:] if args is None else args)
    node_name = overrides.get('node_name') or DEFAULT_NODE_NAME

    rclpy.init(args=args)
    node: SafeZoneNode | None = None
    try:
        node = SafeZoneNode(node_name)
        while rclpy.ok():
            rclpy.spin_once(node)
    except (ValueError, ParameterException, InvalidNodeNameException) as exc:
        # A mistyped parameter value, a marker that is not there or an unusable
        # node_name is a startup mistake, not a crash: the rclpy exceptions are
        # not ValueErrors, so they are named here rather than left to become a
        # traceback.
        get_logger(STARTUP_LOG_NAME).error(f'cannot start: {exc}')
        raise SystemExit(2) from exc
    except (OSError, ModuleNotFoundError) as exc:
        # libX11 missing, no display to open, or PySide6 not installed. PySide6
        # is an undeclared runtime dependency of the overlay and the node
        # imports it lazily, so this is the likeliest way to fail on a machine
        # where the rest of the package works, and it is the same shape of
        # problem as a bad parameter: a startup mistake, one line, exit 2.
        get_logger(STARTUP_LOG_NAME).error(f'cannot start: {exc}')
        raise SystemExit(2) from exc
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        # A signal can arrive while a timer callback is running, invalidating the
        # context after the rclpy.ok() check above. Treat it as shutdown.
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
