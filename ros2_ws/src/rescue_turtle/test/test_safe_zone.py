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
Tests for the safe zone overlay node.

Hand-written FFI is where a test earns its keep, because every failure mode is
silent: a wrong return convention finds no window, a wrong struct offset reads a
plausible wrong number, and an X11 error left to libX11's default handler ends
the process. So the libX11 binding, the struct offsets, the error handler, the
headless path and the startup failures are all checked here rather than left to
a run against a live turtlesim.

Most of these need neither a display nor Qt: the display cases skip themselves,
and the headless node is the one that has to keep PySide6 out of the process.
"""

import builtins
from collections.abc import Iterator
from contextlib import contextmanager
import ctypes
import os
import sys
from typing import Any

import pytest
import rclpy

import rescue_turtle.safe_zone as safe_zone
from rescue_turtle.safe_zone import _Xlib
from rescue_turtle.safe_zone import _XWindowAttributes
from rescue_turtle.safe_zone import DEFAULT_CANVAS_WIDTH_PX
from rescue_turtle.safe_zone import DEFAULT_OVERLAY_WINDOW_TITLE
from rescue_turtle.safe_zone import DEFAULT_TRACK_PERIOD_S
from rescue_turtle.safe_zone import DEFAULT_WINDOW_CLASS
from rescue_turtle.safe_zone import DEFAULT_WINDOW_TITLE
from rescue_turtle.safe_zone import DEFAULT_WORLD_HEIGHT_M
from rescue_turtle.safe_zone import DEFAULT_WORLD_WIDTH_M
from rescue_turtle.safe_zone import main
from rescue_turtle.safe_zone import resolve_image_path
from rescue_turtle.safe_zone import SafeZoneNode

#: Every parameter the design's table says the node has to declare. rclpy adds
#: its own (``use_sim_time``, the node description service), so this is checked as
#: a subset rather than as the whole set.
DECLARED_PARAMETERS = (
    'canvas_height_px',
    'canvas_margin_px',
    'canvas_width_px',
    'image_path',
    'node_name',
    'overlay_window_title',
    'start_zone_x_max',
    'start_zone_x_min',
    'start_zone_y_max',
    'start_zone_y_min',
    'track_period_s',
    'turtlesim_gui',
    'turtlesim_window_class',
    'turtlesim_window_title',
    'world_height_m',
    'world_width_m',
)

#: The bindings that must not be in the process unless the overlay is actually
#: drawing: PySide6 is an undeclared runtime dependency, so the headless path has
#: to work without it and the lazy import is what makes that true.
QT_BINDINGS = ('PySide6', 'shiboken', 'shiboken6', 'PyQt5', 'PyQt6')


@contextmanager
def rclpy_arguments(arguments: list[str]) -> Iterator[None]:
    """
    Give one test a live rclpy context with these global ROS arguments.

    A node reads its parameter overrides from the context it is created in, not
    from its constructor, so this is how a test starts the headless path:
    ``turtlesim_gui:=False`` has to arrive as a global argument rather than as a
    keyword.
    """
    rclpy.init(args=arguments)
    try:
        yield
    finally:
        if rclpy.ok():
            rclpy.shutdown()


@contextmanager
def no_qt_import(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Make every ``PySide6`` import raise, as it would on a machine without it.

    Patched at :func:`builtins.__import__` rather than by stubbing the method
    that imports, so the real code path runs and the order of its checks is what
    is under test.
    """
    real_import = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split('.')[0] == 'PySide6':
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    yield


@pytest.fixture
def open_display() -> Iterator[_Xlib]:
    """Yield an open X11 connection, or skip when this machine has no display."""
    safe_zone._X_ERROR_COUNT = 0
    connection = _Xlib()
    if not connection.is_open():
        connection.close()
        pytest.skip('no X display on this machine')
    try:
        yield connection
    finally:
        connection.close()


# --------------------------------------------------------------- marker file


def test_an_empty_image_path_resolves_to_the_installed_marker() -> None:
    """
    The default has to be the file that was installed, not one in the source tree.

    Found through the ament index, so it still resolves from another prefix.
    """
    resolved = resolve_image_path('')
    assert resolved.endswith(os.path.join('rescue_turtle', 'media', 'safe_zone.png'))
    assert os.path.isfile(resolved)


