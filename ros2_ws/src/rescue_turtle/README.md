# rescue_turtle

Rescue one turtlesim turtle with another. A turtle drives over to a turtle that
is stranded, picks it up, and drags it back to the start zone. Built on stock
turtlesim, which is never modified.

The point of this package is not the game. It is a logic prototype: the rescue
rules are worked out in turtlesim, where they are quick to change and easy to
test, so they can later be ported to a Gazebo robot. The Gazebo port is a
separate project and has not started.

## Versions

A version is a shipped state of the package. Changes to an already-shipped
version are numbered `1.1`, `1.2`, and so on, so a fix to what is already working
does not require inventing a new major version.

| Version | Status | What it adds |
| --- | --- | --- |
| 1. Manual driving, automatic game logic | done | A human drives the rescuer on the keyboard. Two nodes run the rules: `spawner` places the victim and respawns it after each rescue, `rescue_manager` attaches, drags and scores. |
| 1.1 Safe zone overlay | done | A third node, `safe_zone`, draws `safe_zone.png` over the turtlesim canvas, centred on the rescuer's spawn point and scaled to the start zone. |
| 2. Autonomous rescuer | next | A `rescuer` node replaces the human. It seeks the victim, grabs it, and returns to the exact start position using `cmd_vel`. |
| 3. Fleet | later | Several autonomous rescuers, plus a dispatcher that hands out victims. |

Version 1 was built with Version 3 in mind. Every topic, service, node name and
threshold is a parameter, the manager's state is scoped to a
`(rescuer, victim)` pair rather than to a role, and the interesting logic sits
in modules that import no rclpy so it can be unit tested without a running ROS
graph. The payoff is that Version 3 should be configuration, not a rewrite.

## Layout

```
rescue_turtle/
  rescue_pair.py      names for one pair; derives every topic and service name
  geometry.py         distance, zone containment, world-to-pixel, spawn sampling
  states.py           the FSM states and the post-success hold predicate
  arg_overrides.py    reads -p and --params-file before the node exists
  validation.py       startup parameter checks; fail fast, never silently
  spawner.py          SpawnerNode: the victim's lifecycle
  rescue_manager.py   RescueManagerNode: IDLE/RESCUE for one pair
  safe_zone.py        SafeZoneNode: the marker over the canvas, found via libX11
resource/safe_zone.png  the marker, installed to share/rescue_turtle/media/
launch/rescue_turtle.launch.py
test/                 126 unit tests and 5 linters, 131 in the colcon total
docs/spec.md          the approved design and the measured turtlesim facts
docs/progress.md      what was done, what was decided, what is next
docs/lessons/         plain-language notes on what was built and why
```

The first three modules deliberately import nothing from rclpy. That is what
makes name derivation, zone containment and spawn sampling testable in isolation.
`safe_zone.py` imports PySide6 inside the three functions that need it, so
importing it needs neither Qt nor a display, and the headless path never gets
that far at all.

## Run it

One shell is one environment, so `source` in every new terminal. The workspace is
`ros2_ws/`.

```bash
cd ~/robotics-factory/ros2_ws
colcon build --packages-select rescue_turtle
source install/setup.bash
```

Then, in two separate terminals, each re-sourcing first.

**Terminal 1** — the turtlesim window and the two game nodes. The launch file
starts turtlesim itself, so do not start a second one alongside it:

```bash
source install/setup.bash
ros2 launch rescue_turtle rescue_turtle.launch.py
```

**Terminal 2** — your keyboard control of the rescuer:

```bash
source install/setup.bash
ros2 run turtlesim turtle_teleop_key
```

Order does not matter technically: teleop publishes `/turtle1/cmd_vel` whether
or not turtlesim exists yet, and turtlesim subscribes when it comes up. Starting
the launch first is still the better instruction, because otherwise keypresses
before the window exists go nowhere and look like a broken teleop.

`turtle_teleop_key` must run in a real terminal, not in the background. It puts
the keyboard into raw mode, and without a tty it aborts with
`Failed to get old console mode`.

If you would rather drive an already-running turtlesim, pass
`turtlesim_gui:=False` and start turtlesim yourself. The overlay still starts: it
needs a turtlesim window to sit over, not a turtlesim of its own. What it cannot
do is force yours onto X11, so start it as
`QT_QPA_PLATFORM=xcb ros2 run turtlesim turtlesim_node`, or the overlay will log
that it found no window.

Watch the victim spawn away from the start zone, drive the rescuer over to it,
and the pair will attach once within `attach_distance`. The background turns red
during the rescue, the victim follows you, and on reaching the start zone the
background returns to white and a new victim spawns.

`turtle_teleop_key` is deliberately not started by the launch file: it needs a
terminal of its own.

### The safe zone overlay

The launch file starts `safe_zone` as well, which puts a translucent marker over
the turtlesim canvas at the start zone. turtlesim itself cannot show an image
file, so this is a window of our own, found by asking X11 where the turtlesim
window is and kept over it by a 10 Hz timer. Two consequences worth knowing
before you are surprised by them:

- **turtlesim is forced onto X11.** The launch file sets `QT_QPA_PLATFORM=xcb`
  for turtlesim and for the overlay, so turtlesim renders through XWayland
  instead of the session's native Wayland. A Wayland client has no window another
  process can find or place, so without this the overlay has nothing to attach
  to. Without it the overlay logs the reason rather than failing quietly.
