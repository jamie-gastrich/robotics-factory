# Robotics Department
ROS 2, C++, Python, Gazebo. Workspace: ros2_ws/. Each project lives in ros2_ws/src/<project>/.

## Workflow
1. Ask which project the task belongs to if it isn't clear.
2. For any non-trivial task, write the plan to <project>/docs/spec.md and STOP for human approval.
3. After approval, delegate coding to @implementer, then have @reviewer check it.
4. Commit after each approved task.
5. At the end of a task, append to <project>/docs/progress.md: done, decisions, next step.
6. After a task is committed, ask @professor to write a lesson to <project>/docs/lessons/.

## Rules
- Never overwrite progress.md or decisions.md; append only.
- Department-wide decisions go in docs/decisions.md at this root.
- Load skills (ros2, cpp-style, python-style, gazebo-sim) when relevant.
  NOTE: none of these skill directories exist yet; don't assume a skill is
  available — check first and proceed without it if missing.
- At the start of a session, read <project>/docs/progress.md before doing anything.

## Environment
- ROS 2 distro `lyrical` at /opt/ros/lyrical, Python 3.14.
- Build: cd ros2_ws && colcon build --symlink-install, then
  source install/setup.bash in the same shell. Sourcing is required in every
  new shell or `ros2 run` cannot find built executables.
- `build/`, `install/`, and `log/` are generated and gitignored; delete them
  freely to force a clean rebuild.
- One shell is one environment. Backgrounded nodes die with the shell that
  started them unless detached (e.g. `setsid`).
