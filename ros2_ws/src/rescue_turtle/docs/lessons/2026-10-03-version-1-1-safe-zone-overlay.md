# Version 1.1: safe zone overlay

Date: 2026-10-03. Package `rescue_turtle`. Commit `d7f8e2a`.

## 1. Core concepts

1. **Overlay, not injection** - when a system you cannot change has no way to accept your image, draw it in a window of your own, exactly over the target.
2. **Timer re-assertion** - on X11, clicking a window raises it. A 10 Hz timer that re-finds the window and puts your overlay back on top is simpler and more robust than any event hook.
3. **X11 return conventions are a trap** - most calls return non-zero on success, but `XGetWindowProperty` returns zero. Getting one backwards does not raise; it silently finds nothing.
4. **libX11's default error handler calls `exit(1)`** - a window destroyed mid-walk kills the process. You must install your own handler before the first X call.
5. **Requested geometry is a wish, not a fact** - `setGeometry` asks the window manager; the window manager answers. Read back the realised position from X11 and log both.

## 2. What we built

A `safe_zone` node that draws `resource/safe_zone.png` over the turtlesim canvas, centred on the rescuer's spawn point (5.544444, 5.544444) and scaled to the 1.2 m start zone (4.944..6.144 m in both axes). The overlay is a separate frameless Qt window placed via X11 window discovery using `ctypes` against `libX11`. A 10 Hz timer re-finds the turtlesim window and re-asserts the overlay's geometry and stacking, so the marker survives `/clear`, window moves, resizes, and the turtlesim window being raised by a click.

The node is deliberately separate from `rescue_manager`: the manager owns one `(rescuer, victim)` pair; the overlay owns one *canvas*. Version 3 will have several pairs on one canvas, so keeping them apart means Version 1.1 does not have to be undone later.

## 3. The concepts explained

### Why turtlesim could not just be given the PNG

The request was "add the safe_zone.png to the same coordinates that the rescuer turtle spawns in at and stays there". The first thought might be: make turtlesim draw it. But turtlesim has no door for that:

- `/spawn` carries `x`, `y`, `theta`, `name`. No texture field.
- The only parameters on `/turtlesim` are `background_r/g/b` and `holonomic`. Nothing selects an image file.
- At startup turtlesim opens **all thirteen** sprites in `share/turtlesim/images` (one per ROS distro). On every `/spawn` it opens **nothing** — it indexes the set it already loaded. Verified with `inotify` on a live turtlesim.
- So `/spawn name:=safe_zone` does not draw `safe_zone.png`. It succeeds, returns `safe_zone`, and draws a stock turtle parked in the middle of the start zone.
- The sprite directory `/opt/ros/lyrical/share/turtlesim/images` is not writable, so the file cannot be placed beside the sprites either.
- `AGENTS.md` says never modify turtlesim.

An overlay is the only route.

### Why a separate Qt window was the right architecture

The marker is drawn into turtlesim's canvas by turtlesim. `/clear` erases *that* canvas. An image drawn *by us*, in *our* window, is a different surface entirely: turtlesim has no handle on it, so `/clear` cannot erase it. Nothing to redeploy.

What *does* need handling is the stacking order. On X11, clicking the turtlesim window raises it, and a raise beats an ordinary "always on top" window, so the overlay can end up behind the window it is annotating. Re-asserting the overlay's geometry and raise on a short timer covers that, and covers the user moving or resizing the window too. That timer is the mechanism; no `/clear` hook is needed.

### The measured geometry this design rests on

All of these were measured against the installed turtlesim 1.10.9 (distro `lyrical`) on this machine, not taken from documentation.

- The canvas `QImage` is **500 x 500** px. The turtlesim client window measures **500 x 500** px, so the image fills the client area and its origin is the client origin.
- The world is **[0, 11.088889] m square** (not 11.54). Measured by driving a turtle into each wall.
- `11.088889 / 2 = 5.5444445`, which is exactly the pose turtlesim spawns `turtle1` at. The rescuer's spawn point is the exact centre of the canvas.
- Scale: **45.0902 px/m**. Cross-check: the stock sprites are 45 x 45 px, which is 0.998 m — a ~1 m turtle in an 11 m arena.
- The start zone is 1.2 m square, so it is **54.11 px**, 10.8% of the canvas.