def test_an_explicit_image_path_is_used_exactly_as_given() -> None:
    """
    An operator's path is theirs: no resolution and no existence check here.

    Whether it is a file is the node's business, in its own error message.
    """
    assert resolve_image_path('/some/path/marker.png') == '/some/path/marker.png'


# -------------------------------------------------------------------- libX11


def test_no_display_means_no_window_and_no_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A display that cannot be opened is a condition, not a crash.

    This is the documented limit of the whole node: turtlesim has to be on X11,
    and the way that is meant to show up is a warning and an idle node.
    """
    monkeypatch.setenv('DISPLAY', '/no-such-display-for-this-test:99')
    connection = _Xlib()
    try:
        assert not connection.is_open()
        assert connection.find_window(DEFAULT_WINDOW_TITLE, DEFAULT_WINDOW_CLASS) is None
    finally:
        connection.close()


def test_the_window_attributes_struct_has_the_offsets_libx11_writes_to() -> None:
    """
    The struct is declared whole because every offset depends on the fields above it.

    136 bytes with ``class`` at 40 are the offsets the C compiler produces on this
    platform, checked against compiled C rather than against this file's own idea
    of the layout. Reading the wrong offset does not raise: it returns a
    plausible wrong number, which is the worst kind of FFI bug and the reason the
    numbers are pinned.
    """
    assert ctypes.sizeof(_XWindowAttributes) == 136
    assert _XWindowAttributes.class_.offset == 40


def test_the_error_handler_counts_and_never_raises() -> None:
    """
    The handler has to do the least there is and must not raise.

    libX11 calls it on the thread that made the failing request, which here is
    the timer callback, so anything it printed would be printed ten times a
    second. Returning 0 is how it tells libX11 the error was handled.

    Uses the module-level handler and counter directly, since the handler is
    no longer an instance method.
    """
    safe_zone._X_ERROR_COUNT = 0
    assert safe_zone._x_error_handler(None, None) == 0
    assert safe_zone._x_error_handler(None, None) == 0
    assert safe_zone._X_ERROR_COUNT == 2


def test_a_window_destroyed_mid_lookup_is_counted_and_the_process_survives(
    open_display: _Xlib,
) -> None:
    """
    Asking about a window that is not there must not take the process down.

    This is what the error handler is for. libX11's default handler prints to
    stderr and calls ``exit(1)``, and the lookup walks the whole window tree
    asking about windows other processes are free to destroy, so one of them
    vanishing between two calls would end the node with no ROS log, no
    ``destroy_node`` and exit code 1. Without the handler this test would not
    fail: the pytest process itself would be gone.
    """
    assert open_display.attributes(0xDEADBEEF) is None
    assert open_display.error_count == 1
    # Still usable afterwards, which is the point of counting rather than dying.
    open_display.find_window(DEFAULT_WINDOW_TITLE, DEFAULT_WINDOW_CLASS)


# --------------------------------------------------------------- headless node


def test_a_headless_node_declares_every_parameter_and_starts_no_timer() -> None:
    """
    ``turtlesim_gui:=False`` has to be a complete node, just an idle one.

    It exists so the package can run where there is no display at all, which is
    also why it must not reach for Qt: PySide6 is not a declared dependency, so a
    headless run has to work on a machine that has never installed it.
    """
    with rclpy_arguments(['--ros-args', '-p', 'turtlesim_gui:=False']):
        node = SafeZoneNode('test_safe_zone_headless')
        try:
            for name in DECLARED_PARAMETERS:
                assert node.has_parameter(name), f'{name} was not declared'
            assert list(node.timers) == []
            assert node.get_parameter('turtlesim_gui').value is False
            assert node.get_parameter('world_width_m').value == DEFAULT_WORLD_WIDTH_M
            assert node.get_parameter('world_height_m').value == DEFAULT_WORLD_HEIGHT_M
            assert node.get_parameter('canvas_width_px').value == DEFAULT_CANVAS_WIDTH_PX
            assert node.get_parameter('track_period_s').value == DEFAULT_TRACK_PERIOD_S
            assert node.get_parameter('turtlesim_window_title').value == DEFAULT_WINDOW_TITLE
            assert node.get_parameter('turtlesim_window_class').value == DEFAULT_WINDOW_CLASS
            assert node.get_parameter('overlay_window_title').value == DEFAULT_OVERLAY_WINDOW_TITLE
            assert node.get_parameter('image_path').value == ''
            for binding in QT_BINDINGS:
                assert binding not in sys.modules, f'{binding} was imported'
        finally:
            node.destroy_node()


def test_a_headless_node_destroys_without_owning_anything() -> None:
    """
    ``destroy_node`` has to survive a start that got no further than the parameters.

    The spawner documents the same hazard: a startup failure part way through
    construction must exit on the error that caused it, not on an
    ``AttributeError`` from the cleanup. Here nothing was ever opened, so every
    field the cleanup reads is ``None``.
    """
    with rclpy_arguments(['--ros-args', '-p', 'turtlesim_gui:=False']):
        node = SafeZoneNode('test_safe_zone_destroy')
        node.destroy_node()


def test_a_bad_image_path_is_reported_before_the_missing_qt_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    On a machine with no PySide6, a mistyped path is the mistake an operator can fix.

    Both are true at once there, so the order of the two checks decides which one
    gets said. This asserts the path wins, and asserts it by running the real
    method with the import blocked.
    """
    with no_qt_import(monkeypatch):
        with rclpy_arguments([
            '--ros-args', '-p', 'turtlesim_gui:=False',
            '-p', 'image_path:=/no/such/marker.png',
        ]):
            node = SafeZoneNode('test_safe_zone_bad_path')
            try:
                with pytest.raises(ValueError, match='is not a file'):
                    node._open_marker()
            finally:
                node.destroy_node()


