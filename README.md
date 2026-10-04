# robotics-factory

> **Status: paused.** I've stopped active work here to focus on [`mower-sim`](https://github.com/jamie-gastrich/mower-sim), a simulated autonomous mower. This repo is where I learned ROS 2 fundamentals, and it stays as a record of that work. The workflow also changed: here, agents did most of the typing while I approved. In `mower-sim`, I write the code myself, with agents acting as a professor and a reviewer.

A ROS 2 workspace where I work out robot logic in simulation before it goes on
hardware. Each project is a small, complete, verified thing rather than a
tutorial fragment.

The rule I hold myself to: **a claim in this repo is either verified by a
command in it, or it is marked as not yet verified.** There is a third option I
try to avoid, which is writing something that sounds like it works.

## What's here

| Project | Version | State | What it is |
|---|---|---|---|
| [`rescue_turtle`](ros2_ws/src/rescue_turtle/README.md) | 1 done, 1.1 not started | paused | A turtlesim rescue game. You drive one turtle to a stranded one, and two nodes run the rules: attach, drag it home, score, respawn. |
| [`first_robot`](ros2_ws/src/first_robot) | 1 | done | The floor: a timer-driven publisher on `/heartbeat`, to prove the workspace, the build, and pub/sub mechanics. Closed as it stands; the specced subscriber was dropped rather than built. |

Neither project has been run on a robot. Both are simulation, deliberately, so
the logic can be changed quickly and tested without hardware. The port to
Gazebo was never started here; that work now happens in `mower-sim`.

## Quick start

```
cd ros2_ws
source /opt/ros/lyrical/setup.bash      # ROS 2 'lyrical'
colcon build
source install/setup.bash              # required in every new shell
```

Run `rescue_turtle` in two terminals, each sourcing first. The launch file
starts the turtlesim window itself, so do not start a second one:

```
ros2 launch rescue_turtle rescue_turtle.launch.py            # 1: window + game
ros2 run turtlesim turtle_teleop_key                         # 2: you drive
```

Which one you start first does not matter — teleop publishes `/turtle1/cmd_vel` whether or not turtlesim is up yet, and turtlesim subscribes when it starts. Put
the launch first anyway: otherwise keypresses before the window exists go
nowhere and read as a broken teleop. `turtle_teleop_key` must run in a real
terminal rather than in the background, since it puts the keyboard into raw
mode and aborts without a tty.

Test everything:

```
cd ros2_ws && source /opt/ros/lyrical/setup.bash
colcon test && colcon test-result --verbose
```

```
Summary: 89 tests, 0 errors, 0 failures, 1 skipped
```

The skip is `first_robot`'s `ament_copyright` check: its stub test files have no
licence headers yet. The 84 `rescue_turtle` tests run without a ROS graph at
all, because the logic does not import rclpy.

## The interesting problem in rescue_turtle

At the moment a rescue succeeds, the victim is still sitting on the rescuer.
The spawner has not respawned it yet. A plain `IDLE -> RESCUE` machine therefore
re-attaches on its very next 20 Hz tick, grabs the turtle that was just
returned home, and drags it straight back out. The game loops on one turtle and
never recovers.

The geometric fix does not work. "Release once they separate" is a condition
that is *already true* while holding, so it can never be what ends the hold. It
also only ever fires by luck: separation is reachable at all only when `attach_distance` is smaller than the distance a fresh victim spawns at, and
that is a legal parameter pair. Set `min_spawn_distance` below `attach_distance` and the game stops for good, with nothing in the log to
explain it.

What ships instead is a hold released by a predicate over the live victim pose
versus the pose recorded at success. The new turtle is a *different* turtle at a *different* place, so that condition can only become true after the respawn. The
decision is a pure function in `states.py`, so it is unit tested with no robot
in the loop. The geometric version latched after one rescue; this one ran 30
rescues in a row.

Full transcript of the shipped behaviour, captured headlessly:

```
rescue_manager: rescue started: the pair is 0.005 m apart, inside the 0.7 m attach distance
rescue_manager: SUCCESS: 'turtle2' reached the start zone at x=5.540 y=5.540 after 114.41 s
rescue_manager: holding IDLE until 'turtle2' has been replaced: a victim still on the
                rescuer is one the spawner has yet to respawn
spawner:       got 'rescue_complete', respawning in 1.0 s
spawner:       spawning 'turtle2' at x=8.181 y=4.506 theta=2.525 rad, 2.084 m clear of
                the start zone (minimum 2.0 m)
rescue_manager: releasing the post-success hold, the live victim is a different turtle
                from the rescued one; attaching again from now on
```

