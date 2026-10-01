# Version 1: manual driving, automatic game logic

Date: 2026-09-30. Package `rescue_turtle`. Commit `a6c1466`.

## 1. Core concepts

1. **Parameterization** - the settings that change go in as inputs, never typed
   into the code.
2. **Separation of concerns** - one job per file or node, so each part can be
   trusted on its own.
3. **Pure vs impure** - the math goes in a function that touches no ROS, so you
   can test it without a robot.
4. **Pair-scope, not role-scope** - name things after the *pair* they belong to,
   not the job they do.
5. **State must outlast a restart** - when something must stay remembered after a
   change, code that state explicitly.

## 2. What we built

A turtlesim game. You drive one turtle with the keyboard. When you get close to
the other turtle it sticks to you and the screen turns red. Bring it to the start
zone, the screen turns white, and a new turtle appears far away.

Two nodes do the thinking. `spawner` owns the new turtle's life. `rescue_manager`
owns the two states, waiting and rescuing. You drive; the game plays itself.

## 3. The concepts explained

### Parameterization

Everything that could be different lives in a parameter: the turtle names, the
how-close-is-close-enough distance, the timer rate. Code should never say
`turtle1` out loud. If it does, changing the name means editing code. If the name
is a parameter, changing it means passing one word on the command line.

### Separation of concerns

The spawner never decides when a rescue starts. The manager never creates
turtles. They talk on one channel, a status topic for that pair. When two jobs
share one job, a bug in one shows up as a bug in the other.

### Pure vs impure

Pure function: same inputs, same output, touches nothing outside itself.
Impure: talks to a robot. The distance math and the "is the hold over" question
are pure, so they are unit-tested with no ROS graph running at all. Only the thin
node wrapper is impure.

### Pair-scope, not role-scope

A role name says "this turtle is the rescuer". A pair name says "these two
turtles, together, are one rescue". Pair-scope means no field ever means "the
rescuer", and two pairs on one machine cannot collide. Version 3 wants several
   pairs, so this is the whole point of Version 1.

### State must outlast a restart

At success the victim is still sitting on the rescuer. If the manager went
straight back to waiting, it would grab the new turtle instantly and drag it back
out. So the manager holds a short memory: *a new turtle is coming*. The hold has
to end on something true after the restart, not on a shape that is true while
holding. "They moved apart" is true while holding, so it never ends. "The live
pose is not the pose we saved at success" is only true after the new turtle
arrives.

### Verify through the interface

Nothing here was checked by looking at the window. It was checked by reading
topics, parameters and test output. The colour was read as a number, so the human
visual check is still open.

## 4. Key words

- **Parameter** - a setting read at startup. All names and thresholds live here.
- **Concern** - one job. Splitting jobs up is splitting concerns.
- **Pure function** - a function that only uses its arguments and returns a
  value. Nothing else. Testable with no robot.
- **Impure** - a function that reads the world or talks to a robot.
- **FSM (finite state machine)** - a thing that is in exactly one of a few named
  states, with rules for moving between. Here: `IDLE` and `RESCUE`.
- **Pair-scoped** - named after the pair, so two pairs never collide.
- **Latching** - a condition that never goes false, so the code sticks in it.

## 5. How this connects to bigger ideas

Version 3 is a fleet: several rescuer turtles plus a dispatcher. Because of these
concepts that is configuration, not a rewrite.

## 6. Say it in an interview

- I built a turtlesim rescue game where I drive the rescuer and two nodes run the
  game logic: a spawner that owns the victim's life and a manager that runs a
  two-state machine for one rescuer-victim pair.
- Every name and threshold is a parameter, so a second pair is a different
  `ros2 launch` line instead of a code change.
- The manager owns a *pair* rather than a role, which is what lets several pairs
  run side by side without colliding.
- The distance math and the state rules are pure functions with no rclpy import,
  so they are unit-tested without a running ROS graph.
- The interesting bug was state that has to survive a restart: at success the
  victim is still on the rescuer, so my first release condition raced with the
  respawn and locked the game after one rescue.

## 7. Quick check

1. Why does a new victim spawn far from the start zone, and what would go wrong
   if it spawned close?

**Answers**

1. Because `min_spawn_distance` (2.0 m) is larger than `attach_distance` (0.7 m).
If it spawned inside 0.7 m it would attach instantly, and the loop would repeat
every `respawn_delay_s`. Nothing stops that: the two numbers live in two
different nodes and neither can see the other.