# --------------------------------------------------------------------- main()


def _startup_output(capfd: pytest.CaptureFixture[str]) -> str:
    """Return what a failed startup wrote, so the test can insist it was one line."""
    return capfd.readouterr().err


def test_a_missing_pyside6_is_one_line_and_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """
    An undeclared runtime dependency must not arrive as a traceback.

    PySide6 is imported lazily and is not declared in ``package.xml``, so a
    machine without it is an expected machine rather than a broken one, and it is
    the same shape of problem as a bad parameter: one line, exit 2.
    """
    with no_qt_import(monkeypatch):
        with pytest.raises(SystemExit) as exit_info:
            main(args=[])
    assert exit_info.value.code == 2
    lines = [line for line in _startup_output(capfd).splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert 'cannot start' in lines[0]
    assert 'PySide6' in lines[0]


def test_a_missing_libx11_is_one_line_and_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """
    The same for the library the lookup binds to.

    Qt is stubbed out here so the failure under test is the one from opening the
    display, not the one from a machine that also has no Qt. ``ctypes.CDLL``
    raises ``OSError`` for a library that is not there, which used to reach the
    operator as a traceback.
    """
    def no_library(*_args: Any, **_kwargs: Any) -> None:
        raise OSError('libX11.so.6: cannot open shared object file: No such file')

    monkeypatch.setattr(SafeZoneNode, '_open_marker', lambda _self: None)
    monkeypatch.setattr(SafeZoneNode, '_open_overlay', lambda _self: None)
    monkeypatch.setattr(_Xlib, '__init__', no_library)
    with pytest.raises(SystemExit) as exit_info:
        main(args=[])
    assert exit_info.value.code == 2
    lines = [line for line in _startup_output(capfd).splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert 'cannot start' in lines[0]
    assert 'libX11' in lines[0]


def test_a_rejected_configuration_is_one_line_and_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """
    The node that only got as far as validating its parameters still exits cleanly.

    This is the other half of ``destroy_node``'s hazard: the constructor raised,
    so there is no node object to clean up, and ``main``'s ``finally`` must cope
    with that rather than tripping over it on the way out.
    """

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError('start_zone_x_min must be < start_zone_x_max, got 9.0')

    monkeypatch.setattr(SafeZoneNode, '_validate', refuse)
    with pytest.raises(SystemExit) as exit_info:
        main(args=[])
    assert exit_info.value.code == 2
    lines = [line for line in _startup_output(capfd).splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert 'cannot start' in lines[0]
