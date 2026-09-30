# Rescue Turtle Spec

## Goal
Built on stock turtlesim. Turtle1 rescues turtle2 and brings it back to the start zone. Logic prototype for a later Gazebo version.

## Phase 1: Manual driving, automatic game logic
- Keyboard: existing turtle_teleop_key.
- A rescue is identified by a (rescuer name, victim name) pair, both
  parameters. `turtle1`/`turtle2` are defaults, not fixed roles.
- spawner: spawns the victim at a random position (min distance from start zone)
  via /spawn; respawns after each rescue.
- rescue_manager: subscribes to both poses of its pair.
  - IDLE: distance(rescuer, victim) < attach_distance -> RESCUE; set background
    color (params) and call /clear.
  - RESCUE: victim follows rescuer via /<victim>/teleport_absolute.
  - Victim in start zone -> SUCCESS: reset background, log, back to IDLE with a
    new victim.
- Parameters: attach_distance, start_zone bounds, rescue color, turtle names,
  topic/service names.

## Phase 2: Autonomous
- rescuer node: SEEK -> RESCUE -> RETURN via Twist on /<rescuer>/cmd_vel; must
  reach the exact start position. Takes the same rescuer name parameter.

## Phase 3: Fleet
- Several autonomous rescuer turtles plus a dispatcher that assigns victims to
  rescuers. Phase 1 and 2 code is written so this needs no rewrite: names are
  parameters, logic is in per-pair classes, and the same executables already
  run side by side.
- Gazebo port remains a later, separate project.

## Verification
- Topic checks: pose topics publish; the victim's pose tracks the rescuer's
  during RESCUE.
- Human visual check: background changes on rescue, resets on success.

## Open questions
- Timeout that fails a rescue?
- Score counter (topic or log)?

## Phase 1 Plan

Verified against the installed turtlesim 1.10.9 (distro `lyrical`) before writing
this plan. Facts that constrain the design:

- The GUI node is `/turtlesim` (not `/turtlesim_node`); its parameters are
  `background_r/g/b` (ints, 0-255) plus `holonomic`.
- Pose topics are `turtlesim_msgs/msg/Pose` on `/turtleN/pose`, published at
  ~62 Hz. Turtle1 starts at `x=5.544444, y=5.544444, theta=0.0`.
- Per-turtle services `/turtleN/teleport_absolute`, `/turtleN/teleport_relative`,
  `/turtleN/set_pen` and `/kill` only exist **after** that turtle has been
  spawned. Clients must tolerate the service being absent, and the name is
  reused when a turtle of the same name is respawned.
- Spawning a second turtle under a name that is already live does not replace
  it: turtlesim allocates the next free index. So the respawn path must
  `/kill` the old victim first, then `/spawn` the new one under the same name,
  to keep `/<victim>/pose` and `/<victim>/teleport_absolute` meaning the
  current turtle.
- Verified live: `ros2 param set /turtlesim background_r 200` succeeds,
  `/spawn` with `name: 'turtle2'` returns `turtle2`, and
  `/turtle2/teleport_absolute` moves turtle2's published pose.

### Phase 3 constraints applied now

Phase 3 is a fleet of autonomous rescuer turtles plus a dispatcher. Phase 1
builds none of that, but the Phase 1 code must not need rewriting to get there.
Four constraints, applied to everything below:

1. **No hard-coded turtle names.** `turtle1` and `turtle2` appear only as
   parameter defaults. Every topic and service name is derived from a
   `rescuer_name` and a `victim_name` pair, or overridden outright.
2. **`rescue_manager` owns a pair, not a role.** Its entire state is scoped to
   one `(rescuer_name, victim_name)` pair. It has no idea it is "the" manager
   and no field that means "the rescuer".
3. **Logic in parameter-driven classes.** All behaviour lives in a
   `rclpy.node.Node` subclass whose `__init__` reads every knob from
   parameters. No module-level mutable state, no reading the environment, no
   `main()` arguments beyond ROS args. Running the same executable twice with
   different parameters must be a supported configuration, so the process
   interface is unchanged between one instance and many.
4. **No fleet features.** One pair per node instance, driven by parameters.
   There is no dispatcher, no pair list, no `DeclareMultiRescue`, no dynamic
   pair discovery, no fleet-wide score, and no per-turtle background colours.
   The only concession to multi-instance use is that nothing is hard-coded.

