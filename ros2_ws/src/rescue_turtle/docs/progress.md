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