Correction to Version 1: the spawner's `canvas_x_max` and `canvas_y_max` defaults of `11.54` were wrong. The real extent is `11.088889`. Fixed as part of this version.

### The image itself

`safe_zone.png` is 256 x 256 RGBA: a transparent field with a centred, symmetric marker in two semi-transparent blues. Its non-transparent content occupies x,y `8..248`, centred on `128,128` — so the art is 93.75% of the image. Scaling the whole 256 px image to the 1.2 m zone puts the art at 1.125 m (50.7 px) with the centre exactly on the zone centre. The transparency is what makes an overlay workable: the marker is see-through everywhere it is not drawn, so the victim and rescuer stay visible inside the zone.

One consequence: an overlay window is *always above* turtlesim's canvas, so the marker is drawn over the turtles rather than under them. With this image that is harmless. A future opaque image would hide the rescue it is annotating.

## 4. Key words

- **Overlay** - a window drawn by us, placed over another window's canvas, that the target window knows nothing about.
- **X11** - the window system protocol the lookup speaks; turtlesim is forced onto X11 (`QT_QPA_PLATFORM=xcb`) because a Wayland client has no window another process can find or position.
- **ctypes** - Python's foreign function interface; used here to call `libX11.so.6` directly, so there is no new dependency to install and no subprocess.
- **Window tree walk** - breadth-first search over the X window hierarchy, matching `_NET_WM_NAME` (title) and `WM_CLASS` (class) to find the turtlesim client window.
- **World y up, screen y down** - the coordinate flip that puts the zone in the right place on the canvas.
- **Realised geometry** - where the window manager actually put the window, read back from X11 after `setGeometry` returns.
- **X error handler** - a process-wide callback libX11 calls when a request fails; the default prints and calls `exit(1)`.
- **Module-level trampoline** - a plain function at module scope that forwards to the real handler, avoiding the reference cycle a bound method creates.

## 5. How the pieces fit together

### Analogy: a transparent sticky note on a restaurant table

Imagine a restaurant table (the turtlesim canvas) where the staff wipe the surface clean every so often (`/clear`). You want a marker showing the "safe zone" where food should be placed. You cannot ask the staff to paint it on the table — they only have their standard wipe-clean surface. So you bring your own transparent plastic sheet (the Qt overlay window), draw the marker on it, and lay it exactly over the table. When the staff wipe the table, your sheet is untouched because it is not *on* the table, it is *above* it. When a customer leans on the table and shifts it, you notice and slide your sheet back into place. That is what the 10 Hz timer does.

### Walkthrough

1. **Node starts**. Reads all parameters (zone bounds, world size, canvas size, window title/class, track period). Validates them in `validation.py` — pure functions, unit-tested without ROS.
2. **If `turtlesim_gui:=False`**, the node stays idle: no Qt import, no X11 open, no timer. This is the headless path for CI.
3. **Otherwise**, load the marker PNG via `QPixmap` (lazy import of PySide6). Create a frameless, translucent, input-transparent, no-focus `QWidget` with `WindowStaysOnTopHint`. Do not show it yet — its geometry is not known.
4. **First timer tick** (and every tick after):
   - Open the X display once (`XOpenDisplay`). Install the module-level error handler *before* this call, so errors during display opening are also caught.
   - Walk the window tree from the root (breadth-first, depth-limited to 32). For each window: read attributes (`XGetWindowAttributes`), skip if not viewable or not `InputOutput` or `override_redirect`. Read `_NET_WM_NAME` via `XGetWindowProperty` (returns 0 on success). Read `WM_CLASS` via `XGetClassHint` (returns 1 on success). Both must match `TurtleSim` and `turtlesim_node`.
   - On match: translate the window's (0,0) to root coordinates (`XTranslateCoordinates`, returns 1 on success). That gives the client rect in screen pixels.
   - Compute the canvas rect: client rect + `canvas_margin_px` (0 here).
   - Compute the zone rectangle in canvas pixels via `zone_to_pixel_rect` in `geometry.py` — this is where the y-flip lives (world y up → screen y down).
   - Ask the overlay to cover the whole canvas (`setGeometry` with canvas rect) and paint the marker at the zone rect.
   - `overlay.show()` if hidden, then `overlay.raise_()` every tick — this is the re-assertion that keeps it on top.
   - Read back the overlay's *realised* geometry from X11 (attributes + translate) and log both requested and realised. Warn on mismatch.
   - Report swallowed X11 error count periodically (so a permanently broken display is not silent).