Two consequences worth stating plainly, because they are limitations rather
than solved problems:

- **Isolation unit is the turtle-name pair, not the ROS namespace.** All derived
  names are absolute (`/{name}/pose`), which is what turtlesim publishes, so
  pushing a node into a namespace does not redirect them. Two instances run side
  by side only if they are given different `rescuer_name`/`victim_name` values.
  This is the correct Phase 1 shape and is also how the fleet will work, but it
  is not namespace-based multi-tenancy and is not claimed to be.
- **The background colour is global.** `/turtlesim` has exactly one
  `background_r/g/b` triple, so two managers running at once would overwrite
  each other's colour. Left as-is deliberately: fixing it means a fleet-wide
  colour policy, which is a Phase 3 decision. Phase 1 uses it as a single-pair
  visual signal.

### Files to create

| Path | Purpose |
| --- | --- |
| `rescue_turtle/rescue_pair.py` | `RescuePair` frozen dataclass: holds a `rescuer_name`/`victim_name` pair and derives every topic and service name from it. No rclpy import. |
| `rescue_turtle/geometry.py` | Pure helpers, no rclpy import. `distance`, `in_zone`, `random_spawn_pose`. |
| `rescue_turtle/states.py` | `Enum` for the FSM states. Pure, no rclpy import. |
| `rescue_turtle/spawner.py` | `SpawnerNode`: owns the lifecycle of one victim. |
| `rescue_turtle/rescue_manager.py` | `RescueManagerNode`: the IDLE/RESCUE/SUCCESS state machine for one pair. |
| `launch/rescue_turtle.launch.py` | Launch file for one pair. |
| `test/test_geometry.py` | pytest unit tests for the pure helpers. |
| `test/test_rescue_pair.py` | pytest unit tests for name derivation and validation. |

Files to modify: `setup.py` (entry points + `data_files`), `package.xml`
(add `turtlesim_msgs`, `std_srvs`, `launch`, `launch_ros`).

`rescue_pair.py`, `geometry.py` and `states.py` deliberately import nothing from
rclpy so the interesting logic (name derivation, zone containment, spawn
distance rejection sampling) is testable without a running ROS graph. This is
where the "no hard-coded names" constraint becomes a unit test rather than a
convention someone can quietly break.

### `RescuePair`

The single source of truth for names, used by both nodes. Frozen dataclass with
`rescuer_name` and `victim_name`; everything else is a derived property:

| Property | Derivation | For the default pair |
| --- | --- | --- |
| `rescuer_pose_topic` | `/{rescuer_name}/pose` | `/turtle1/pose` |
| `victim_pose_topic` | `/{victim_name}/pose` | `/turtle2/pose` |
| `victim_teleport_service` | `/{victim_name}/teleport_absolute` | `/turtle2/teleport_absolute` |
| `victim_kill_name` | `victim_name` | `turtle2` |
| `status_topic` | `/rescue_turtle/{rescuer}_to_{victim}/status` | `/rescue_turtle/turtle1_to_turtle2/status` |
| `node_name` | `rescue_manager_{rescuer}_to_{victim}` | `rescue_manager_turtle1_to_turtle2` |

The status topic and node name are pair-scoped for the same reason the rest is:
two instances must not talk over each other. `status_topic` and `node_name`
remain overridable by parameter, since a dispatcher will want to choose them.

`__post_init__` validates both names against `[A-Za-z_][A-Za-z0-9_]*` and
rejects `rescuer_name == victim_name` (a turtle cannot rescue itself). Violations
raise `ValueError` at construction, which `main()` turns into a clear log line
and a non-zero exit, rather than a node that silently works on the wrong topics.

### Node responsibilities

**spawner** — owns the lifecycle of one victim, nothing else.

1. Read `victim_name`, build a `RescuePair`, and take the spawn/kill/clear
   service names from parameters.
2. Wait for `/spawn` (bounded by `service_wait_timeout_s`), then `/kill` any
   existing victim by name, `/clear`, and `/spawn` at a fresh random pose under
   that name.
3. Subscribe to the pair's status topic. On the rescue-complete status, wait a
   short `respawn_delay_s` (so the manager can reset its state and the human can
   see the result), then repeat step 2.
4. Log every spawn with x, y, theta and the distance from the start zone.

