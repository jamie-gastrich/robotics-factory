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
The states of the rescue finite state machine, and the hold that follows one.

Pure, no rclpy import, so the manager can be reasoned about without a graph.

There is deliberately no SUCCESS state: bringing the victim into the start zone
is a logged and published event, and the state machine returns to IDLE
immediately. The respawn that follows belongs to the spawner, not to the
manager, so a state that waited for it would only add a state nobody acts on.

IDLE is nevertheless not left completely passive after a success, because of
what happens next. At SUCCESS the victim is still sitting exactly where the
rescuer brought it, and the spawner only replaces it ``respawn_delay_s`` later.
IDLE would therefore attach again on the very next tick, start a second rescue
over the freshly respawned victim and drag it straight back to the start zone.
So IDLE holds until the hold predicate here says otherwise. The hold is a
property of the state machine, not of the node, which is why the decision is a
plain function over four values and can be unit tested.
"""

from enum import Enum
from typing import Final

from .geometry import distance
from .geometry import Point

#: How far a pose has to move before it is a different turtle, in metres.
#: Far below any spawn distance, far above the noise of a published double.
POSE_REPLACED_EPSILON: Final[float] = 1e-6


class RescueState(Enum):
    """The two states of the rescue finite state machine."""

    IDLE = 'idle'
    RESCUE = 'rescue'


class HoldRelease(Enum):
    """Why the hold on IDLE after a completed rescue is over."""

    VICTIM_ABSENT = 'the victim pose went stale, so it is being killed'
    VICTIM_REPLACED = 'the live victim is a different turtle from the rescued one'
    SEPARATED = 'the victim is out of attach distance of the rescuer again'


def hold_release_reason(
    rescuer: Point | None,
    victim: Point | None,
    pose_at_success: Point | None,
    attach_distance: float,
) -> HoldRelease | None:
    """
    Return why the post-success hold can be released, or ``None`` to hold on.

    A pose is ``None`` when it is absent, which the manager decides by its own
    staleness timeout. The decision is made against the pose recorded at SUCCESS
    rather than against the geometry of the pair, because "the rescuer and the
    victim are still close together" is exactly the state a hold exists to
    survive: it is true both when the same victim is still there and when a
    respawned one has landed next to a rescuer parked in the start zone.

    Every branch here can only lead to a release, never to a wait on something
    that cannot happen:

    - no live victim pose at all means the old turtle is gone, so there is
      nothing left to re-attach to;
    - a live victim anywhere other than the pose the rescue ended on is a
      different turtle, because the manager only teleports a victim while a
      rescue is running and never while a hold is in force;
    - separation and a missing rescuer are the remaining, secondary paths.

    A recorded pose of ``None`` is not a state this package can reach, the two
    are set together. It releases rather than holds, so that a programming
    error can never turn into a manager that never rescues again.
    """
    if victim is None:
        return HoldRelease.VICTIM_ABSENT
    if pose_at_success is None or _has_moved(victim, pose_at_success):
        return HoldRelease.VICTIM_REPLACED
    if rescuer is None:
        return None
    if distance(rescuer[0], rescuer[1], victim[0], victim[1]) >= attach_distance:
        return HoldRelease.SEPARATED
    return None


def _has_moved(victim: Point, pose_at_success: Point) -> bool:
    """Return whether a live pose is a different pose from the one recorded."""
    return (
        abs(victim[0] - pose_at_success[0]) > POSE_REPLACED_EPSILON
        or abs(victim[1] - pose_at_success[1]) > POSE_REPLACED_EPSILON
    )
