# Spec

Plans live here. Write the plan, get human approval, then implement.

## Task 1 — First ROS 2 node (COMPLETED)

**Goal:** Prove the workspace, the build, and `ros2 run` work end to end by
creating the smallest useful node.

**Plan (as approved):**
1. Move the package to `ros2_ws/src/first_robot/`.
2. Declare `rclpy` in `package.xml`.
3. Write a node with a timer callback that logs a counter.
4. Register it as a `console_scripts` entry point.
5. Build, source, run, confirm it appears in `ros2 node list`.
6. Make `colcon test` pass (the package ships lint tests: copyright, flake8,
   mypy, pep257, xmllint).

**Outcome:** Done. See docs/progress.md.

**Design notes:**
- Node named `first_robot_node`, one class `FirstRobotNode(Node)`.
- Canonical lifecycle: `rclpy.init()` → create node → spin → destroy → shutdown.
- Shutdown path catches `RCLError` as well as `KeyboardInterrupt` and
  `ExternalShutdownException`, because a signal can land inside the
  executor's blocking wait set construction, after the `rclpy.ok()` check.

## Task 2 — Heartbeat publisher (COMPLETED)

**Goal:** Introduce topics, message types, and QoS by publishing on one.

**Plan (as approved):**
1. Add `std_msgs` dependency.
2. Create a `std_msgs/msg/String` publisher on `/heartbeat`.
3. Publish a counter from the existing timer callback.
4. Verify with `ros2 topic list`, `ros2 topic type`, `ros2 topic echo`.

**Outcome:** Done. See docs/progress.md.

**Design notes:**
- Rate is the `rate_hz` parameter, default 1.0, so it is tunable at launch.
- Default QoS (KEEP_LAST depth 10, RELIABLE, VOLATILE) was used. Deeper QoS
  tuning is deferred until a real reliability problem forces the question.

## Task 3 — Heartbeat subscriber (PENDING APPROVAL)

**Goal:** Demonstrate that publisher and subscriber are fully decoupled.

**Plan:**
1. New module `first_robot/heartbeat_subscriber.py` with its own `main()`,
   registered as a second console script.
2. Subscribe to `/heartbeat` with the same `std_msgs/msg/String` type, log
   each message received.
3. Start publisher and subscriber as two separate processes; confirm messages
   flow using `ros2 topic info -v` (publisher count 1, subscription count 1).
4. Stop the subscriber while the publisher keeps running, then restart it, to
   show that messages published while absent are dropped rather than queued.

**Note:** The subscriber must not import anything from the publisher, and
must not hardcode a node name into the topic. It only needs to agree on the
topic name and the message type.