5. **Shutdown**: cancel timer, close overlay, close X display, `destroy_node`.

## 6. The eight technical challenges and their resolutions

### 1. X11 window discovery without python-xlib

**Problem**: No `python-xlib` installed, no `xdotool`/`wmctrl` (would mean a subprocess per lookup).

**Resolution**: `ctypes` against `libX11.so.6` directly. BFS over the X tree from the root, matching `_NET_WM_NAME` (title) and `WM_CLASS` (class). Only descend into viewable, `InputOutput`, non-override-redirect windows — this prunes the tree and bounds the walk. The first match in BFS order is the one nearest the bottom of the stack.

### 2. Geometry: world y-up → screen y-down flip, correct scale, tested against non-square world/canvas

**Problem**: World coordinates have y increasing up; screen coordinates have y increasing down. The zone would be drawn upside down without the flip. Also, the world and canvas might not be square in a different build.

**Resolution**: `world_to_pixel` in `geometry.py` does the flip explicitly:
```python
return (
    x * canvas_width_px / world_width_m,
    canvas_height_px - y * canvas_height_px / world_height_m,
)
```
`zone_to_pixel_rect` maps the zone's top-left (world `x_min, y_max`) and bottom-right (world `x_max, y_min`) independently, so a non-square world or canvas is handled by passing its own extents. Unit tests in `test_geometry.py` cover the flip, the centre, and non-square cases.

### 3. The Xlib return convention trap

**Problem**: `XQueryTree`, `XGetWindowAttributes`, `XGetClassHint`, `XTranslateCoordinates` return **1 on success**. `XGetWindowProperty` returns **0 on success** (`Success`). Getting one wrong does not raise — it silently finds nothing.

**Resolution**: Docstring guard in `_Xlib._declare_signatures` lists the convention for every call. The struct `_XWindowAttributes` is declared whole (136 bytes, `class_` at offset 40) because pulling the last field forward would make ctypes read whatever sits in memory. Verified against compiled C.

### 4. The missing X error handler

**Problem**: libX11's default handler prints to stderr and calls `exit(1)`. The lookup walks the whole window tree five calls deep ten times a second. A window destroyed between two of those calls would take the process with it: no ROS log, no shutdown, exit code 1.

**Resolution**: Module-level error handler installed at import time (before any X call, including `XOpenDisplay`). It counts errors and returns 0 (handled). The handler is a **module-level function** (`_x_error_handler`) with a module-level counter (`_X_ERROR_COUNT`), not a bound method. A bound method creates a reference cycle (instance → handler → `__self__` → instance). Cyclic GC can collect the trampoline while libX11 still holds the global pointer, and the next X error segfaults. The module-level version has no cycle, no instance lifetime coupling, and survives `del x; gc.collect()`.

### 5. Qt stacking: `Qt.Tool` under Weston moves the window to -32736,-32736. `WindowStaysOnTopHint` sets no `_NET_WM_STATE_ABOVE`. Screenshots are black. Stacking is unverified and left as a human check.

**Problem**: 
- `Qt.WindowType.Tool` makes the window transient for a Qt group leader that is never mapped; the window manager places it at -32768,-32768.
- `WindowStaysOnTopHint` on this session's Weston does not set `_NET_WM_STATE_ABOVE` (checked with `xprop`).
- `QScreen.grabWindow` returns all-black even for a known-colour window; `xwininfo -root -tree` order does not track X stacking here; no `xwd`, ImageMagick, grim, or weston-screenshooter available.

