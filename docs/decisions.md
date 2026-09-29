# Decisions

Department-wide decisions. Append only; do not overwrite.

## 2026-09-29 — Packages live in `ros2_ws/src/<project>/`
The `first_robot` package was generated at `ros2_ws/first_robot/`, outside
`src/`. Moved to `ros2_ws/src/first_robot/` before any code was written.
`colcon` would have discovered it either way, but every ROS 2 tutorial, and
the root `AGENTS.md`, assume the `src/` layout. Keep new packages there.

## 2026-09-29 — Apache-2.0 as the default package license
The generated `package.xml` shipped with `<license>TODO: License declaration`.
Set to Apache-2.0, matching the ROS 2 ecosystem default. Required for
`ament_copyright` to pass, since it checks source headers against the
declared license.

## 2026-09-29 — Referenced skills are not yet available
The root `AGENTS.md` instructs loading `ros2`, `cpp-style`, `python-style`,
and `gazebo-sim` skills. None of these directories exist locally or
globally. Root `AGENTS.md` now notes this so future agents check before
relying on them. `@implementer` and `@reviewer` do exist in
`~/.config/opencode/agent/`, so the delegation step in the workflow is
usable today.
