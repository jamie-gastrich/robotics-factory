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

"""
Startup checks on the two nodes' parameters, as functions over plain values.

Both nodes fail fast on a parameter combination that cannot work, so that a
mistyped threshold is one clear log line and a non-zero exit instead of a node
quietly misbehaving. The rules are here rather than in the node methods because
they are arithmetic on a handful of numbers: with no rclpy import they are
unit-testable without a ROS graph, which is the reason the rest of the pure
logic in this package is kept apart from the nodes in the first place.

Each function returns every problem it finds, in the order a node should report
them, and a node raises the first. Returning all of them keeps the function
testable on its own, which is the point.
"""

from .geometry import Box
from .geometry import canvas_has_room
from .geometry import in_zone

#: Lowest and highest value a background colour component can take.
COLOR_MIN = 0
COLOR_MAX = 255


def zone_errors(label: str, zone: Box) -> list[str]:
    """Return why a box cannot be a zone, empty when it can be one."""
    x_min, x_max, y_min, y_max = zone
    if x_min >= x_max or y_min >= y_max:
        return [f'{label} is empty: x [{x_min}, {x_max}], y [{y_min}, {y_max}]']
    return []


def spawner_configuration_errors(
    *,
    start: tuple[float, float],
    zone: Box,
    canvas: Box,
    min_spawn_distance: float,
    respawn_delay_s: float,
    service_wait_timeout_s: float,
    service_retry_period_s: float,
) -> list[str]:
    """Return every reason the spawner's parameters cannot work."""
    errors: list[str] = []
    if min_spawn_distance <= 0.0:
        errors.append(f'min_spawn_distance must be > 0, got {min_spawn_distance}')
    empty_zone = zone_errors('start zone', zone)
    errors.extend(empty_zone)
    start_x, start_y = start
    if not empty_zone and not in_zone(start_x, start_y, zone[0], zone[1], zone[2], zone[3]):
        errors.append(
            f'start zone x [{zone[0]}, {zone[1]}], y [{zone[2]}, {zone[3]}] does '
            f'not contain the start pose ({start_x}, {start_y})'
        )
    errors.extend(zone_errors('canvas', canvas))
    if not canvas_has_room(zone, canvas, min_spawn_distance):
        errors.append(
            f'canvas x [{canvas[0]}, {canvas[1]}], y [{canvas[2]}, {canvas[3]}] '
            f'lies entirely within {min_spawn_distance} m of the start zone: no '
            'spawn pose could ever be accepted'
        )
    if respawn_delay_s < 0.0:
        errors.append(f'respawn_delay_s must be >= 0, got {respawn_delay_s}')
    if service_wait_timeout_s <= 0.0:
        errors.append(
            f'service_wait_timeout_s must be > 0, got {service_wait_timeout_s}')
    if service_retry_period_s <= 0.0:
        errors.append(
            f'service_retry_period_s must be > 0, got {service_retry_period_s}')
    return errors


def manager_configuration_errors(
    *,
    attach_distance: float,
    follow_rate_hz: float,
    pose_timeout_s: float,
    service_wait_timeout_s: float,
    zone: Box,
    rescue_color: tuple[int, int, int],
    default_color: tuple[int, int, int],
) -> list[str]:
    """Return every reason the manager's parameters cannot work."""
    errors: list[str] = []
    if attach_distance <= 0.0:
        errors.append(f'attach_distance must be > 0, got {attach_distance}')
    if follow_rate_hz <= 0.0:
        errors.append(f'follow_rate_hz must be > 0, got {follow_rate_hz}')
    if pose_timeout_s <= 0.0:
        errors.append(f'pose_timeout_s must be > 0, got {pose_timeout_s}')
    if service_wait_timeout_s <= 0.0:
        errors.append(
            f'service_wait_timeout_s must be > 0, got {service_wait_timeout_s}')
    errors.extend(zone_errors('start zone', zone))
    errors.extend(color_errors('rescue', rescue_color))
    errors.extend(color_errors('default', default_color))
    return errors


def color_errors(label: str, color: tuple[int, int, int]) -> list[str]:
    """Return why a colour triple cannot be a background, empty when it can."""
    return [
        f'{label}_color component {component} is outside [{COLOR_MIN}, {COLOR_MAX}]'
        for component in color
        if not COLOR_MIN <= component <= COLOR_MAX
    ]