## How I worked here

This describes how this repo was built. It is a deliberate part of the repo,
not a wrapper around it. (`mower-sim` uses a different workflow: I write the
code myself and agents teach and review.)

**A plan gets written and approved before code exists.** Non-trivial work goes
into `<project>/docs/spec.md` first. The `rescue_turtle` spec records the
measured turtlesim facts the design depends on — actual pose publish rates,
actual start coordinates, actual service names — so the plan is argued from
what the system does, not from what the tutorial says.

**Logs are append-only.** `progress.md` and `docs/decisions.md` are never
rewritten. A decision that turned out wrong stays on the page next to the one
that replaced it, which is the only reason I can still tell you why a piece of
code looks the way it does.

**Decisions carry their reasons.** Every non-obvious choice is written down with
the alternative that was rejected and why. See [`docs/decisions.md`](docs/decisions.md) and the Decisions sections in each
project's `progress.md`.

**Logic is separated from ROS so it can be tested.** Name derivation, zone
containment, spawn sampling, the FSM and its hold predicate import no rclpy.
84 unit tests run with no graph, no window, and no timing. Only the thin node
wrapper touches ROS.

**Nothing is hard-coded.** Every topic, service, node name, distance and rate is
a parameter. `grep -rn "turtle1\|turtle2" rescue_turtle/` returns nothing, and
a second pair runs from the same binaries:

```
ros2 launch rescue_turtle rescue_turtle.launch.py rescuer_name:=turtle2 victim_name:=turtle3
```

That is not decoration. It is what makes the fleet version configuration instead
of a rewrite, and it is the reason the design is scoped to a `(rescuer, victim)` *pair* rather than to a role: no field anywhere means "the
rescuer", so two pairs on one machine cannot collide.

**No check here involves looking at a screen.** Nothing automated inspects a
GUI. Behaviour is read back through topics, services and parameters: the
background colour is asserted as a number, `background_g` being 0 while a
rescue runs and 255 otherwise. The one thing a machine cannot confirm is that
the window *looks* right, so I drove it myself and watched the background go
red on attach and white again on success.

**Agents did the typing, I did the approving.** Coding was delegated to a
subagent, a second one reviewed the diff and ran the tests, and a third wrote a
plain-language lesson to `docs/lessons/`. The workflow is in [`AGENTS.md`](AGENTS.md). It caught real bugs, and the constraint that every
agent must read `progress.md` before touching anything is why decisions stayed
consistent across sessions.

## Layout

```
ros2_ws/src/
  first_robot/          heartbeat publisher; the ROS 2 floor
  rescue_turtle/        the rescue game
docs/decisions.md       department-wide decisions, append-only
AGENTS.md               how work is planned, approved, delegated and committed
```

`rescue_turtle` has the full set. `first_robot` has `AGENTS.md` and `docs/spec.md` + `docs/progress.md`; its README and lessons are not written
yet, which is itself on the list below.

## Honest gaps

- **No CI.** Tests run locally via `colcon test`; there is no workflow running
  them on push yet.
- **No root LICENSE file.** Packages declare Apache-2.0 in `package.xml`, which
  is what `ament_copyright` checks, but the repository itself has no licence
  file.
- **Simulation only.** No Gazebo, no hardware, no C++ yet.
- **`first_robot` has no README or lesson.** `rescue_turtle` has both.
- **Paused.** `rescue_turtle` 1.1 and later versions are not being worked on.

## Environment

ROS 2 `lyrical` at `/opt/ros/lyrical`, Python 3.14, `ament_python` packages.

```
cd ros2_ws && colcon build --symlink-install && source install/setup.bash
```

Two things that cost me time and will cost you time if the docs do not say so:
sourcing is required in *every* new shell or `ros2 run` reports
"executable not found" even when the code is correct; and `pkill -f first_robot_node` hangs the shell, because `-f` matches the `pkill` command's own command line. Use a bracketed pattern: `pkill -f "first_robot[_]node"`.

## Versions

A version is a shipped state. Changes to what already shipped are numbered `1.1`, `1.2`, and so on, rather than inventing a new major version. `rescue_turtle` version 1 is shipped and verified; the changes I had in mind
for it are 1.1, and that work has not started. `first_robot` is closed at 1.

**Original roadmap (paused, kept for reference):** `rescue_turtle` 1.1, then version 2 (an autonomous `rescuer` node: seek, grab, return on `cmd_vel`), then version 3 (several rescuers and a
dispatcher). Active robotics work continues in [`mower-sim`](https://github.com/jamie-gastrich/mower-sim).