- **PySide6 has to be installed.** It is imported lazily, only on the overlay's
  GUI path, and it is not a declared dependency of the package: install the
  distribution's `python3-pyside6`, or run with `show_safe_zone:=False`.

Useful launch arguments, all optional:

| Argument | Default | Effect |
| --- | --- | --- |
| `rescuer_name` / `victim_name` | `turtle1` / `turtle2` | The pair to run |
| `attach_distance` | `0.7` | Metres within which the rescue attaches |
| `min_spawn_distance` | `2.0` | Metres a victim must spawn clear of the start zone |
| `follow_rate_hz` | `20.0` | Manager control timer rate |
| `rng_seed` | `-1` | Set a number for reproducible spawns |
| `turtlesim_gui` | `True` | `False` to attach to a turtlesim already running |
| `show_safe_zone` | `True` | `False` to leave the overlay out |
| `safe_zone_image` | `''` | Marker file, empty uses the one installed |
| `start_zone_x_min` / `_max`, `start_zone_y_min` / `_max` | `4.944` / `6.144` | The start zone, passed to all three nodes |

A second pair is a second launch with different names, from the same binaries:

```bash
ros2 launch rescue_turtle rescue_turtle.launch.py rescuer_name:=turtle2 victim_name:=turtle3
```

## Test it

```bash
cd ~/robotics-factory/ros2_ws
colcon build --packages-select rescue_turtle
colcon test --packages-select rescue_turtle
colcon test-result --verbose
```

Agents cannot see the turtlesim window, so every automated check reads state back
through topics, services and parameters instead of looking at the screen:

```bash
ros2 node list                                    # the two pair-scoped nodes, plus /safe_zone
ros2 param list /rescue_manager_turtle1_to_turtle2
ros2 topic echo /rescue_turtle/turtle1_to_turtle2/status
ros2 topic info /turtle2/pose -v                  # publisher count of 1
ros2 param get /turtlesim background_g            # 0 in RESCUE, 255 otherwise
```

Read the colour from `background_g`, not `background_r`: the rescue colour is
`255 0 0` and the default is `255 255 255`, so `background_r` is 255 either way
and cannot tell the two states apart.

The status topic is `TRANSIENT_LOCAL` and keeps a backlog, so a subscriber that
connects late is handed every earlier status, oldest first. `ros2 topic echo`
without `--once` therefore prints the startup `idle` before the current one.
Read the whole sequence, or attach before the state you care about happens.

There is one mechanical check that enforces the no-hard-coded-names rule:

```bash
grep -rn "turtle1\|turtle2" rescue_turtle/        # must return nothing
```

The overlay's placement is checked numerically rather than by eye, because
screenshots do not work on this machine: `QScreen.grabWindow` returns an all-black
pixmap even for a window the grabbing process has just filled with a known
colour. So the node logs what it found and what it computed, and reads its own
window's geometry back out of X11:

```bash
xwininfo -name TurtleSim                          # the canvas, 500 x 500 px
xwininfo -name rescue_turtle_safe_zone            # the overlay, over the same origin
```

The human visual check for Version 1 has been done: driven on the keyboard, the
background turns red on attach and the victim visibly tracks the rescuer, and
both return to white on success with a new victim spawning clear of the start
zone. For 1.1 the arithmetic and the geometry are checked above and what is left
is the human's: that the marker is visible over the canvas, centred on the
rescuer's spawn point, sized to the start zone, still there after several
`/clear` calls, and that the victim shows through it.

## Known limits

These are deliberate for Version 1, not oversights.

- **The background colour is global.** turtlesim has one `background_r/g/b`
  triple, so two managers running at once overwrite each other's colour. Fixing
  it means a fleet-wide colour policy, which is a Version 3 decision.
- **The isolation unit is the turtle-name pair, not the ROS namespace.** Derived
  names are absolute (`/{name}/pose`), so namespacing a node does not redirect
  them. Two instances coexist only if given different `rescuer_name` and
  `victim_name` values. This is not namespace-based multi-tenancy.
- **Keep `min_spawn_distance` above `attach_distance`.** Nothing enforces it
  across nodes, and if the spawn distance is smaller the victim spawns already in
  attach range and the game loops every `respawn_delay_s`.

From 1.1:

- **The overlay needs turtlesim on X11.** A Wayland turtlesim has no window
  another process can find, so the overlay logs that it found nothing and waits.
  The launch file forces `QT_QPA_PLATFORM=xcb` for the turtlesim it starts; one
  you start yourself has to be launched that way too.
- **The overlay is above the turtles, never below them.** Fine for a transparent
  marker, wrong for an opaque one.
- **One overlay per canvas, and only the one the launch file starts.** Two
  turtlesim windows share a title and a window class, so two overlays would both
  match the same window. Version 3 with several canvases needs a per-window
  identifier.
- **Where the marker is placed is arithmetic on measured constants.** The world
  is 11.088889 m and the canvas 500 px, both read off this turtlesim build. A
  build with a different canvas needs `canvas_width_px` and `canvas_height_px`
  changed; the node warns when the window it finds disagrees with them.
- **The window manager can put the overlay somewhere else.** `setGeometry` is a
  request. The node reads its realised geometry back and logs a warning when the
  two disagree, but whether the marker is actually in front of the canvas is a
  compositing question the log cannot answer.

## Conventions

Python only, no Gazebo. The design lives in `docs/spec.md`, the log in
`docs/progress.md` and is append-only, and after each committed task the
department writes a lesson to `docs/lessons/`.
