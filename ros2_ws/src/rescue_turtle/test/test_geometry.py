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

No ROS graph is needed: the module under test imports no rclpy.
"""

import math
import random

import pytest

from rescue_turtle.geometry import DEFAULT_MAX_ATTEMPTS
from rescue_turtle.geometry import distance
from rescue_turtle.geometry import distance_to_zone
from rescue_turtle.geometry import in_zone
from rescue_turtle.geometry import random_spawn_pose

# The measured start zone and canvas of a stock turtlesim window.
ZONE = (4.944, 6.144, 4.944, 6.144)
CANVAS = (0.0, 11.54, 0.0, 11.54)
MIN_SPAWN_DISTANCE = 2.0


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
