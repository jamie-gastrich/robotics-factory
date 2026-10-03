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
Unit tests for the startup parameter checks of all three nodes.

No ROS graph is needed: the module under test imports no rclpy. Every node fails
fast by raising the first of these errors, so what matters here is that every
rule names the parameter it is about, because that string is the whole error
message an operator gets.
"""

import pytest

from rescue_turtle.geometry import canvas_has_room
from rescue_turtle.validation import manager_configuration_errors
from rescue_turtle.validation import safe_zone_configuration_errors
from rescue_turtle.validation import spawner_configuration_errors
from rescue_turtle.validation import zone_errors
from rescue_turtle.validation import zone_on_world_errors

#: The measured start pose, start zone, world and canvas of a stock turtlesim.
START = (5.544444, 5.544444)
ZONE = (4.944, 6.144, 4.944, 6.144)
CANVAS = (0.0, 11.088889, 0.0, 11.088889)


def spawner_errors(**overrides: object) -> list[str]:
    """Return the spawner's configuration errors with defaults and overrides."""
    arguments: dict[str, object] = {
        'start': START,
        'zone': ZONE,
        'canvas': CANVAS,
        'min_spawn_distance': 2.0,
        'respawn_delay_s': 1.0,
        'service_wait_timeout_s': 5.0,
        'service_retry_period_s': 1.0,
    }
    arguments.update(overrides)
    return spawner_configuration_errors(**arguments)  # type: ignore[arg-type]


def manager_errors(**overrides: object) -> list[str]:
    """Return the manager's configuration errors with defaults and overrides."""
    arguments: dict[str, object] = {
        'attach_distance': 0.7,
        'follow_rate_hz': 20.0,
        'pose_timeout_s': 1.0,
        'service_wait_timeout_s': 5.0,
        'zone': ZONE,
        'rescue_color': (255, 0, 0),
        'default_color': (255, 255, 255),
    }
    arguments.update(overrides)
    return manager_configuration_errors(**arguments)  # type: ignore[arg-type]


def safe_zone_errors(**overrides: object) -> list[str]:
    """Return the overlay's configuration errors with defaults and overrides."""
    arguments: dict[str, object] = {
        'zone': ZONE,
        'world_size': (11.088889, 11.088889),
        'canvas_size_px': (500.0, 500.0),
        'canvas_margin_px': 0.0,
        'track_period_s': 0.1,
        'window_title': 'TurtleSim',
        'window_class': 'turtlesim_node',
    }
    arguments.update(overrides)
    return safe_zone_configuration_errors(**arguments)  # type: ignore[arg-type]


# --------------------------------------------------------------------- geometry


def test_a_whole_canvas_has_room_when_one_corner_does() -> None:
    """The stock window reaches far past the start zone, so a spawn is possible."""
    assert canvas_has_room(ZONE, CANVAS, 2.0)


def test_a_canvas_inside_the_exclusion_has_no_room() -> None:
    """Every corner too close means no pose could ever be accepted."""
    assert not canvas_has_room(ZONE, ZONE, 2.0)


def test_a_canvas_that_just_reaches_the_exclusion_has_room() -> None:
    """The test is on the margin itself, so the boundary case is included."""
    x_min, x_max, y_min, y_max = ZONE
    canvas = (x_min - 2.0, x_max, y_min, y_max)
    assert canvas_has_room(ZONE, canvas, 2.0)
    assert not canvas_has_room(ZONE, canvas, 2.001)


# ---------------------------------------------------------------------- zones


def test_a_normal_zone_has_no_errors() -> None:
    """The measured zone is a zone."""
    assert zone_errors('start zone', ZONE) == []


def test_an_inverted_or_empty_zone_is_rejected() -> None:
    """A zone with no area contains nothing, so nothing can ever arrive in it."""
    assert 'is empty' in zone_errors('start zone', (6.144, 4.944, 4.944, 6.144))[0]
    assert 'is empty' in zone_errors('start zone', (5.0, 5.0, 5.0, 5.0))[0]
    assert 'is empty' in zone_errors('start zone', (4.944, 6.144, 6.144, 4.944))[0]


# -------------------------------------------------------------------- spawner


def test_the_default_spawner_configuration_is_accepted() -> None:
    """Nothing about the shipped defaults is a problem."""
    assert spawner_errors() == []


@pytest.mark.parametrize('distance', [0.0, -1.0])
def test_a_non_positive_min_spawn_distance_is_rejected(distance: float) -> None:
    """A victim could never spawn clear of the zone, and never spawn at all."""
    assert 'min_spawn_distance must be > 0' in spawner_errors(
        min_spawn_distance=distance)[0]


