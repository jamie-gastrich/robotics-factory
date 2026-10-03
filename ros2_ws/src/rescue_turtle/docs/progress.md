# Progress Log (append only)

## Setup
- Package created, AGENTS.md and docs added. Next: get a Phase 1 plan approved.

## 2026-09-29 — Phase 1 implemented
- Done: spawner and rescue_manager nodes, launch file, setup.py entry points and
  launch data_files, package.xml deps, and unit tests. `colcon build` is
  warning-free; `colcon test` passes 84 tests, 0 failures.
- Verified headlessly (topics, services and parameters only): turtle2 spawns;
  IDLE stays IDLE while the rescuer is far away; the pair attaches and the
  background goes 255/0/0; the victim pose tracks the rescuer pose; SUCCESS in
  the start zone returns the background to 255/255/255; the victim respawns with
  exactly two pose topics on the graph.
- Not verified: the human-only visual check (background visibly red/white,
  victim visibly tracking). The `turtle_teleop_key` path was not exercised.

### Decisions
- The FSM needed a post-success hold that the approved plan did not contain. At
  SUCCESS the victim is still on the rescuer, so IDLE re-attaches on the next
  20 Hz tick and drags the freshly respawned victim back out; plan step 9 was
  unachievable as written. Added as a hold, released by a pure predicate in
  `states.hold_release_reason()`.
- The hold releases on the live victim pose differing from the pose recorded at
  SUCCESS, not on geometry. The geometric condition was unsound: the kill->spawn
  gap is far shorter than `pose_timeout_s`, and separation is unreachable when
  the rescuer is parked in the start zone and `min_spawn_distance` is below
  `attach_distance`. Confirmed by reproduction: the geometric version latched
  after one rescue, the version now shipped ran 30 rescues in a row.
- Node names are derived from the pair, but a node cannot read its own parameters
  before it exists, so `main()` parses the ROS argument vector to learn what to
  call itself. `launch_ros` supplies parameters via a generated `--params-file`,
  so both that and `-p` are read. This is why `arg_overrides.py` exists as a
  module separate from `rescue_pair.py`.
- `min_spawn_distance` should exceed `attach_distance`. With the hold fixed this
  is not a hang, but it makes the game churn at `respawn_delay_s` cadence.
  Noted in the spec's parameter tables; no cross-node check was built.

### Next step
- Human visual check of the rescue, then commit. Phase 2 is the autonomous
  `rescuer` node (SEEK -> RESCUE -> RETURN), which takes the same rescuer name
  parameter.

## 2026-10-01 — Renamed "phase" to "version"
- Done: terminology changed across `README.md`, `AGENTS.md`, `docs/spec.md`,
  `docs/lessons/2026-09-30-version-1-manual-rescue.md` (renamed from
  `2026-09-30-phase-1-manual-rescue.md`) and one docstring in `rescue_pair.py`.
  No behaviour changed; no node, topic, service or parameter was touched.
- The entries above keep the word "Phase" as written on the day they were
  recorded. They are history, not current terminology.

### Decisions
- The term is "version", not "phase". The reason given is that changing what is
  already shipped should read as `1.1`, and "phase 1.1" reads as a contradiction
  where "version 1.1" does not. The numbering therefore means: `1` is the first
  shipped state, `1.1` and `1.2` are changes to it, `2` is the next major
  version. Added to `README.md` so the convention is written down rather than
  assumed.
- This project had no `1.1` yet, so nothing was renamed inside the numbers. The
  Version 1 changes the author now has in mind become `1.1`.

### Next step
- Start Version 1.1. The human visual check of Version 1 is still the open item
  from the entry above.

## 2026-10-02 — Visual check done; corrected the verification instructions
- Done: the human visual check is complete. Driven on the keyboard, the
  background turns red on attach and the victim visibly tracks the rescuer; both
  return to white on success and a new victim spawns clear of the start zone.
  Version 1 has no outstanding check now.
- Done: corrected three instructions in `README.md` and `AGENTS.md` that were
  wrong. None of them changed behaviour.
- Also wrote the repository `README.md` at the root, which did not exist.
- Terminal order corrected: the launch starts turtlesim, so the launch is
  terminal 1 and `turtle_teleop_key` is terminal 2. Verified that teleop-first
  is not broken, only pointless: teleop publishes `/turtle1/cmd_vel` with no
  subscriber and turtlesim subscribes when it starts.

### Decisions
- The run instructions started `turtlesim_node` in one terminal *and* ran the
  launch in another, but the launch file starts turtlesim itself. Two
  `/turtlesim` nodes. Now two terminals: `turtle_teleop_key`, then the launch.
  The stale `(once it exists)` note in `AGENTS.md` went with it.
