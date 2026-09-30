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
Unit tests for turtle-name derivation and validation.

No ROS graph is needed: the module under test imports no rclpy and no YAML
parser. These are the tests that make "no hard-coded turtle names" a checked
property rather than a convention.

The default pair is checked against literal names on purpose. Comparing the
derivations against the constants the dataclass fields default to would pass
for any template at all, and would not notice the documented defaults changing.
Test files sit outside the package the "no hard-coded names" grep covers, so
spelling a turtle name out here is exactly where it belongs.
"""

import dataclasses

import pytest

from rescue_turtle.rescue_pair import DEFAULT_VICTIM_NAME
from rescue_turtle.rescue_pair import RescuePair
from rescue_turtle.rescue_pair import resolve


def test_the_default_pair_derives_the_documented_names() -> None:
    """The default pair is the one the spec and the launch file promise."""
    pair = RescuePair()
    assert pair.rescuer_name == 'turtle1'
    assert pair.victim_name == 'turtle2'
    assert pair.rescuer_pose_topic == '/turtle1/pose'
    assert pair.victim_pose_topic == '/turtle2/pose'
    assert pair.victim_teleport_service == '/turtle2/teleport_absolute'
    assert pair.victim_kill_name == 'turtle2'
    assert pair.status_topic == '/rescue_turtle/turtle1_to_turtle2/status'
    assert pair.node_name == 'rescue_manager_turtle1_to_turtle2'
    assert pair.spawner_node_name == 'spawner_turtle1_to_turtle2'


def test_a_non_default_pair_derives_everything_from_its_two_names() -> None:
    """Nothing about a pair is special, so another pair needs no other code."""
    pair = RescuePair('alpha', 'beta')
    assert pair.rescuer_pose_topic == '/alpha/pose'
    assert pair.victim_pose_topic == '/beta/pose'
    assert pair.victim_teleport_service == '/beta/teleport_absolute'
    assert pair.victim_kill_name == 'beta'
    assert pair.status_topic == '/rescue_turtle/alpha_to_beta/status'
    assert pair.node_name == 'rescue_manager_alpha_to_beta'
    assert pair.spawner_node_name == 'spawner_alpha_to_beta'


def test_two_pairs_never_collide_on_a_topic_or_a_node_name() -> None:
    """The status topic and node name are pair-scoped, so instances cannot talk."""
    first = RescuePair('alpha', 'beta')
    second = RescuePair('gamma', 'delta')
    assert first.status_topic != second.status_topic
    assert first.node_name != second.node_name
    assert first.spawner_node_name != second.spawner_node_name
    assert first.victim_pose_topic != second.victim_pose_topic


@pytest.mark.parametrize('name', ['alpha', 'Alpha_9', '_private', 'a'])
def test_usable_turtle_names_are_accepted(name: str) -> None:
    """The identifier pattern is what ROS itself accepts as a name segment."""
    assert RescuePair(name, 'beta').rescuer_name == name


@pytest.mark.parametrize('name', ['9bad', '', 'has space', 'has-dash', 'has.dot', 'sla/sh'])
def test_unusable_turtle_names_are_rejected(name: str) -> None:
    """A name that could not be a ROS name segment fails at construction."""
    with pytest.raises(ValueError, match='not a usable turtle name'):
        RescuePair(name, 'beta')
    with pytest.raises(ValueError, match='not a usable turtle name'):
        RescuePair('alpha', name)


def test_a_turtle_cannot_rescue_itself() -> None:
    """Equal names would make the manager chase its own pose forever."""
    with pytest.raises(ValueError, match='cannot rescue itself'):
        RescuePair('alpha', 'alpha')
    with pytest.raises(ValueError, match='cannot rescue itself'):
        RescuePair(DEFAULT_VICTIM_NAME, DEFAULT_VICTIM_NAME)


def test_the_pair_is_frozen() -> None:
    """Re-pairing a live node by mutating its pair is not possible."""
    pair = RescuePair('alpha', 'beta')
    with pytest.raises(dataclasses.FrozenInstanceError):
        pair.victim_name = 'gamma'  # type: ignore[misc]


def test_an_empty_override_falls_back_to_the_derived_name() -> None:
    """The derived parameters use a sentinel default, so an override still wins."""
    pair = RescuePair('alpha', 'beta')
    assert resolve(None, pair.status_topic) == pair.status_topic
    assert resolve('', pair.status_topic) == pair.status_topic
    assert resolve('/somewhere/else', pair.status_topic) == '/somewhere/else'
