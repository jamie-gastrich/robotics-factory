# Copyright 2026 jamie
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""First ROS 2 node: logs a heartbeat from a timer."""

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class FirstRobotNode(Node):
    """A minimal node that logs a counter on a fixed-rate timer."""

    def __init__(self) -> None:
        """Create the node and start the heartbeat timer."""
        super().__init__('first_robot_node')
        self.declare_parameter('rate_hz', 1.0)
        self._rate_hz = float(self.get_parameter('rate_hz').value)
        self._count = 0
        self.get_logger().info(
            f'first_robot_node started at {self._rate_hz} Hz'
        )
        self._timer = self.create_timer(1.0 / self._rate_hz, self._on_timer)

    def _on_timer(self) -> None:
        """Log one heartbeat. Called by the executor on each timer expiry."""
        self._count += 1
        self.get_logger().info(f'heartbeat {self._count}')


def main(args: list[str] | None = None) -> None:
    """Run the node until interrupted."""
    rclpy.init(args=args)
    node = FirstRobotNode()
    try:
        while rclpy.ok():
            rclpy.spin_once(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        # A signal can arrive inside the blocking wait, invalidating the
        # context after the rclpy.ok() check above. Treat it as shutdown.
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
