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
Unit tests for reading parameter overrides out of a node's argument vector.

No ROS graph is needed: the module under test imports no rclpy. What is being
pinned here is which parameters a node may take from a ``--params-file`` and
which win when two keys disagree, because getting that wrong brings a node up
under the wrong name while it behaves perfectly, which is close to
undiagnosable.
"""

from pathlib import Path

from rescue_turtle.arg_overrides import parameter_overrides


def test_parameter_overrides_reads_the_ros_argument_vector() -> None:
    """The node name has to be known before the node can read its parameters."""
    argv = [
        'spawner',
        '--ros-args',
        '-p', 'rescuer_name:=alpha',
        '-p', 'victim_name:=beta',
        '-p', 'node_name:=',
        '--log-level', 'warn',
    ]
    assert parameter_overrides(argv) == {
        'rescuer_name': 'alpha',
        'victim_name': 'beta',
        'node_name': '',
    }


def test_parameter_overrides_ignores_arguments_outside_the_ros_section() -> None:
    """Anything before --ros-args, or after the bare --, belongs to someone else."""
    argv = ['-p', 'victim_name:=ignored', '--ros-args', '-p', 'rng_seed:=7', '--', '-p', 'x:=1']
    assert parameter_overrides(argv) == {'rng_seed': '7'}


def test_parameter_overrides_keeps_the_whole_value_after_the_first_separator() -> None:
    """A value may itself contain the name/value separator."""
    overrides = parameter_overrides(['--ros-args', '--param', 'status_topic:=/a:=b/status'])
    assert overrides == {'status_topic': '/a:=b/status'}


def test_parameter_overrides_of_an_empty_vector_is_empty() -> None:
    """A node run with no arguments at all falls back to every default."""
    assert parameter_overrides([]) == {}


def test_parameter_overrides_reads_a_launch_style_params_file(tmp_path: Path) -> None:
    """launch_ros writes parameters to a file, not to -p, so that has to work."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text(
        '/**:\n'
        '  ros__parameters:\n'
        '    rescuer_name: alpha\n'
        '    victim_name: beta\n'
        '    min_spawn_distance: 2.0\n'
    )
    argv = ['--ros-args', '--params-file', str(params_file)]
    # Only the strings are kept: those are the ones a node name is built from.
    assert parameter_overrides(argv) == {'rescuer_name': 'alpha', 'victim_name': 'beta'}


def test_a_params_file_ignores_another_nodes_namespace(tmp_path: Path) -> None:
    """A wildcard under a namespace is somebody else's node, not this one."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text(
        '/**:\n'
        '  ros__parameters:\n'
        '    victim_name: beta\n'
        '/some/other_ns/**:\n'
        '  ros__parameters:\n'
        '    victim_name: wrong\n'
    )
    argv = ['--ros-args', '--params-file', str(params_file)]
    assert parameter_overrides(argv) == {'victim_name': 'beta'}


def test_a_params_file_ignores_a_node_in_another_namespace(tmp_path: Path) -> None:
    """Same for an explicitly named node: a name is not a namespace prefix."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text(
        'spawner_alpha_to_beta:\n'
        '  ros__parameters:\n'
        '    victim_name: beta\n'
        '/a_namespace/other_node:\n'
        '  ros__parameters:\n'
        '    victim_name: wrong\n'
    )
    argv = ['--ros-args', '--params-file', str(params_file)]
    assert parameter_overrides(argv) == {'victim_name': 'beta'}


def test_a_node_key_wins_over_the_wildcard_either_way_round(tmp_path: Path) -> None:
    """ROS 2 lets the node-specific key win, so file order must not matter."""
    for contents in (
        '/**:\n  ros__parameters:\n    victim_name: wildcard\n'
        'my_node:\n  ros__parameters:\n    victim_name: mine\n',
        'my_node:\n  ros__parameters:\n    victim_name: mine\n'
        '/**:\n  ros__parameters:\n    victim_name: wildcard\n',
    ):
        params_file = tmp_path / 'launch_params'
        params_file.write_text(contents)
        argv = ['--ros-args', '--params-file', str(params_file)]
        assert parameter_overrides(argv) == {'victim_name': 'mine'}


def test_parameter_overrides_lets_the_later_of_two_files_win(tmp_path: Path) -> None:
    """Two files is what launch writes when parameters are given in two dicts."""
    first = tmp_path / 'first'
    first.write_text('/**:\n  ros__parameters:\n    victim_name: beta\n')
    second = tmp_path / 'second'
    second.write_text('/**:\n  ros__parameters:\n    victim_name: gamma\n')
    argv = ['--ros-args', '--params-file', str(first), '--params-file', str(second)]
    assert parameter_overrides(argv) == {'victim_name': 'gamma'}


def test_parameter_overrides_ignores_an_unreadable_params_file(tmp_path: Path) -> None:
    """A missing file is skipped, and the node falls back to the default pair."""
    argv = ['--ros-args', '--params-file', str(tmp_path / 'not_there.yaml')]
    assert parameter_overrides(argv) == {}


def test_parameter_overrides_ignores_an_unparsable_params_file(tmp_path: Path) -> None:
    """A file that is not YAML is skipped rather than taking the node down."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text('ros__parameters: [unclosed\n')
    argv = ['--ros-args', '--params-file', str(params_file)]
    assert parameter_overrides(argv) == {}


def test_parameter_overrides_ignores_a_file_that_is_not_a_mapping(tmp_path: Path) -> None:
    """A YAML document that is a list holds no parameters for anybody."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text('- one\n- two\n')
    argv = ['--ros-args', '--params-file', str(params_file)]
    assert parameter_overrides(argv) == {}


def test_a_later_command_line_parameter_wins_over_a_file(tmp_path: Path) -> None:
    """-p after --params-file is how an operator overrides a launch default."""
    params_file = tmp_path / 'launch_params'
    params_file.write_text('/**:\n  ros__parameters:\n    victim_name: from_file\n')
    argv = ['--ros-args', '--params-file', str(params_file), '-p', 'victim_name:=from_cli']
    assert parameter_overrides(argv) == {'victim_name': 'from_cli'}


def test_a_parameter_with_no_separator_is_not_an_override() -> None:
    """A bare token after -p is not a name/value pair, so it is dropped."""
    assert parameter_overrides(['--ros-args', '-p', 'victim_name']) == {}
