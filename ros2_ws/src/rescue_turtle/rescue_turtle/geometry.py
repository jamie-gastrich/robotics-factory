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
Pure geometry helpers for the rescue game.

No rclpy import: the zone arithmetic and the spawn rejection sampling are
tested directly, with no ROS graph in the way.
"""

import math
import random

#: How many candidate poses rejection sampling tries before giving up.
DEFAULT_MAX_ATTEMPTS = 1000

#: Two radians, so a random heading is not near-identical to zero.
TAU = 2.0 * math.pi

#: An axis-aligned box, as ``(x_min, x_max, y_min, y_max)``.
Box = tuple[float, float, float, float]

#: A point in the plane.
Point = tuple[float, float]

#: A rectangle in canvas pixels, as ``(x, y, width, height)``: Qt's own argument
#: order, so it is what the overlay's painting wants. The values are floats and
#: both ``QRect`` and ``setGeometry`` take ints, so a caller hands them to Qt
#: rounded; :meth:`rescue_turtle.safe_zone.SafeZoneNode._place_overlay` does.
#: Deliberately the same shape as :data:`Box` rather than a distinct type: the two
#: are then interchangeable as far as mypy is concerned, so passing a metre box
#: where pixels are wanted is a mistake a reader can see at the call site, and a
#: separate type would have to be threaded through every caller to say the same
#: thing more slowly.
PixelRect = tuple[float, float, float, float]


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Return the Euclidean distance between two points."""
    return math.hypot(x2 - x1, y2 - y1)


def in_zone(
    x: float,
    y: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> bool:
    """Return whether a point lies inside the axis-aligned zone, edges included."""
    return x_min <= x <= x_max and y_min <= y <= y_max


def distance_to_zone(
    x: float,
    y: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
) -> float:
    """
    Return the distance from a point to the nearest point of the zone.

    Zero inside the zone, and the distance to the closest edge outside it.
    """
    nearest_x = min(max(x, x_min), x_max)
    nearest_y = min(max(y, y_min), y_max)
    return math.hypot(x - nearest_x, y - nearest_y)


def world_to_pixel(
    x: float,
    y: float,
    *,
    world_width_m: float,
    world_height_m: float,
    canvas_width_px: float,
    canvas_height_px: float,
) -> Point:
    """
    Return a world position as a pixel position on the canvas.

    World y points up and screen y points down, so the row is measured down
    from the top of the canvas. That flip is the whole reason this is a
    function with a unit test on it rather than an expression written inline
    where it cannot be checked.

    Both the world extent and the canvas size must be positive; callers check
    that in :mod:`rescue_turtle.validation` before any of this is called.
    """
    return (
        x * canvas_width_px / world_width_m,
        canvas_height_px - y * canvas_height_px / world_height_m,
    )


def zone_to_pixel_rect(
    zone: Box,
    *,
    world_width_m: float,
    world_height_m: float,
    canvas_width_px: float,
    canvas_height_px: float,
) -> PixelRect:
    """
    Return the pixel rectangle a world zone occupies on the canvas.

    The zone's top left corner in world terms is ``(x_min, y_max)``, because
    world y is up, and that is the top left of the rectangle on screen. Width
    and height then come out positive for any zone that is not inverted, which
    Qt requires.

    The two axes are mapped independently, so a canvas that is not square, or a
    world that is not, is handled by passing its own extents rather than by
    assuming one scale.
    """
    x_min, x_max, y_min, y_max = zone
    left, top = world_to_pixel(
        x_min, y_max,
        world_width_m=world_width_m,
        world_height_m=world_height_m,
        canvas_width_px=canvas_width_px,
        canvas_height_px=canvas_height_px,
    )
    right, bottom = world_to_pixel(
        x_max, y_min,
        world_width_m=world_width_m,
        world_height_m=world_height_m,
        canvas_width_px=canvas_width_px,
        canvas_height_px=canvas_height_px,
    )
    return (left, top, right - left, bottom - top)


def canvas_has_room(zone: Box, canvas: Box, min_distance: float) -> bool:
    """
    Return whether any canvas corner is far enough from the zone to spawn on.

    A box is entirely inside the exclusion region exactly when all four of its
    corners are, so the corners decide whether a spawn is possible at all. It
    is a necessary condition, not a guarantee: rejection sampling can still run
    out of attempts and say so.
    """
    x_min, x_max, y_min, y_max = zone
    for x in (canvas[0], canvas[1]):
        for y in (canvas[2], canvas[3]):
            if distance_to_zone(x, y, x_min, x_max, y_min, y_max) >= min_distance:
                return True
    return False


def random_spawn_pose(
    rng: random.Random,
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    min_distance: float,
    canvas_x_min: float,
    canvas_x_max: float,
    canvas_y_min: float,
    canvas_y_max: float,
    random_theta: bool = True,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> tuple[float, float, float]:
    """
    Return a random ``(x, y, theta)`` at least ``min_distance`` from the zone.

    Uses rejection sampling: draw a pose on the canvas, keep it when it is far
    enough from the start zone, otherwise draw again. ``min_distance`` is
    measured from the nearest point of the zone, not from its centre, so a
    victim cannot spawn just outside the goal.

    :raises RuntimeError: if no acceptable pose was found in ``max_attempts``
        draws, which means the canvas and the minimum distance disagree.
    """
    for _ in range(max_attempts):
        x = rng.uniform(canvas_x_min, canvas_x_max)
        y = rng.uniform(canvas_y_min, canvas_y_max)
        if distance_to_zone(x, y, x_min, x_max, y_min, y_max) < min_distance:
            continue
        theta = rng.uniform(0.0, TAU) if random_theta else 0.0
        return x, y, theta
    raise RuntimeError(
        f'no spawn pose at least {min_distance} m from the start zone found in '
        f'{max_attempts} attempts'
    )