`spawner` never looks at poses and never decides game state. It does not need
the rescuer's name for anything except the shared status topic, which it gets
from the same `rescuer_name` parameter.

**rescue_manager** — the state machine for one pair, driven by one timer.

1. Build a `RescuePair` from `rescuer_name` and `victim_name`. Subscribe to
   `pair.rescuer_pose_topic` and `pair.victim_pose_topic`. The callbacks only
   cache the latest pose plus its stamp; they do no logic. A cached pose older
   than `pose_timeout_s` is treated as absent, so the gap while the victim is
   killed and respawned cannot produce a bogus transition.
2. One control timer at `follow_rate_hz` evaluates the whole FSM. One timer
   means one rate, no reentrancy, and no acting on a half-updated pose pair.
3. States:
   - `IDLE`: if both poses are fresh and `distance(rescuer, victim) <
     attach_distance`, set the `/turtlesim` background params to
     `rescue_color_*`, call `/clear`, and go to `RESCUE`.
   - `RESCUE`: if the victim is inside the start zone, set the background back
     to `default_color_*`, call `/clear`, log SUCCESS, publish the success
     status, and go to `IDLE`. Otherwise, `call_async`
     `pair.victim_teleport_service` with the rescuer's pose. A single in-flight
     request is allowed at a time; if the previous one has not completed the
     tick is skipped, so a slow service cannot queue up an unbounded backlog of
     teleports.
   - `SUCCESS` is not a state; it is a logged, published event, and the
     transition is back to `IDLE` immediately. `spawner` owns the respawn.
4. Status publishing on `pair.status_topic`: `idle`, `rescue_started`,
   `rescue_complete`. This is the only coupling between the two nodes, and it
   is observable with `ros2 topic echo`, which is the main testing hook.
5. The in-flight flag, the pose cache and the current state are instance
   attributes. Nothing is class-level, so two `RescueManagerNode` objects in
   one process, or two processes on the machine, cannot interfere.

Background colour is set through `rclpy.parameter_client.AsyncParameterClient`
against the parameterised `turtlesim_node` name, rather than by calling the
parameter services by hand.

### Parameters

**spawner**

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `rescuer_name` | str | `turtle1` | Only used to derive the shared status topic. |
| `victim_name` | str | `turtle2` | The name passed to `/spawn` and `/kill`. |
| `node_name` | str | derived | Defaults to `spawner_<rescuer>_to_<victim>`. |
| `spawn_service` | str | `/spawn` | |
| `kill_service` | str | `/kill` | |
| `clear_service` | str | `/clear` | |
| `status_topic` | str | derived | Defaults to the pair-scoped status topic. |
| `start_x`, `start_y` | float | `5.544444` | The rescuer's start pose, measured. |
| `start_zone_x_min/max`, `start_zone_y_min/max` | float | `4.944, 6.144` | Box around the start, half-width 0.6. |
| `min_spawn_distance` | float | `2.0` | From the nearest point of the start zone. Keep it above the manager's `attach_distance`: a victim that spawns closer than the attach distance is attached and rescued the moment it appears. |
| `canvas_x_min/max`, `canvas_y_min/max` | float | `0.0, 11.54` | Keeps the victim on screen. |
| `spawn_theta_random` | bool | `True` | |
| `rng_seed` | int | `-1` | `-1` = non-deterministic; any other value makes spawns reproducible. |
| `respawn_delay_s` | float | `1.0` | Pause after a rescue so the result is visible. |
| `service_wait_timeout_s` | float | `5.0` | |
| `service_retry_period_s` | float | `1.0` | How often to re-check for turtlesim while no victim can be spawned. |
| `rescue_complete_status` | str | `rescue_complete` | Status string that triggers a respawn. |

**rescue_manager**

