# rescue_turtle

## Purpose
Rescue Turtle2: built on stock turtlesim (never modify turtlesim itself). Turtle1 rescues turtle2 and brings it back to the start zone. Prototype of the logic for a later Gazebo project.

## Layout
- Package: rescue_turtle (ament_python), depends on the installed turtlesim.
- Nodes: spawner, rescue_manager (Phase 1); rescuer (Phase 2).
- Interfaces: /turtle1/pose, /turtle2/pose, /turtle1/cmd_vel, services /spawn, /clear, /turtle2/teleport_absolute; turtlesim params background_r/g/b.
- Skills that apply: ros2, python-style, turtlesim.

## Build and run
cd ~/robotics-factory/ros2_ws
colcon build --packages-select rescue_turtle
source install/setup.bash
ros2 run turtlesim turtlesim_node                    # terminal 1
ros2 run turtlesim turtle_teleop_key                 # terminal 2
ros2 launch rescue_turtle rescue_turtle.launch.py    # terminal 3 (once it exists)

## Definition of done (Phase 1)
- Package builds with no warnings; `colcon test --packages-select rescue_turtle` passes.
- Topic/service names and thresholds are parameters, not hard-coded.
- Launch file exists and is installed via setup.py data_files.
- Agents verify via `ros2 topic echo` / `ros2 service call` (they cannot see the GUI); the human does the visual check.

## Project constraints
- Python only. No Gazebo. Plan lives in docs/spec.md, log in docs/progress.md.