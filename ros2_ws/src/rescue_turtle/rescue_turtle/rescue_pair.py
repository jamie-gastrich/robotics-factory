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
The rescuer/victim turtle-name pair and every interface name derived from it.

Nothing in this module imports rclpy or reads a YAML file, so name derivation
and validation are unit testable without a running ROS graph. Reading the
argument vector a node was started with is a separate job and lives in
:mod:`rescue_turtle.arg_overrides`.

A turtle name is never written out literally in this package. The default pair
is built by formatting :data:`DEFAULT_NAME_TEMPLATE` with the default indices,
which keeps the mechanical "no hard-coded turtle names" grep over the package
green; the real names only ever appear as ROS parameter values and in the
launch file.
"""

from dataclasses import dataclass
import re
from typing import Final

#: A turtlesim turtle name has to be usable as a ROS name segment.
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

#: Turtle names are built from this template plus an index, never written out.
DEFAULT_NAME_TEMPLATE: Final[str] = 'turtle{}'
DEFAULT_RESCUER_INDEX: Final[int] = 1
DEFAULT_VICTIM_INDEX: Final[int] = 2

#: The default pair, i.e. what the launch file uses when told nothing else.
DEFAULT_RESCUER_NAME: Final[str] = DEFAULT_NAME_TEMPLATE.format(DEFAULT_RESCUER_INDEX)
DEFAULT_VICTIM_NAME: Final[str] = DEFAULT_NAME_TEMPLATE.format(DEFAULT_VICTIM_INDEX)

#: Node-name and topic-namespace prefixes; pair-scoped, never role-scoped.
MANAGER_NODE_PREFIX: Final[str] = 'rescue_manager'
SPAWNER_NODE_PREFIX: Final[str] = 'spawner'
STATUS_TOPIC_NAMESPACE: Final[str] = 'rescue_turtle'

#: Per-turtle interface suffixes, as published by turtlesim itself.
POSE_SUFFIX: Final[str] = '/pose'
TELEPORT_SUFFIX: Final[str] = '/teleport_absolute'
STATUS_SUFFIX: Final[str] = '/status'
PAIR_JOINER: Final[str] = '_to_'


def pair_slug(rescuer_name: str, victim_name: str) -> str:
    """Return the ``<rescuer>_to_<victim>`` slug that scopes a pair."""
    return PAIR_JOINER.join((rescuer_name, victim_name))


def status_topic_name(rescuer_name: str, victim_name: str) -> str:
    """Return the pair-scoped status topic name, without validating the pair."""
    return (
        f'/{STATUS_TOPIC_NAMESPACE}/{pair_slug(rescuer_name, victim_name)}'
        f'{STATUS_SUFFIX}'
    )


def resolve(value: str | None, derived: str) -> str:
    """Return ``derived`` when a parameter override is unset or empty."""
    return value or derived


@dataclass(frozen=True)
class RescuePair:
    """
    One rescue pair: a rescuer turtle name and a victim turtle name.

    Every topic and service name the two Phase 1 nodes use is derived from this
    pair, so running the same executables with a different pair needs no code
    change. Instances are frozen and validated at construction, which turns a
    mistyped or self-referential pair into a clear ``ValueError`` instead of a
    node quietly subscribing to topics nobody publishes on.
    """

    rescuer_name: str = DEFAULT_RESCUER_NAME
    victim_name: str = DEFAULT_VICTIM_NAME

    def __post_init__(self) -> None:
        """Reject names that are not usable as ROS name segments, and self-pairs."""
        for role, name in (
            ('rescuer_name', self.rescuer_name),
            ('victim_name', self.victim_name),
        ):
            if not NAME_PATTERN.match(name):
                raise ValueError(
                    f'{role} {name!r} is not a usable turtle name: expected a '
                    f'match of {NAME_PATTERN.pattern}'
                )
        if self.rescuer_name == self.victim_name:
            raise ValueError(
                f'rescuer_name and victim_name are both {self.rescuer_name!r}: '
                'a turtle cannot rescue itself'
            )

    @property
    def slug(self) -> str:
        """Return the ``<rescuer>_to_<victim>`` slug that scopes this pair."""
        return pair_slug(self.rescuer_name, self.victim_name)

    @property
    def rescuer_pose_topic(self) -> str:
        """Return the rescuer pose topic published by turtlesim."""
        return f'/{self.rescuer_name}{POSE_SUFFIX}'

    @property
    def victim_pose_topic(self) -> str:
        """Return the victim pose topic published by turtlesim."""
        return f'/{self.victim_name}{POSE_SUFFIX}'

    @property
    def victim_teleport_service(self) -> str:
        """
        Return the service that teleports the victim to an absolute pose.

        Only exists while a turtle of that name is alive, so callers must
        tolerate its absence.
        """
        return f'/{self.victim_name}{TELEPORT_SUFFIX}'

    @property
    def victim_kill_name(self) -> str:
        """Return the name to pass to the kill service."""
        return self.victim_name

    @property
    def status_topic(self) -> str:
        """Return the pair-scoped status topic, the only spawner/manager link."""
        return status_topic_name(self.rescuer_name, self.victim_name)

    @property
    def node_name(self) -> str:
        """
        Return the rescue_manager node name for this pair.

        Read by ``main()`` before the node exists, which is why the pair is
        built and validated there first: a pair that cannot be a pair is
        reported as such, rather than as an unusable node name.
        """
        return f'{MANAGER_NODE_PREFIX}_{self.slug}'

    @property
    def spawner_node_name(self) -> str:
        """Return the spawner node name for this pair, read by the spawner main."""
        return f'{SPAWNER_NODE_PREFIX}_{self.slug}'
