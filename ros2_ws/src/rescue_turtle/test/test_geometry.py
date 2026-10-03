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
Unit tests for the pure geometry helpers.

No ROS graph is needed: the module under test imports no rclpy and no Qt. The
world-to-pixel helpers are here for the same reason as the rest: the y flip, from
a world whose y points up to a canvas whose y points down, is the arithmetic the
safe zone overlay is placed by, and it is checked here rather than by eye.
"""

import math
import random

import pytest

from rescue_turtle.geometry import DEFAULT_MAX_ATTEMPTS
from rescue_turtle.geometry import distance
from rescue_turtle.geometry import distance_to_zone
from rescue_turtle.geometry import in_zone
from rescue_turtle.geometry import random_spawn_pose
from rescue_turtle.geometry import world_to_pixel
from rescue_turtle.geometry import zone_to_pixel_rect

# The measured start zone and world of a stock turtlesim window: the walls are at
# 11.088889 m, and the canvas over them is 500 px square.
ZONE = (4.944, 6.144, 4.944, 6.144)
CANVAS = (0.0, 11.088889, 0.0, 11.088889)
MIN_SPAWN_DISTANCE = 2.0

#: The measured canvas, in the units the overlay works in.
WORLD_WIDTH_M = 11.088889
WORLD_HEIGHT_M = 11.088889
CANVAS_WIDTH_PX = 500.0
CANVAS_HEIGHT_PX = 500.0

#: The scale those two numbers give: 45.0902 px/m, so the 1.2 m start zone is
#: 54.11 px across, which is 10.8% of the canvas.
PX_PER_M = CANVAS_WIDTH_PX / WORLD_WIDTH_M
ZONE_WIDTH_M = ZONE[1] - ZONE[0]
ZONE_HEIGHT_M = ZONE[3] - ZONE[2]

#: Where turtlesim spawns the first turtle, and therefore the middle of the
#: canvas, because the world is square and the spawn point is its centre.
SPAWN_X = 5.544444
SPAWN_Y = 5.544444


def test_distance_is_the_euclidean_gap() -> None:
    """A 3-4-5 triangle, the classic way to pin a distance function down."""
    assert distance(0.0, 0.0, 3.0, 4.0) == pytest.approx(5.0)
    assert distance(1.0, 1.0, 1.0, 1.0) == pytest.approx(0.0)
    assert distance(-2.0, 0.5, 2.0, 0.5) == pytest.approx(4.0)


def test_in_zone_includes_every_edge_and_corner() -> None:
    """The zone is closed, so a victim exactly on a boundary has arrived."""
    x_min, x_max, y_min, y_max = ZONE
    assert in_zone(5.544444, 5.544444, x_min, x_max, y_min, y_max)
    for x, y in ((x_min, y_min), (x_max, y_max), (x_min, y_max), (x_max, y_min)):
        assert in_zone(x, y, x_min, x_max, y_min, y_max)
    assert in_zone(x_min, 5.5, x_min, x_max, y_min, y_max)
    assert in_zone(x_max, 5.5, x_min, x_max, y_min, y_max)


def test_in_zone_excludes_just_outside() -> None:
    """One float-step outside an edge is not inside, on any of the four sides."""
    x_min, x_max, y_min, y_max = ZONE
    step = 1e-6
    for x, y in (
        (x_min - step, 5.5),
        (x_max + step, 5.5),
        (5.5, y_min - step),
        (5.5, y_max + step),
    ):
        assert not in_zone(x, y, x_min, x_max, y_min, y_max)


def test_in_zone_of_an_inverted_box_is_empty() -> None:
    """A mis-ordered zone contains nothing rather than everything."""
    assert not in_zone(5.0, 5.0, 6.0, 4.0, 6.0, 4.0)


def test_distance_to_zone_is_zero_inside() -> None:
    """Every interior point, including the edges, is zero from the zone."""
    x_min, x_max, y_min, y_max = ZONE
    for x, y in ((5.5, 5.5), (x_min, y_min), (x_max, y_max)):
        assert distance_to_zone(x, y, x_min, x_max, y_min, y_max) == 0.0


def test_distance_to_zone_measures_from_the_nearest_point() -> None:
    """Outside the box the distance is to the closest edge, not the centre."""
    x_min, x_max, y_min, y_max = ZONE
    assert distance_to_zone(x_min - 0.5, 5.5, x_min, x_max, y_min, y_max) == \
        pytest.approx(0.5)
    assert distance_to_zone(5.5, y_max + 2.0, x_min, x_max, y_min, y_max) == \
        pytest.approx(2.0)
    # A corner measures both offsets at once.
    assert distance_to_zone(x_min - 3.0, y_min - 4.0, x_min, x_max, y_min, y_max) == \
        pytest.approx(5.0)


def test_random_spawn_pose_stays_on_canvas_and_clear_of_the_zone() -> None:
    """Every sampled pose is on the canvas and far enough from the zone."""
    x_min, x_max, y_min, y_max = ZONE
    canvas_x_min, canvas_x_max, canvas_y_min, canvas_y_max = CANVAS
    rng = random.Random(0)
    for _ in range(200):
        x, y, theta = random_spawn_pose(
            rng,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            min_distance=MIN_SPAWN_DISTANCE,
            canvas_x_min=canvas_x_min,
            canvas_x_max=canvas_x_max,
            canvas_y_min=canvas_y_min,
            canvas_y_max=canvas_y_max,
        )
        assert canvas_x_min <= x <= canvas_x_max
        assert canvas_y_min <= y <= canvas_y_max
        margin = distance_to_zone(x, y, x_min, x_max, y_min, y_max)
        assert margin >= MIN_SPAWN_DISTANCE
        assert 0.0 <= theta < 2.0 * math.pi


def test_random_spawn_pose_without_random_theta_points_along_x() -> None:
    """With random headings off, the theta argument is what decides."""
    rng = random.Random(1)
    _, _, theta = random_spawn_pose(
        rng,
        x_min=ZONE[0],
        x_max=ZONE[1],
        y_min=ZONE[2],
        y_max=ZONE[3],
        min_distance=MIN_SPAWN_DISTANCE,
        canvas_x_min=CANVAS[0],
        canvas_x_max=CANVAS[1],
        canvas_y_min=CANVAS[2],
        canvas_y_max=CANVAS[3],
        random_theta=False,
    )
    assert theta == 0.0


def test_a_seeded_rng_makes_spawns_reproducible() -> None:
    """The same seed replays the same poses, which is what the rng_seed knob is for."""
    def poses(seed: int) -> list[tuple[float, float, float]]:
        rng = random.Random(seed)
        return [
            random_spawn_pose(
                rng,
                x_min=ZONE[0],
                x_max=ZONE[1],
                y_min=ZONE[2],
                y_max=ZONE[3],
                min_distance=MIN_SPAWN_DISTANCE,
                canvas_x_min=CANVAS[0],
                canvas_x_max=CANVAS[1],
                canvas_y_min=CANVAS[2],
                canvas_y_max=CANVAS[3],
            )
            for _ in range(5)
        ]

    assert poses(7) == poses(7)
    assert poses(7) != poses(8)


def test_sampling_gives_up_when_the_canvas_is_all_exclusion() -> None:
    """A canvas entirely inside the minimum distance can never yield a pose."""
    with pytest.raises(RuntimeError, match='no spawn pose'):
        random_spawn_pose(
            random.Random(0),
            x_min=ZONE[0],
            x_max=ZONE[1],
            y_min=ZONE[2],
            y_max=ZONE[3],
            min_distance=MIN_SPAWN_DISTANCE,
            canvas_x_min=ZONE[0],
            canvas_x_max=ZONE[1],
            canvas_y_min=ZONE[2],
            canvas_y_max=ZONE[3],
            max_attempts=5,
        )


def test_sampling_with_no_attempts_always_gives_up() -> None:
    """The attempt budget is a bound, so zero attempts cannot succeed."""
    with pytest.raises(RuntimeError, match='0 attempts'):
        random_spawn_pose(
            random.Random(0),
            x_min=ZONE[0],
            x_max=ZONE[1],
            y_min=ZONE[2],
            y_max=ZONE[3],
            min_distance=MIN_SPAWN_DISTANCE,
            canvas_x_min=CANVAS[0],
            canvas_x_max=CANVAS[1],
            canvas_y_min=CANVAS[2],
            canvas_y_max=CANVAS[3],
            max_attempts=0,
        )


def test_the_default_attempt_budget_is_finite() -> None:
    """The default is a number, not a silent infinite loop."""
    assert 0 < DEFAULT_MAX_ATTEMPTS < 100000


# --------------------------------------------------------------- world to pixel


def test_world_to_pixel_maps_the_near_origin_to_the_bottom_left() -> None:
    """The origin of the world is the bottom left of the canvas, not the top."""
    assert world_to_pixel(
        0.0, 0.0,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((0.0, CANVAS_HEIGHT_PX))


def test_world_to_pixel_flips_y() -> None:
    """
    The world y axis points up and the screen one points down.

    This is the whole reason the helper is tested: with the flip missing the
    marker would be drawn at the mirror image of the start zone, which is the
    middle of the canvas on a symmetric zone and therefore hard to see by eye.
    """
    top = world_to_pixel(
        WORLD_WIDTH_M, WORLD_HEIGHT_M,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    bottom = world_to_pixel(
        WORLD_WIDTH_M, 0.0,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert top == pytest.approx((CANVAS_WIDTH_PX, 0.0))
    assert bottom == pytest.approx((CANVAS_WIDTH_PX, CANVAS_HEIGHT_PX))
    # Three quarters of the way up the world is a quarter of the way down the
    # canvas, so up on the left is down on the screen.
    upper = world_to_pixel(
        0.0, WORLD_HEIGHT_M * 0.75,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert upper == pytest.approx((0.0, CANVAS_HEIGHT_PX * 0.25))


def test_world_to_pixel_maps_the_far_corner_to_the_top_right() -> None:
    """Both axes reach the far edge, so the whole world is covered exactly."""
    assert world_to_pixel(
        WORLD_WIDTH_M, WORLD_HEIGHT_M,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((CANVAS_WIDTH_PX, 0.0))


def test_world_to_pixel_maps_the_world_centre_to_the_canvas_centre() -> None:
    """A square world over a square canvas has the same centre in both."""
    assert world_to_pixel(
        WORLD_WIDTH_M / 2.0, WORLD_HEIGHT_M / 2.0,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((CANVAS_WIDTH_PX / 2.0, CANVAS_HEIGHT_PX / 2.0), abs=0.001)


def test_the_rescuer_spawn_point_is_the_centre_of_the_canvas() -> None:
    """
    The measured start pose is the centre pixel, which is what centres the marker.

    The world is a square and 11.088889 / 2 is 5.5444445, the pose turtlesim
    spawns the first turtle at, so the "same coordinates as the rescuer spawns
    at" that the overlay is asked for is the centre of the canvas.
    """
    assert world_to_pixel(
        SPAWN_X, SPAWN_Y,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((CANVAS_WIDTH_PX / 2.0, CANVAS_HEIGHT_PX / 2.0), abs=0.001)


def test_world_to_pixel_maps_the_two_axes_independently() -> None:
    """A canvas that is not square, or a world that is not, still fills exactly."""
    assert world_to_pixel(
        2.0, 3.0,
        world_width_m=4.0, world_height_m=6.0,
        canvas_width_px=400.0, canvas_height_px=150.0,
    ) == pytest.approx((200.0, 75.0))


# --------------------------------------------------------------- zone to pixel


def test_zone_to_pixel_rect_is_the_measured_size_and_centre() -> None:
    """
    The 1.2 m start zone is 54.11 px, centred on the spawn point.

    The zone's centre is 5.544 m and the world's is 5.5444445, so the two are
    half a thousandth of a metre apart and the rectangle's centre lands within
    0.03 px of the canvas centre rather than exactly on it.
    """
    left, top, width, height = zone_to_pixel_rect(
        ZONE,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert width == pytest.approx(ZONE_WIDTH_M * PX_PER_M, abs=0.01)
    assert height == pytest.approx(ZONE_HEIGHT_M * PX_PER_M, abs=0.01)
    assert width == pytest.approx(54.11, abs=0.01)
    assert (left + width / 2.0) == pytest.approx(CANVAS_WIDTH_PX / 2.0, abs=0.05)
    assert (top + height / 2.0) == pytest.approx(CANVAS_HEIGHT_PX / 2.0, abs=0.05)


def test_zone_to_pixel_rect_puts_the_near_zone_at_the_bottom_of_the_canvas() -> None:
    """A zone in the corner of the world lands in the opposite corner of the canvas."""
    side = 1.2
    left, top, width, height = zone_to_pixel_rect(
        (0.0, side, 0.0, side),
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert left == pytest.approx(0.0)
    assert width == pytest.approx(side * PX_PER_M, abs=0.01)
    # Below, not above: the flip again, on a zone where it is unmistakable.
    assert top == pytest.approx(CANVAS_HEIGHT_PX - side * PX_PER_M)
    assert height == pytest.approx(side * PX_PER_M, abs=0.01)


def test_zone_to_pixel_rect_puts_the_far_zone_at_the_top_of_the_canvas() -> None:
    """The same size of zone against the far walls is at the top, and still flush."""
    far_min = WORLD_WIDTH_M - 1.2
    left, top, width, height = zone_to_pixel_rect(
        (far_min, WORLD_WIDTH_M, far_min, WORLD_HEIGHT_M),
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert top == pytest.approx(0.0)
    assert left == pytest.approx(CANVAS_WIDTH_PX - width)


def test_the_start_zone_rectangle_is_these_four_numbers() -> None:
    """
    The whole rectangle as literal expected values, worked out by hand.

    500 px over 11.088889 m is 45.09018 px/m, so the zone's left edge at 4.944 m
    is 4.944 * 45.09018 = 222.9258 px, and its top edge is y_max measured down
    from the top of the canvas: 500 - 6.144 * 45.09018 = 222.9659 px. Top and left
    differ by the flip and by the zone's centre sitting half a thousandth of a
    metre off the canvas centre. Each side is 1.2 m, or 54.1082 px.

    Written as literals rather than as agreement between ``zone_to_pixel_rect``
    and the ``world_to_pixel`` calls it is built from: the two agreeing proves
    only that they are consistent, so a flip, a scale or a transposed axis
    inside both of them would still pass.
    """
    assert zone_to_pixel_rect(
        ZONE,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((222.9258, 222.9659, 54.1082, 54.1082), abs=0.001)


def test_zone_to_pixel_rect_of_the_whole_world_is_the_whole_canvas() -> None:
    """The extreme case: the world fills the canvas exactly, edge to edge."""
    assert zone_to_pixel_rect(
        (0.0, WORLD_WIDTH_M, 0.0, WORLD_HEIGHT_M),
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((0.0, 0.0, CANVAS_WIDTH_PX, CANVAS_HEIGHT_PX))


def test_zone_to_pixel_rect_of_an_upright_zone_has_positive_extents() -> None:
    """
    Qt reads a negative width as an empty rectangle, so an upright zone must not make one.

    Upright is the precondition, not a result: this pins that the ordinary cases
    come out positive, and the inverted case is pinned separately below as what it
    is rather than as what it should have been.
    """
    for zone in (
        (0.0, 1.0, 0.0, 1.0),
        ZONE,
        (0.0, WORLD_WIDTH_M, 0.0, WORLD_HEIGHT_M),
        (5.0, 6.0, 5.0, 5.5),
    ):
        _, _, width, height = zone_to_pixel_rect(
            zone,
            world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
            canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
        )
        assert width > 0.0
        assert height > 0.0


def test_zone_to_pixel_rect_of_an_inverted_zone_returns_negative_extents() -> None:
    """
    An inverted zone is returned as the arithmetic gives it, not repaired.

    The zone ``(2, 1, 3, 2)`` has ``x_min > x_max`` and ``y_min > y_max``, so the
    rectangle runs backwards on both axes: 2 m along is 90.1804 px, 3 m down is
    409.8196 px, and each extent is -1 m, or -45.0902 px. A caller that gets one of
    these has passed a zone that does not exist, and
    :func:`rescue_turtle.validation.safe_zone_configuration_errors` is where that
    is refused: this pure function is arithmetic and does not check its argument.
    """
    assert zone_to_pixel_rect(
        (2.0, 1.0, 3.0, 2.0),
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    ) == pytest.approx((90.1804, 409.8196, -45.0902, -45.0902), abs=0.001)


def test_zone_to_pixel_rect_scales_each_axis_on_its_own() -> None:
    """
    A rectangular canvas maps a square zone to a rectangle of the right ratio.

    Guards against the two axes being swapped, which a square canvas cannot show
    because it maps the wrong way up.
    """
    left, top, width, height = zone_to_pixel_rect(
        (0.0, 2.0, 0.0, 2.0),
        world_width_m=4.0, world_height_m=4.0,
        canvas_width_px=400.0, canvas_height_px=200.0,
    )
    assert width == pytest.approx(200.0)
    assert height == pytest.approx(100.0)
    assert left == pytest.approx(0.0)
    assert top == pytest.approx(100.0)


def test_a_zone_moved_off_the_centre_moves_the_rectangle_with_it() -> None:
    """
    The rectangle tracks the zone rather than being pinned to the centre.

    The zone here is moved a little further along x and a little lower in y, so
    both the left edge and the top edge have to move down and to the right. That
    is the pair of directions a flipped y axis gets wrong: getting only one of
    them right still puts the marker in the wrong corner of the canvas.
    """
    centre = zone_to_pixel_rect(
        ZONE,
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    shifted = zone_to_pixel_rect(
        (5.0, 6.2, 4.0, 5.2),
        world_width_m=WORLD_WIDTH_M, world_height_m=WORLD_HEIGHT_M,
        canvas_width_px=CANVAS_WIDTH_PX, canvas_height_px=CANVAS_HEIGHT_PX,
    )
    assert shifted[0] > centre[0]
    assert shifted[1] > centre[1]
    assert shifted[2:] == pytest.approx(centre[2:])