def test_a_start_zone_that_excludes_the_start_pose_is_rejected() -> None:
    """The rescuer could never be in its own goal, so no rescue could succeed."""
    assert 'does not contain the start pose' in spawner_errors(
        zone=(0.0, 1.0, 0.0, 1.0))[0]


def test_a_zone_with_no_area_is_reported_once() -> None:
    """An empty zone is the real problem; the start pose is then merely outside it."""
    errors = spawner_errors(zone=(6.144, 4.944, 6.144, 4.944))
    assert len(errors) == 1
    assert 'is empty' in errors[0]


def test_a_canvas_with_no_area_is_rejected() -> None:
    """There would be nowhere to put a turtle."""
    assert 'canvas is empty' in spawner_errors(canvas=(11.54, 0.0, 0.0, 11.54))[0]


def test_a_canvas_the_victim_can_never_escape_is_rejected() -> None:
    """Every corner is within the minimum distance, so sampling always gives up."""
    errors = spawner_errors(canvas=(4.0, 6.5, 4.0, 6.5), min_spawn_distance=2.0)
    assert 'no spawn pose could ever be accepted' in errors[0]


def test_a_negative_respawn_delay_is_rejected() -> None:
    """A negative timer period is not a delay, it is a broken clock."""
    assert 'respawn_delay_s must be >= 0' in spawner_errors(respawn_delay_s=-0.1)[0]


@pytest.mark.parametrize('timeout', [0.0, -1.0])
def test_a_non_positive_wait_timeout_is_rejected(timeout: float) -> None:
    """A zero wait never waits, so the retry would spin as fast as it can."""
    assert 'service_wait_timeout_s must be > 0' in spawner_errors(
        service_wait_timeout_s=timeout)[0]


@pytest.mark.parametrize('period', [0.0, -1.0])
def test_a_non_positive_retry_period_is_rejected(period: float) -> None:
    """Same reason: the retry timer has to be a real period."""
    assert 'service_retry_period_s must be > 0' in spawner_errors(
        service_retry_period_s=period)[0]


def test_every_spawner_problem_is_reported_not_just_the_first() -> None:
    """The node raises the first, so the list has to be ordered, not deduplicated."""
    errors = spawner_errors(
        min_spawn_distance=0.0, respawn_delay_s=-1.0, service_retry_period_s=0.0)
    assert len(errors) == 3
    assert errors[0].startswith('min_spawn_distance')
    assert errors[1].startswith('respawn_delay_s')
    assert errors[2].startswith('service_retry_period_s')


# -------------------------------------------------------------------- manager


def test_the_default_manager_configuration_is_accepted() -> None:
    """Nothing about the shipped defaults is a problem."""
    assert manager_errors() == []


@pytest.mark.parametrize('value', [0.0, -0.5])
def test_a_non_positive_attach_distance_is_rejected(value: float) -> None:
    """Nothing is ever within a non-positive distance, so no rescue ever starts."""
    assert 'attach_distance must be > 0' in manager_errors(attach_distance=value)[0]


def test_a_non_positive_follow_rate_is_rejected() -> None:
    """A control timer of zero hertz never evaluates the state machine."""
    assert 'follow_rate_hz must be > 0' in manager_errors(follow_rate_hz=0.0)[0]


def test_a_non_positive_pose_timeout_is_rejected() -> None:
    """Every pose would count as stale, so nothing would ever be acted on."""
    assert 'pose_timeout_s must be > 0' in manager_errors(pose_timeout_s=-1.0)[0]


def test_a_colour_outside_a_byte_is_rejected() -> None:
    """Turtlesim takes 0-255 per component, so anything else is refused there."""
    assert 'rescue_color component 300' in manager_errors(
        rescue_color=(300, 0, 0))[0]
    assert 'default_color component -1' in manager_errors(
        default_color=(-1, 0, 0))[0]


def test_the_colour_bounds_are_inclusive() -> None:
    """0 and 255 are legal, so the check is on the closed interval."""
    assert manager_errors(rescue_color=(0, 0, 0), default_color=(255, 255, 255)) == []


def test_a_manager_zone_with_no_area_is_rejected() -> None:
    """No zone means no goal, so the rescue could never finish."""
    assert 'start zone is empty' in manager_errors(zone=(6.144, 4.944, 4.944, 6.144))[0]


# ----------------------------------------------------------------- zone on world


def test_a_zone_inside_the_world_has_no_errors() -> None:
    """The measured zone is well within the measured world."""
    assert zone_on_world_errors(ZONE, (11.088889, 11.088889)) == []


