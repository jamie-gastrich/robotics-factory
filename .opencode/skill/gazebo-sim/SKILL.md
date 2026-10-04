---
name: gazebo-sim
description: How to launch Gazebo simulations, bridge them to ROS 2, and verify that a simulated robot works
---
- Distro/Gazebo pairing: ROS 2 Jazzy + Gazebo Jetty (ros_gz installed via apt).
- Run a world: `gz sim -r <world>.sdf` (`-r` starts running immediately).
- Headless (no GUI, useful in WSL): `gz sim -s -r <world>.sdf`.
- Bridge topics to ROS 2 with ros_gz_bridge (parameter_bridge) or a ros_gz_sim launch file.
- Verify by echoing the bridged ROS 2 topics (`ros2 topic echo`), not by eyeballing the GUI.
- "Passing" means: sim starts without errors, expected topics publish at the expected rate, and the robot behaves as specified in the spec.
- Always shut down stray sim processes (`pkill -f gz`) before re-running.