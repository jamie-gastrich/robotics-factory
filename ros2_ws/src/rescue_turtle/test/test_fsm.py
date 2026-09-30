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
Unit tests for the state machine's post-success hold.

No ROS graph is needed: the module under test imports no rclpy. This is the
coverage the hold never had, and it is the one that matters, because the way it
used to be decided could keep the manager holding for good: a combination of
legal parameters, with a rescuer parked in the start zone and an attach
distance wider than any spawn distance, satisfied neither release condition and
stopped the game with nothing in the log.
"""

from rescue_turtle.states import hold_release_reason
from rescue_turtle.states import HoldRelease
from rescue_turtle.states import POSE_REPLACED_EPSILON

# The measured start pose of a stock turtlesim turtle1, and a victim rescued
# into the start zone is exactly on it.
START = (5.544444, 5.544444)
ATTACH_DISTANCE = 0.7


def test_a_fresh_victim_still_on_the_rescuer_keeps_the_hold() -> None:
    """The normal case: the rescued turtle is still there, so wait for it."""
    assert hold_release_reason(START, START, START, ATTACH_DISTANCE) is None


def test_the_hold_is_released_when_the_victim_pose_goes_stale() -> None:
    """No victim pose at all means the old turtle is gone, so there is nothing to hold."""
    assert hold_release_reason(START, None, START, ATTACH_DISTANCE) is \
        HoldRelease.VICTIM_ABSENT


def test_the_hold_is_released_when_a_respawned_victim_appears() -> None:
    """Anywhere else on the canvas is a different turtle, and the game goes on."""
    reason = hold_release_reason(START, (9.0, 9.0), START, ATTACH_DISTANCE)
    assert reason is HoldRelease.VICTIM_REPLACED


def test_a_respawn_next_to_the_rescuer_also_releases_the_hold() -> None:
    """Replaced does not mean far: the spawn is what says so, not the distance."""
    reason = hold_release_reason(START, (5.9, 5.9), START, ATTACH_DISTANCE)
    assert reason is HoldRelease.VICTIM_REPLACED


def test_a_respawn_inside_the_attach_distance_also_releases_the_hold() -> None:
    """
    The combination that used to latch: a hold could not be released by geometry.

    ``min_spawn_distance`` 0.1 with ``attach_distance`` 20.0 and the rescuer
    parked in the start zone means every victim, old and new, is within attach
    distance for ever. Nothing about the separation can ever change, so the
    release has to come from the victim being a different turtle.
    """
    wide_attach = 20.0
    assert hold_release_reason(START, START, START, wide_attach) is None
    assert hold_release_reason(START, (5.7, 5.7), START, wide_attach) is \
        HoldRelease.VICTIM_REPLACED


def test_a_victim_moved_by_hand_also_releases_the_hold() -> None:
    """Teleporting the victim away is a replacement as far as the hold is concerned."""
    reason = hold_release_reason(START, (2.0, 2.0), START, ATTACH_DISTANCE)
    assert reason is HoldRelease.VICTIM_REPLACED


def test_the_separation_release_still_works_without_a_recorded_pose() -> None:
    """With nothing recorded, the victim counts as replaced; separation is a fallback."""
    far_apart = hold_release_reason((0.0, 0.0), (5.0, 5.0), None, ATTACH_DISTANCE)
    assert far_apart is HoldRelease.VICTIM_REPLACED


def test_a_missing_rescuer_pose_keeps_the_hold_on_a_known_victim() -> None:
    """With no rescuer there is nothing to attach to, so there is nothing to release."""
    assert hold_release_reason(None, START, START, ATTACH_DISTANCE) is None


def test_the_separation_release_fires_when_the_victim_is_far_and_still() -> None:
    """
    The secondary path, and the one that released a hold in the default setup.

    Only reachable when the victim is still where the rescue ended it, which is
    the case the replaced check is there to catch first, so this documents the
    order of the two paths rather than a situation that arises on its own.
    """
    reason = hold_release_reason((0.0, 0.0), START, START, ATTACH_DISTANCE)
    assert reason is HoldRelease.SEPARATED


def test_a_pose_moved_by_no_more_than_the_epsilon_is_the_same_pose() -> None:
    """Floating point noise on a stationary turtle is not a new turtle."""
    nudged = (START[0] + POSE_REPLACED_EPSILON / 10.0, START[1])
    assert hold_release_reason(START, nudged, START, ATTACH_DISTANCE) is None


def test_the_hold_is_always_released_once_the_victim_leaves_the_success_pose() -> None:
    """No rescuer pose, no attach distance and no separation can keep it for ever."""
    for rescuer in (None, START, (0.0, 0.0)):
        for attach_distance in (0.001, ATTACH_DISTANCE, 20.0, 1e6):
            reason = hold_release_reason(
                rescuer, (9.0, 9.0), START, attach_distance)
            assert reason is HoldRelease.VICTIM_REPLACED