**Resolution**: Do not use `Qt.Tool`. Use `FramelessWindowHint | WindowStaysOnTopHint | WindowTransparentForInput | WindowDoesNotAcceptFocus`. The timer re-raises every tick. Whether the marker actually renders in front of the canvas **cannot be verified programmatically on this machine**. The code and docstrings do not claim it is verified. Human visual check is the Definition of Done item.

### 6. Realised vs requested geometry

**Problem**: `setGeometry` is a request; the window manager overrides it. Measured on this session: a request for `(-32730, -32709)` was realised as `(-32736, -32736)` — 6 px and 27 px out, enough to put the marker off the canvas.

**Resolution**: Read back the overlay's geometry from X11 after `processEvents()` (when Qt has sent the request and the WM has answered). Log both requested and realised. Warn on mismatch. Re-state the realised position every `PLACEMENT_REPORT_EVERY_TICKS` (300) ticks even when settled, because the first tick can run before the manager answers.

### 7. Single zone source

**Problem**: The start zone was copied in four places (spawner defaults, manager defaults, overlay defaults, launch defaults). Retuning the zone meant three edits that had to be kept equal by hand.

**Resolution**: Launch declares `start_zone_x_min/max` and `start_zone_y_min/max` once and passes them to all three nodes via `zone_parameters`. Retuning the zone is now one edit in the launch file.

### 8. `turtlesim_gui` dead parameter

**Problem**: The launch originally conditioned the overlay on `turtlesim_gui`, meaning `turtlesim_gui:=False` could never start the overlay — the rationale was backwards. `turtlesim_gui:=False` means "do not start turtlesim from this launch"; the overlay can still attach to an external turtlesim.

**Resolution**: Overlay is conditioned on `show_safe_zone` (default `True`), not on `turtlesim_gui`. The overlay needs a turtlesim window and an X display; neither has to come from this launch file. The docstring in the launch file explains this explicitly.

## 7. Testing approach

No screenshot verification is possible on this machine (see challenge 5). The 131 passing tests include 14 new tests in `test_safe_zone.py` covering:

- **Struct layout**: `_XWindowAttributes` is 136 bytes with `class_` at offset 40 — pinned against compiled C, because reading the wrong offset returns a plausible wrong number.
- **Headless path**: `turtlesim_gui:=False` declares every parameter, starts no timer, imports no Qt bindings (`PySide6`, `shiboken`, `PyQt5`, `PyQt6`).
- **Error handler survival**: a window destroyed mid-lookup (`attributes(0xDEADBEEF)`) is counted, the process survives, and the connection stays usable.
- **Error exits**: `main()` catches `ValueError`, `ParameterException`, `InvalidNodeNameException`, `OSError`, `ModuleNotFoundError` — each produces exactly one log line ("cannot start: ...") and exit code 2, not a traceback.
- **Image path resolution**: empty string resolves to the installed `share/rescue_turtle/media/safe_zone.png` via the ament index; explicit paths are used as given.
- **Three weak tests fixed**: previously asserted only that a method ran; now assert real behaviour (error count increments, headless node has no timers, bad path reported before missing Qt).

All tests run headless; the display tests skip themselves when `$DISPLAY` is absent.

## 8. What remains

Human visual check: verify the marker is visible in front of the turtlesim canvas at the correct position (centred on the rescuer spawn, sized to the 1.2 m start zone), stays there across `/clear` calls, window moves, and resizes, and the victim is visible through the transparent parts.

## 9. A few lines of code, explained line by line

### The y-flip in `geometry.py`

```python
def world_to_pixel(
    x: float,
    y: float,
    *,
    world_width_m: float,
    world_height_m: float,
    canvas_width_px: float,
    canvas_height_px: float,
) -> Point:
    return (
        x * canvas_width_px / world_width_m,
        canvas_height_px - y * canvas_height_px / world_height_m,
    )
```

- Line 1-7: signature takes world coordinates and the two extents (world metres, canvas pixels).
- Line 9: x scales linearly, no flip.
- Line 10: y scales linearly **then subtracted from canvas height**. World y=0 (bottom) becomes screen y=canvas_height (bottom). World y=world_height (top) becomes screen y=0 (top). That is the whole flip.

