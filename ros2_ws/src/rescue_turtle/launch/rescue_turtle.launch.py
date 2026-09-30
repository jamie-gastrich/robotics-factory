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
Launch one rescue_turtle pair.

Brings up turtlesim, the spawner and the rescue_manager for a single
(rescuer, victim) pair. Set ``turtlesim_gui:=False`` to attach to a turtlesim
that is already running, which is how the headless checks drive it.

This does not start ``turtle_teleop_key``: the rescuer is driven by a human on
the keyboard, and that needs a terminal of its own, not a managed process. It
also launches exactly one pair. A second pair is a second ``ros2 launch`` with
different names, which is a deliberate manual step for now.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# The default pair. Both nodes derive their own topic, service and node names
# from it, so a different pair needs this file run again, not edited.
DEFAULT_RESCUER_NAME = 'turtle1'
DEFAULT_VICTIM_NAME = 'turtle2'
DEFAULT_TURTLESIM_NODE = 'turtlesim'


def generate_launch_description() -> LaunchDescription:
    """
    Return the launch description for one pair.

    :return: The launch description, arguments first, then turtlesim (if
        asked for), then the spawner and the rescue_manager.
    """
    rescuer_name = LaunchConfiguration('rescuer_name')
    victim_name = LaunchConfiguration('victim_name')
    spawner_node_name = LaunchConfiguration('spawner_node_name')
    manager_node_name = LaunchConfiguration('manager_node_name')
    attach_distance = LaunchConfiguration('attach_distance')
    follow_rate_hz = LaunchConfiguration('follow_rate_hz')
    min_spawn_distance = LaunchConfiguration('min_spawn_distance')
    spawn_theta_random = LaunchConfiguration('spawn_theta_random')
    rng_seed = LaunchConfiguration('rng_seed')
    turtlesim_node = LaunchConfiguration('turtlesim_node')
    turtlesim_gui = LaunchConfiguration('turtlesim_gui')

    arguments = [
        DeclareLaunchArgument(
            'rescuer_name', default_value=DEFAULT_RESCUER_NAME,
            description='Name of the rescuing turtle, and the root of its pose topic'),
        DeclareLaunchArgument(
            'victim_name', default_value=DEFAULT_VICTIM_NAME,
            description='Name the spawner gives the turtle to be rescued'),
        DeclareLaunchArgument(
            'spawner_node_name', default_value='',
            description='Override for the spawner name alone, empty derives it'),
        DeclareLaunchArgument(
            'manager_node_name', default_value='',
            description='Override for the manager name alone, empty derives it'),
        DeclareLaunchArgument(
            'attach_distance', default_value='0.7',
            description='Metres within which the pair is attached and a rescue starts'),
        DeclareLaunchArgument(
            'follow_rate_hz', default_value='20.0',
            description='Rate of the manager control timer in hertz'),
        DeclareLaunchArgument(
            'min_spawn_distance', default_value='2.0',
            description='Metres a new victim must spawn clear of the start zone'),
        DeclareLaunchArgument(
            'spawn_theta_random', default_value='True',
            description='Whether a new victim gets a random heading'),
        DeclareLaunchArgument(
            'rng_seed', default_value='-1',
            description='Seed for the spawn poses, -1 for a different one every run'),
        DeclareLaunchArgument(
            'turtlesim_node', default_value=DEFAULT_TURTLESIM_NODE,
            description='Name of the node holding the background parameters'),
        DeclareLaunchArgument(
            'turtlesim_gui', default_value='True',
            description='Start turtlesim here, or False to use one already running'),
    ]

    turtlesim = Node(
        package='turtlesim',
        executable='turtlesim_node',
        name=turtlesim_node,
        output='screen',
        condition=IfCondition(turtlesim_gui),
    )

    # Both nodes get the same pair, so they derive the same status topic and
    # neither has to be told about the other. Their own names are not shared:
    # two nodes under one name would share a parameter namespace, a logger name
    # and its parameter events, so each name goes to its own node only.
    pair_parameters = [
        {
            'rescuer_name': rescuer_name,
            'victim_name': victim_name,
        }
    ]

    spawner = Node(
        package='rescue_turtle',
        executable='spawner',
        parameters=pair_parameters + [
            {
                'node_name': spawner_node_name,
                'min_spawn_distance': min_spawn_distance,
                'spawn_theta_random': spawn_theta_random,
                'rng_seed': rng_seed,
            },
        ],
        output='screen',
    )

    rescue_manager = Node(
        package='rescue_turtle',
        executable='rescue_manager',
        parameters=pair_parameters + [
            {
                'node_name': manager_node_name,
                'attach_distance': attach_distance,
                'follow_rate_hz': follow_rate_hz,
                'turtlesim_node': turtlesim_node,
            },
        ],
        output='screen',
    )

    return LaunchDescription(arguments + [turtlesim, spawner, rescue_manager])
