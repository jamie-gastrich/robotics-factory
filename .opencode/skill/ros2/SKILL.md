---
name: ros2
description: ROS 2 workspace layout, build/run commands, naming conventions, and code style standards
---
## Workflow
- Workspace: src/ holds packages; build with `colcon build`, then `source install/setup.bash`.
- Inspect: `ros2 topic list`, `ros2 topic echo <topic>`, `ros2 topic hz <topic>`, `ros2 node list`.

## Naming (ROS 2 Developer Guide)
- Packages, nodes, topics, services, actions, parameters: lowercase snake_case (e.g. `first_robot`, `/heartbeat`).
- Namespaces are separated by `/`; use `~/` for node-private names.
- Interface types are CamelCase (e.g. `std_msgs/msg/String`, `MyCustomMsg.msg`).
- C++ files: snake_case with .cpp/.hpp. Classes: CamelCase. Functions and variables: snake_case; class member variables end with a trailing underscore.

## Code style
- C++ follows the ROS 2 style guide, which is based on Google C++ style with modifications (notably a 100-character line limit).
- Python follows PEP 8 with a 99-character line limit.

## Linting
- Add `ament_lint_auto` and `ament_lint_common` as test dependencies in package.xml so `colcon test` checks style automatically (ament_uncrustify, ament_cpplint, ament_flake8, ament_pep257).