### The return convention guard in `_Xlib._declare_signatures`

```python
        # The return conventions are not uniform and are the trap in this file:
        # XQueryTree, XGetWindowAttributes, XGetClassHint and
        # XTranslateCoordinates all return non-zero on success, while
        # XGetWindowProperty returns Success, which is zero. Getting one of
        # them the wrong way round does not raise, it silently finds nothing.
        library.XQueryTree.restype = integer          # 1 = success
        library.XGetWindowAttributes.restype = integer  # 1 = success
        library.XGetClassHint.restype = integer        # 1 = success
        library.XTranslateCoordinates.restype = integer # 1 = success
        library.XGetWindowProperty.restype = integer   # 0 = success
```

- Each `restype` is declared explicitly so ctypes does not guess.
- The comment is the guard: a future reader who changes one of these has the convention in front of them.

### The module-level error handler trampoline in `safe_zone.py`

```python
_X_ERROR_COUNT = 0

def _x_error_handler(display: Any, event: Any) -> int:
    global _X_ERROR_COUNT
    _X_ERROR_COUNT += 1
    return 0

_X_ERROR_HANDLER_TRAMPOLINE = X_ERROR_HANDLER(_x_error_handler)
```

- `_X_ERROR_COUNT` lives at module scope, not on an instance.
- `_x_error_handler` is a plain function — no `self`, no closure over an instance.
- `_X_ERROR_HANDLER_TRAMPOLINE` is created once at import time and never dies.
- No reference cycle, no GC hazard, survives `del node; gc.collect()`.

### Reading back realised geometry in `_report_placement`

```python
        overlay_window = int(self._overlay.winId())
        attributes = xlib.attributes(overlay_window)
        origin = xlib.translate(overlay_window, 0, 0)
        if attributes is None or origin is None:
            return
        realised = WindowRect(
            origin[0], origin[1], attributes.width, attributes.height)
```

- `winId()` gives the X11 window ID of the Qt overlay.
- `attributes()` reads `XGetWindowAttributes` (width, height).
- `translate(overlay_window, 0, 0)` asks X11 where that window's (0,0) is in root coordinates — this accounts for the window manager's frame.
- The realised rect is compared to the requested rect; mismatch is a warning.

## 10. Check yourself

1. **Why does the overlay survive `/clear` without a redeploy hook?**
2. **What would happen if the X error handler were a bound method of `_Xlib` instead of a module-level function?**
3. **The launch file declares `start_zone_x_min` once and passes it to three nodes. What would go wrong if each node kept its own default?**

### Answers

1. `/clear` erases turtlesim's *canvas*. The overlay draws in a *separate window* that turtlesim has no handle on, so `/clear` cannot reach it. The timer re-asserts placement for raises/moves/resizes, not for `/clear`.
2. A bound method creates a reference cycle (instance → handler → `__self__` → instance). Cyclic GC can collect the trampoline while libX11 still holds the global function pointer. The next X error would call a freed pointer and segfault the process.
3. Retuning the zone would need three edits kept equal by hand. A zone the three nodes disagree about is a marker drawn in the wrong place rather than an error — the worst kind of bug because it looks like it works.

## 11. Say it in an interview

- I built a safe zone marker for turtlesim by overlaying a transparent Qt window over the canvas, placed via X11 window discovery with ctypes/libX11. turtlesim has no API for custom images, so an overlay was the only route.
- The overlay survives `/clear` because it is not drawn into turtlesim's canvas; a 10 Hz timer re-finds the window and re-asserts geometry and stacking, which also handles window moves, resizes, and the turtlesim window being raised by a click.
- The hard parts were the Xlib return convention trap (most calls return 1 on success, `XGetWindowProperty` returns 0), installing a module-level X error handler before the first X call to avoid libX11's default `exit(1)`, and reading back realised geometry from X11 because `setGeometry` is a request the window manager can override.

## 12. What's next

- Human visual check of the marker (the only remaining DoD item).
- Version 1.2: autonomous `rescuer` node (SEEK → RESCUE → RETURN) that takes the same `rescuer` name parameter and uses the safe zone as its goal.