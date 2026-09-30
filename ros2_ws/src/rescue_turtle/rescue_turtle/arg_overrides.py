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
The parameter overrides a node is started with, read out of its argument vector.

A ROS node cannot read its own parameters before it exists, but the node name
is a constructor argument, so a node whose name is derived from its
``rescuer_name``/``victim_name`` parameters has to look at the argument vector
to know what to call itself. Both argument forms are read, because both are in
use: ``-p name:=value`` from a command line, and ``--params-file``, which is
what ``launch_ros`` writes a node's parameters into.

This lives apart from :mod:`rescue_turtle.rescue_pair`, whose subject is name
derivation, so that the pair module keeps importing neither rclpy nor a YAML
parser. The parsing itself is testable without a ROS graph, like the rest of
the pure logic in this package.
"""

from collections.abc import Sequence
from typing import Any
from typing import Final

# PyYAML is imported by rclpy itself, so it is present wherever this package
# runs; reading a launch-generated parameters file needs nothing else beyond
# the python3-yaml declared in package.xml. The stubs are not installed here,
# hence the ignore.
import yaml  # type: ignore[import-untyped]

#: The only wildcard key a parameters file may use to mean "this node".
WILDCARD_KEY: Final[str] = '/**'

#: Argument tokens that introduce a parameter name and its value.
PARAM_FLAGS: Final[tuple[str, ...]] = ('-p', '--param')

#: Argument token that introduces a parameters file.
PARAMS_FILE_FLAG: Final[str] = '--params-file'

#: Argument token that starts, and one that ends, the ROS argument section.
ROS_ARGS_FLAG: Final[str] = '--ros-args'
ARGUMENTS_END_FLAG: Final[str] = '--'


def parameter_overrides(argv: Sequence[str]) -> dict[str, str]:
    """
    Return the parameter overrides found in a ROS argument vector.

    Later entries win, matching how the middleware applies them.

    Only values a node name can be derived from are of interest here, so
    non-string entries are ignored. A file that cannot be read or parsed is
    ignored too: the node then comes up under the default derived name and
    says so in its first log line.
    """
    overrides: dict[str, str] = {}
    ros_args = _ros_arguments(argv)

    index = 0
    while index < len(ros_args):
        token = ros_args[index]
        if token in PARAM_FLAGS and index + 1 < len(ros_args):
            name, separator, value = ros_args[index + 1].partition(':=')
            if separator:
                overrides[name] = value
            index += 2
        elif token == PARAMS_FILE_FLAG and index + 1 < len(ros_args):
            overrides.update(_overrides_from_file(ros_args[index + 1]))
            index += 2
        else:
            index += 1
    return overrides


def _ros_arguments(argv: Sequence[str]) -> list[str]:
    """Return the arguments between ``--ros-args`` and a bare ``--``."""
    collecting = False
    ros_args: list[str] = []
    for arg in argv:
        if not collecting:
            if arg == ROS_ARGS_FLAG:
                collecting = True
            continue
        if arg == ARGUMENTS_END_FLAG:
            break
        ros_args.append(arg)
    return ros_args


def _overrides_from_file(path: str) -> dict[str, str]:
    """
    Return the string parameters a ``--params-file`` sets for this node.

    Two kinds of key address the node itself: the exact wildcard ``/**``, which
    is what ``launch_ros`` writes for a node it was given no name for, and a
    single-segment node key such as ``spawner_alpha_to_beta``, which is how a
    file names one node. A key naming a namespace, or naming a different node,
    belongs to somebody else and is left alone, so a file written for another
    node can never make this one come up under the wrong name.

    ROS 2 lets a node-specific key win over ``/**`` whichever order the two
    appear in, so the wildcard section is merged first and the node keys
    overwrite it.
    """
    try:
        with open(path, encoding='utf-8') as handle:
            document: Any = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(document, dict):
        return {}

    wildcard: dict[str, str] = {}
    named: dict[str, str] = {}
    for key, section in document.items():
        if not isinstance(key, str) or not isinstance(section, dict):
            continue
        if key == WILDCARD_KEY:
            target = wildcard
        elif _is_single_segment(key):
            target = named
        else:
            continue
        parameters = section.get('ros__parameters')
        if isinstance(parameters, dict):
            target.update(
                (parameter, str(value))
                for parameter, value in parameters.items()
                if isinstance(value, str)
            )
    return {**wildcard, **named}


def _is_single_segment(key: str) -> bool:
    """Return whether a parameters-file key names one node rather than a namespace."""
    name = key.strip('/')
    return bool(name) and '/' not in name
