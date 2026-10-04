---
name: cpp-style
description: C++ (rclcpp) conventions, build, and test commands for ROS 2 packages
---
- Follow the ROS 2 style guide (Google-based, 100-char lines); see the ros2 skill for naming.
- Standard: C++17, ament_cmake packages, node classes inherit rclcpp::Node.
- Use smart pointers (std::shared_ptr, std::unique_ptr); no raw new/delete.
- Declare parameters with declare_parameter; never hard-code topic names or rates.
- Log with RCLCPP_INFO/WARN/ERROR, not std::cout.
- Never block inside a callback; keep callbacks short.
- Link dependencies with ament_target_dependencies in CMakeLists.txt and list them in package.xml.
- Build: `colcon build --packages-select <pkg>` then `source install/setup.bash`.
- Test: `colcon test --packages-select <pkg>` then `colcon test-result --verbose` (gtest via ament_cmake_gtest).
- Match topic names, message types, and QoS with the Python nodes they talk to.