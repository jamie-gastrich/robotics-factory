# Rescue Turtle Spec

## Goal
Built on stock turtlesim. Turtle1 rescues turtle2 and brings it back to the start zone. Logic prototype for a later Gazebo version.

## Phase 1: Manual driving, automatic game logic
- Keyboard: existing turtle_teleop_key.
- spawner: spawns "turtle2" at a random position (min distance from start zone) via /spawn; respawns after each rescue.
- rescue_manager: subscribes to both poses.
  - IDLE: distance(turtle1, turtle2) < attach_distance -> RESCUE; set background color (params) and call /clear.
  - RESCUE: turtle2 follows turtle1 via /turtle2/teleport_absolute.
  - Turtle2 in start zone -> SUCCESS: reset background, log, back to IDLE with a new turtle2.
- Parameters: attach_distance, start_zone bounds, rescue color, topic/service names.

## Phase 2: Autonomous
- rescuer node: SEEK -> RESCUE -> RETURN via Twist on /turtle1/cmd_vel; must reach the exact start position.

## Phase 3: Gazebo (later, separate project)

## Verification
- Topic checks: pose topics publish; turtle2 pose tracks turtle1 during RESCUE.
- Human visual check: background changes on rescue, resets on success.

## Open questions
- Timeout that fails a rescue?
- Score counter (topic or log)?