| Name | Type | Default | Notes |
| --- | --- | --- | --- |
| `rescuer_name` | str | `turtle1` | Root of the rescuer pose topic. |
| `victim_name` | str | `turtle2` | Root of the victim pose topic and teleport service. |
| `node_name` | str | derived | Defaults to `rescue_manager_<rescuer>_to_<victim>`. |
| `rescuer_pose_topic` | str | derived | Default `/{rescuer_name}/pose`. |
| `victim_pose_topic` | str | derived | Default `/{victim_name}/pose`. |
| `victim_teleport_service` | str | derived | Default `/{victim_name}/teleport_absolute`. |
| `status_topic` | str | derived | Pair-scoped. |
| `clear_service` | str | `/clear` | |
| `turtlesim_node` | str | `turtlesim` | For the parameter client. |
| `attach_distance` | float | `0.7` | Keep it below the spawner's `min_spawn_distance`, so a fresh victim starts out of attach range. |
| `follow_rate_hz` | float | `20.0` | Control timer rate. |
| `pose_timeout_s` | float | `1.0` | Stale-pose guard. |
| `service_wait_timeout_s` | float | `5.0` | |
| `start_zone_x_min/max`, `start_zone_y_min/max` | float | `4.944, 6.144` | Must match `spawner`. |
| `rescue_color_r/g/b` | int | `255, 0, 0` | Background during a rescue. |
| `default_color_r/g/b` | int | `255, 255, 255` | Background on success. |
| `status_idle` / `status_rescue` / `status_complete` | str | `idle` / `rescue_started` / `rescue_complete` | |

The seven `str` parameters that default to *derived* cannot be declared with a
static default string, since the default depends on the pair. The pattern is
`declare_parameter` with a sentinel empty default, then
`get_parameter(...).value or <derived>`, so an explicit override still wins.

Every parameter above is `declare_parameter`'d; no topic, service, node, colour,
name or threshold is hard-coded anywhere in the package. `rescue_pair.py` holds
the only string literals, and they are `"/pose"`, `"/teleport_absolute"` and
similar format suffixes, not turtle names. Both nodes validate
`rate`/distance/bounds and name validity at startup and fail fast with a clear
log rather than misbehaving silently.

### Launch file

`launch/rescue_turtle.launch.py` (`launch_ros.actions.LaunchDescription`):

- Declares arguments: `rescuer_name` (default `turtle1`), `victim_name`
  (default `turtle2`), `spawner_node_name` and `manager_node_name` (one per
  node, never shared: two nodes under one name would share a parameter
  namespace and a logger), `attach_distance`, `follow_rate_hz`,
  `min_spawn_distance`, `spawn_theta_random`, `rng_seed`, `turtlesim_node`, and
  `turtlesim_gui` (default `True`).
- With `turtlesim_gui:=True`, runs `turtlesim_node`. With it `False`, the launch
  assumes a turtlesim is already running, which is what the headless tests use.
- Starts `spawner` then `rescue_manager`, passing the pair through to both so
  they agree on the status topic.
- Does not start `turtle_teleop_key`: that is the human's manual input, and it
  needs a terminal on the keyboard, not a launch-managed process.
- Launches exactly one pair. A second pair is a second `ros2 launch` with
  different `rescuer_name`/`victim_name`, which is a manual action today and is
  left that way on purpose.

### setup.py

```python
entry_points={
    'console_scripts': [
        'spawner = rescue_turtle.spawner:main',
        'rescue_manager = rescue_turtle.rescue_manager:main',
    ],
},
data_files=[
    ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
    ('share/' + package_name, ['package.xml']),
    ('share/' + package_name + '/launch',
        ['launch/rescue_turtle.launch.py']),
],
```

`package.xml` gains `<depend>turtlesim_msgs</depend>`, `<depend>std_srvs</depend>`,
`<exec_depend>launch</exec_depend>`, `<exec_depend>launch_ros</exec_depend>`.
`geometry_msgs` is not used by either node and will be removed.

Both nodes follow the `first_robot` shutdown pattern: `rclpy.init` → spin →
`destroy_node()` / `shutdown()` in a `finally`, catching `KeyboardInterrupt`,
`ExternalShutdownException` and `RCLError`. `main()` is the same for every
instance — it takes no turtle-name arguments, because the names arrive as ROS
parameters. The pair validation error from `RescuePair` is caught in `main()`,
logged, and exits non-zero.

### Verification without the GUI

No window is watched at any point. A turtlesim window does open on `$DISPLAY`,
but everything we assert is read back through topics, services and parameters.

The commands below use the default pair, so `turtle1` and `turtle2` appear in the
*test* commands, never in the code.

1. **Unit:** `colcon test --packages-select rescue_turtle` must pass.
   `test_geometry.py` covers `in_zone` edges, `distance`, and `random_spawn_pose`
   rejection sampling including the exhaustion path. `test_rescue_pair.py` covers
   name derivation for a non-default pair, the identifier validation regex, and
   the `rescuer_name == victim_name` rejection. All source files carry the
   Apache-2.0 header for `ament_copyright`.