- The documented colour check read `background_r`. That parameter is 255 both in
  `255 0 0` and in `255 255 255`, so it cannot tell RESCUE from IDLE. The
  check now reads `background_g`: 0 while rescuing, 255 otherwise. Verified live
  in both states.
- The status topic is `TRANSIENT_LOCAL` with depth 10, so a late subscriber is
  handed the whole backlog, oldest first. `ros2 topic echo --once` therefore
  prints the startup `idle` rather than the current state, which reads as "the
  rescue never started". Documented instead of changed: the latched startup idle
  is deliberate, so a subscriber that attaches late still sees a state.
- Status clarified: version 1 is shipped and verified, and the project is not
  finished. The changes in mind for it are 1.1. This supersedes the 2026-09-29
  framing, where Phase 1 was the whole of the plan.
- The 2026-09-29 entry says the visual check is unverified and the 2026-10-01
  entry calls it the open item. Both stay as written; this entry supersedes
  them.

### Next step
- Version 1.1. The visual check is no longer blocking. Version 1 is shipped and
  verified; the author has changes in mind for it that are numbered 1.1, and
  that work has not started. Nothing is specced for it yet, so 1.1 begins with
  a plan in this file's sibling, `spec.md`.

## 2026-10-03 — Version 1.1 implemented: safe zone overlay
- Done: added a `safe_zone` node that draws `resource/safe_zone.png` over the
  turtlesim canvas, centered on the rescuer spawn point (5.544444, 5.544444) and
  scaled to the 1.2 m start zone (4.944..6.144 m). The overlay is a separate
  frameless Qt window placed via X11 window discovery (ctypes/libX11); a 10 Hz
  timer re-asserts geometry and stacking across moves, resizes, and `/clear`.
- Build: warning-free `colcon build`; 131 tests pass (0 failures), including 14
  new tests in `test_safe_zone.py` covering the Xlib error handler, headless
  path, struct layout, and `main()` error exits.
- Key fixes during review: Xlib error handler installed before first X call with
  module-level trampoline to prevent GC segfault; `OSError`/`ModuleNotFoundError`
  caught cleanly in `main()`; realised overlay geometry read back from X11 and
  logged (no longer claiming requested position as fact); single zone source in
  launch file; `turtlesim_gui` no longer gates the overlay; docstrings corrected
  to match actual conventions.
- Docs: `docs/spec.md` DoD amended to match implementation (`turtlesim_gui:=False`
  keeps the node present but idle); `README.md` and `AGENTS.md` updated for 1.1.

### Decisions
- The overlay is a separate always-on-top window because turtlesim cannot load a
  custom PNG through `/spawn` (no texture field; `/turtlesim` exposes only
  background_r/g/b and holonomic; all 13 sprite PNGs are loaded at startup, none
  on `/spawn`). An unknown spawn name silently uses a stock sprite.
- `/clear` only erases turtlesim's canvas; the overlay cannot be erased and does
  not need a redeploy hook — the timer re-asserts placement on every tick.
- Stacking order cannot be verified on this machine: `QScreen.grabWindow`
  returns all-black even for a known-colour window; `xwininfo -root -tree` order
  was calibrated and does NOT track X stacking here; `_NET_WM_STATE` is empty on
  both the overlay and the turtlesim window; no xwd, ImageMagick, grim, or
  weston-screenshooter available. Whether the marker renders in front of the
  canvas is a human visual check and stays that way. The code and docstrings do
  not claim it is verified.
- The Xlib return conventions in the *code* are correct (`XQueryTree`,
  `XGetWindowAttributes`, `XGetClassHint`, `XTranslateCoordinates` return 1 on
  success; `XGetWindowProperty` returns 0), the `_XWindowAttributes` struct is
  byte-exact, and no memory leaks at 10 Hz. The initial bound-method handler
  created a reference cycle that could GC the trampoline while libX11 still held
  the pointer; fixed by moving the handler to module level.
- `turtlesim_gui:=False` in the launch file now means "do not start turtlesim
  from this launch"; the overlay starts if `show_safe_zone:=True` and can
  attach to an external turtlesim. This is the opposite of the original
  rationale, which was wrong.

### Next step
- Human visual check of the marker: verify it appears over the turtlesim canvas
  at the correct position and stays there across `/clear`, window moves, and
  resizes.
- Version 1.2: autonomous `rescuer` node (SEEK -> RESCUE -> RETURN) that takes
  the same `rescuer` name parameter and uses the safe zone as its goal.