def test_a_zone_against_the_walls_is_still_on_the_world() -> None:
    """The walls are the edge of the world, so touching them is allowed."""
    assert zone_on_world_errors((0.0, 11.088889, 0.0, 11.088889), (11.088889, 11.088889)) == []


@pytest.mark.parametrize('zone', [
    (-1.0, 1.0, 0.0, 1.0),
    (0.0, 1.0, -1.0, 1.0),
    (10.5, 12.0, 10.5, 12.0),
    (0.0, 1.0, 10.5, 12.0),
])
def test_a_zone_off_the_world_is_rejected(zone: tuple[float, float, float, float]) -> None:
    """A zone off the world maps to pixels off the canvas, where no turtle is."""
    assert 'is not inside the world' in zone_on_world_errors(zone, (11.088889, 11.088889))[0]


# ------------------------------------------------------------------ safe zone


def test_the_default_safe_zone_configuration_is_accepted() -> None:
    """Nothing about the shipped defaults is a problem."""
    assert safe_zone_errors() == []


@pytest.mark.parametrize('world', [(0.0, 11.088889), (-11.088889, 11.088889)])
def test_a_non_positive_world_extent_is_rejected(
    world: tuple[float, float],
) -> None:
    """Nothing maps to a pixel without a world, and the division by zero is worse."""
    errors = safe_zone_errors(world_size=world)
    assert 'world_width_m must be > 0' in errors[0]


@pytest.mark.parametrize('canvas, expected', [
    ((0.0, 500.0), 'canvas_width_px must be > 0'),
    ((500.0, 0.0), 'canvas_height_px must be > 0'),
    ((0.0, 0.0), 'canvas_width_px must be > 0'),
])
def test_a_non_positive_canvas_size_is_rejected(
    canvas: tuple[float, float],
    expected: str,
) -> None:
    """
    The same reason, on the pixels: a canvas of no size cannot hold the marker.

    Each case names the field that is wrong, rather than accepting either name:
    the string is the whole error message an operator gets, so a message that
    blames the width when the height is the zero one is a message that sends them
    to the wrong parameter.
    """
    assert expected in safe_zone_errors(canvas_size_px=canvas)[0]


def test_a_negative_canvas_margin_is_rejected() -> None:
    """A margin shifts the canvas origin, so a negative one moves it off the window."""
    assert 'canvas_margin_px must be >= 0' in safe_zone_errors(canvas_margin_px=-1.0)[0]


def test_a_zero_track_period_is_rejected() -> None:
    """
    A zero period is not a period, it is a spin at the speed of the machine.

    Re-raising the overlay is the mechanism for keeping it on top, so an
    unbounded one is exactly the failure worth refusing.
    """
    assert 'track_period_s must be > 0' in safe_zone_errors(track_period_s=0.0)[0]


def test_an_empty_window_title_is_rejected() -> None:
    """Matching nothing finds nothing, and the overlay would wait forever."""
    assert 'turtlesim_window_title must not be empty' in safe_zone_errors(
        window_title='')[0]


def test_an_empty_window_class_is_rejected() -> None:
    """Same reason, and the class is what keeps two turtlesims distinguishable."""
    assert 'turtlesim_window_class must not be empty' in safe_zone_errors(
        window_class='')[0]


def test_a_safe_zone_with_no_area_is_rejected() -> None:
    """A zone with no area has no centre to place a marker on."""
    assert 'start zone is empty' in safe_zone_errors(zone=(6.144, 4.944, 4.944, 6.144))[0]


def test_a_safe_zone_off_the_world_is_rejected() -> None:
    """The marker would be drawn where the canvas is not."""
    assert 'is not inside the world' in safe_zone_errors(zone=(0.0, 20.0, 0.0, 20.0))[0]


def test_an_empty_zone_is_not_also_reported_as_off_the_world() -> None:
    """An inverted zone has no bounds to compare, so one error is the truth."""
    errors = safe_zone_errors(zone=(6.144, 4.944, 6.144, 4.944))
    assert len(errors) == 1
    assert 'is empty' in errors[0]


def test_every_safe_zone_problem_is_reported_not_just_the_first() -> None:
    """The node raises the first, so the list has to be ordered, not deduplicated."""
    errors = safe_zone_errors(
        track_period_s=0.0, canvas_margin_px=-1.0, window_title='', window_class='')
    assert len(errors) == 4
    assert errors[0].startswith('canvas_margin_px')
    assert errors[1].startswith('track_period_s')
    assert errors[2].startswith('turtlesim_window_title')
    assert errors[3].startswith('turtlesim_window_class')
