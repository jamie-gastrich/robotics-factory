---
name: python-style
description: Python (rclpy) conventions, build, and test commands for ROS 2 packages
---
- PEP 8 with a 99-character line limit; see the ros2 skill for naming.
- Standard: ament_python packages, node classes inherit rclpy.node.Node, type hints.
- Register executables in setup.py under entry_points console_scripts.
- Declare parameters with declare_parameter; never hard-code topic names or rates.
- Log with self.get_logger(), not print().
- In main(): rclpy.init(), spin the node, and destroy_node()/rclpy.shutdown() in a finally block.
- Build: `colcon build --packages-select <pkg>` then `source install/setup.bash`.
- Test: `colcon test --packages-select <pkg>` then `colcon test-result --verbose` (pytest, plus ament_flake8 and ament_pep257).
- Match topic names, message types, and QoS with the C++ nodes they talk to.