2. **No hard-coded names:** `grep -rn "turtle1\|turtle2" rescue_turtle/` returns
   nothing. This is a mechanical check that enforces constraint 1 and is cheap
   enough to run every time.
3. **Interface:** `ros2 node list` shows
   `/spawner_turtle1_to_turtle2` and `/rescue_manager_turtle1_to_turtle2`;
   `ros2 param list /rescue_manager_turtle1_to_turtle2` shows every declared
   parameter.
4. **Headless launch:** `ros2 launch rescue_turtle rescue_turtle.launch.py
   turtlesim_gui:=False` against a separately started `turtlesim_node` brings up
   both nodes with no GUI dependency.
5. **Spawn:** within a few seconds `/turtle2/pose` exists (`ros2 topic info
   /turtle2/pose -v`, publisher count 1). The spawn log confirms the pose is
   outside the start zone by at least `min_spawn_distance`.
6. **IDLE stays IDLE:** drive turtle1 far away with
   `ros2 service call /turtle1/teleport_absolute turtlesim_msgs/srv/TeleportAbsolute
   "{x: 1.0, y: 1.0, theta: 0.0}"`; `ros2 param get /turtlesim background_r`
   still returns 255 and `ros2 topic echo
   /rescue_turtle/turtle1_to_turtle2/status` shows only `idle`.
7. **RESCUE:** teleport turtle1 onto turtle2
   (`ros2 topic echo /turtle2/pose --once` to get the target). Expect within
   ~1 s: `rescue_started` on the status topic, and
   `ros2 param get /turtlesim background_r/g/b` returning `255, 0, 0`.
   Then `ros2 topic echo /turtle2/pose` shows turtle2 tracking turtle1 pose
   for pose, confirming the teleport loop is live.
8. **SUCCESS:** teleport turtle1 to the start zone
   (`{x: 5.544444, y: 5.544444, theta: 0.0}`). Expect `rescue_complete` on the
   status topic, the background params back to `255, 255, 255`, and a
   `SUCCESS` log line with the rescue duration.
9. **Respawn:** within `respawn_delay_s` + 1 s, a second `spawn` log line
   appears, `/turtle2/pose` keeps publishing, and
   `ros2 param get /turtlesim background_r` is still 255 — confirming the
   kill-then-spawn path did not leave a stale third turtle and did not resurrect
   the rescue state. `ros2 topic list | grep pose` must show exactly
   `/turtle1/pose` and `/turtle2/pose`, with no extra `/turtleN/pose`.
10. **Parameters are real:** rerun the launch with
    `-p attach_distance:=0.1` and confirm the attach needs a closer approach;
    rerun spawner with `rng_seed:=7` twice and confirm identical spawn
    coordinates.
11. **Different pair, same binaries:** start a second spawner and manager with
    `victim_name:=turtle3 rescuer_name:=turtle2`. Expect distinct node names,
    distinct status topics, a second `/turtle3/pose` from a separate spawn, and
    the first pair's rescue still working. This is the constraint 2 and 3 test:
    the same executables, a different pair, no code change. Known limitation:
    both managers read and write the same global background params, so colours
    will interfere; only the topics and the rescue flow are being asserted here.
12. **Bad pair rejected:** run with `victim_name:=turtle1` (equal to the
    rescuer) and with `victim_name:="9bad"`. Expect a clear error log and
    non-zero exit within a second, not a node that spins against wrong topics.
13. **Clean build:** `rm -rf build install log` then
    `colcon build --packages-select rescue_turtle` produces no warnings, and
    `colcon test-result --verbose` is clean.

The human-only check stays the visual one: the background visibly turns red on
rescue and back to white on success, and the victim visibly tracks the rescuer.
Steps 7-9 prove the mechanism that causes it; the colour checks are done by
reading the parameters back, not by looking.

**Out of scope for Phase 1:** the rescuer node, rescue timeouts, the score
counter, and anything in the Open questions section.

**Also out of scope, per constraint 4:** the dispatcher, a list of pairs, dynamic
pair discovery or re-pairing at runtime, per-pair background colours, and any
fleet-wide status aggregation. Steps 11 and 12 prove the code tolerates a second
*manually started* pair; they are not a fleet.