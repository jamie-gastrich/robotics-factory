# Progress

## Session 1 — first ROS 2 node (timer logger, then publisher)

**Done**
- Relocated the package from `ros2_ws/first_robot/` to the conventional
  `ros2_ws/src/first_robot/`.
- Wrote `first_robot/first_robot_node.py`: a node that logs and publishes a
  heartbeat on a timer.
- Registered the `first_robot_node` console script in `setup.py`.
- Declared `rclpy` and `std_msgs` dependencies in `package.xml`; replaced the
  TODO description/license with a real one (Apache-2.0).
- Added a root `.gitignore` for colcon and Python artifacts.
- Filled in `ros2_ws/src/first_robot/AGENTS.md`; corrected the root
  `AGENTS.md` environment notes.

**Decisions**
- One node doing both publish and log, rather than a separate logger, to keep
  the first exercise focused on mechanics.
- Rate exposed as the `rate_hz` parameter (default 1.0) instead of a hardcoded
  period, so it is overridable at launch without a rebuild.
- Topic name is a module constant `HEARTBEAT_TOPIC = 'heartbeat'`.
- Caught `RCLError` in `main()`. A signal arriving inside the executor's
  blocking wait invalidates the context *after* the `rclpy.ok()` check, which
  otherwise produces an invalid-wait-set traceback on Ctrl-C.

**Verified**
- `colcon build --packages-select first_robot` — clean, no warnings.
- `ros2 node list` shows `/first_robot_node`; `ros2 topic list` shows
  `/heartbeat`; `ros2 topic type` reports `std_msgs/msg/String`.
- `ros2 topic hz /heartbeat` reports 1.000 Hz average.
- `--ros-args -p rate_hz:=4.0` correctly changes the rate.
- `colcon test --packages-select first_robot` — 5 tests, 0 failures,
  1 skipped (copyright, expected: the stub test files have no headers).

**Not done**
- Subscriber node. The publisher currently has no counterpart in-repo; it is
  only observed with `ros2 topic echo`.
- Nothing is committed yet: git has no `user.name`/`user.email` configured.
  The user chose to set this themselves.

**Next step**
- Write a subscriber node in a separate process, to show decoupled pub/sub:
  it imports nothing from the publisher and only needs to agree on the topic
  name and message type.
