# first_robot

## Purpose
First test project for the factory: a heartbeat publisher (and, next, a
subscriber) to prove the ROS 2 workspace and agent workflow. Grows into the
starter point for publisher/subscriber exercises.

## Layout
- Package: first_robot (ament_python, pure Python, no CMake)
- Nodes:
  - `first_robot_node` (`first_robot/first_robot_node.py`) — exists. Timer-driven
    publisher, logs and publishes each heartbeat.
  - subscriber node — NOT YET WRITTEN.
- Topics: `/heartbeat`, type `std_msgs/msg/String`, default 1.0 Hz
  - Rate is a parameter: `rate_hz` (default 1.0), override at launch with
    `--ros-args -p rate_hz:=4.0`
  - Publisher QoS: `KEEP_LAST` depth 10, RELIABLE, VOLATILE (rclpy default)
- Parameters: `rate_hz` (float, default 1.0)

## Build and run
cd ~/robotics-factory/ros2_ws
colcon build --packages-select first_robot
source install/setup.bash
ros2 run first_robot first_robot_node
ros2 run first_robot first_robot_node --ros-args -p rate_hz:=4.0
Verify with: ros2 topic echo /heartbeat
Check rate with: ros2 topic hz /heartbeat

## Definition of done
- Package builds with no warnings.
- Topic publishes at the expected rate (check with `ros2 topic hz /heartbeat`).
- Tests pass: `colcon test --packages-select first_robot`.

## Gotchas
- `source install/setup.bash` is required in every new shell, or `ros2 run`
  reports "executable not found" even when the code is correct.
- Messages published while no subscriber exists are dropped, not buffered.
  `ros2 topic echo` may start partway through the counter; that is expected.
- `pkill -f first_robot_node` hangs a shell, because `-f` matches the pkill
  command's own command line. Use a bracketed pattern: `pkill -f
  "first_robot[_]node"`.
- The node catches `RCLError` on purpose: a SIGTERM can land inside the
  executor's blocking wait, after the `rclpy.ok()` check, and would otherwise
  raise an invalid-wait-set traceback.

## Project constraints
- Python only for now, no Gazebo yet.
- Plan lives in docs/spec.md, log in docs/progress.md.
- ROS 2 distro `lyrical`, Python 3.14.
- Apache-2.0 license; source files need the copyright header for
  `ament_copyright`.

## Current status
See docs/progress.md.
