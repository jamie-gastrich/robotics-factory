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
Node that owns the lifecycle of one victim turtle for one rescue pair.

The spawner kills any turtle already holding the victim's name, clears the
canvas and spawns a fresh victim at a random pose far enough from the start
zone. It repeats that every time the rescue_manager for the same pair reports a
completed rescue. It never looks at a pose and never decides game state; the
pair-scoped status topic is its only input from the rest of the package.
"""

import random
import sys

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.exceptions import InvalidNodeNameException
from rclpy.exceptions import ParameterException
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from rclpy.task import Future
from rclpy.timer import Timer
from std_msgs.msg import String
from std_srvs.srv import Empty
from turtlesim_msgs.srv import Kill
from turtlesim_msgs.srv import Spawn

from .arg_overrides import parameter_overrides
from .geometry import distance_to_zone
from .geometry import random_spawn_pose
from .rescue_pair import DEFAULT_RESCUER_NAME
from .rescue_pair import DEFAULT_VICTIM_NAME
from .rescue_pair import RescuePair
from .rescue_pair import resolve
from .validation import spawner_configuration_errors

#: ``rng_seed`` value that means "do not make the spawns reproducible".
SEED_UNSET = -1

#: Start pose and zone defaults, measured from a stock turtlesim.
DEFAULT_START_X = 5.544444
DEFAULT_START_Y = 5.544444
DEFAULT_ZONE_MIN = 4.944
DEFAULT_ZONE_MAX = 6.144

#: Canvas defaults, the turtlesim window is 11.54 m square.
DEFAULT_CANVAS_MIN = 0.0
DEFAULT_CANVAS_MAX = 11.54

#: How often to re-check for turtlesim while no victim can be spawned.
DEFAULT_SERVICE_RETRY_PERIOD_S = 1.0

#: Queue depth for the status subscription, the only inbound coupling.
STATUS_QUEUE_DEPTH = 10

#: Logger name for a failure that happens before a node name can be derived.
STARTUP_LOG_NAME = 'rescue_turtle_spawner'


class SpawnerNode(Node):
    """Keeps exactly one victim alive for one :class:`RescuePair`."""

    def __init__(self, node_name: str) -> None:
        """Read every knob from parameters, then queue the first victim."""
        super().__init__(node_name)

        self._rescuer_name = self._declare_str('rescuer_name', DEFAULT_RESCUER_NAME)
        self._victim_name = self._declare_str('victim_name', DEFAULT_VICTIM_NAME)
        self._pair = RescuePair(self._rescuer_name, self._victim_name)
        self._check_node_name(self._declare_str('node_name', ''))

        self._spawn_service = self._declare_str('spawn_service', '/spawn')
        self._kill_service = self._declare_str('kill_service', '/kill')
        self._clear_service = self._declare_str('clear_service', '/clear')
        self._status_topic = resolve(
            self._declare_str('status_topic', ''), self._pair.status_topic)

        self._start_x = self._declare_float('start_x', DEFAULT_START_X)
        self._start_y = self._declare_float('start_y', DEFAULT_START_Y)
        self._zone_x_min = self._declare_float('start_zone_x_min', DEFAULT_ZONE_MIN)
        self._zone_x_max = self._declare_float('start_zone_x_max', DEFAULT_ZONE_MAX)
        self._zone_y_min = self._declare_float('start_zone_y_min', DEFAULT_ZONE_MIN)
        self._zone_y_max = self._declare_float('start_zone_y_max', DEFAULT_ZONE_MAX)
        self._min_spawn_distance = self._declare_float('min_spawn_distance', 2.0)
        self._canvas_x_min = self._declare_float('canvas_x_min', DEFAULT_CANVAS_MIN)
        self._canvas_x_max = self._declare_float('canvas_x_max', DEFAULT_CANVAS_MAX)
        self._canvas_y_min = self._declare_float('canvas_y_min', DEFAULT_CANVAS_MIN)
        self._canvas_y_max = self._declare_float('canvas_y_max', DEFAULT_CANVAS_MAX)
        self._random_theta = self._declare_bool('spawn_theta_random', True)
        self._rng_seed = self._declare_int('rng_seed', SEED_UNSET)
        self._respawn_delay_s = self._declare_float('respawn_delay_s', 1.0)
        self._service_wait_timeout_s = self._declare_float('service_wait_timeout_s', 5.0)
        self._service_retry_period_s = self._declare_float(
            'service_retry_period_s', DEFAULT_SERVICE_RETRY_PERIOD_S)
        self._rescue_complete_status = self._declare_str(
            'rescue_complete_status', 'rescue_complete')
        self._validate()

        if self._rng_seed == SEED_UNSET:
            self._rng = random.Random()
        else:
            self._rng = random.Random(self._rng_seed)
        self._chain_active = False
        self._pending_reason = ''
        self._respawn_timer: Timer | None = None
        self._service_retry_timer: Timer | None = None

        self._spawn_client = self.create_client(Spawn, self._spawn_service)
        self._kill_client = self.create_client(Kill, self._kill_service)
        self._clear_client = self.create_client(Empty, self._clear_service)
        self._status_sub = self.create_subscription(
            String, self._status_topic, self._on_status, STATUS_QUEUE_DEPTH)

        self.get_logger().info(
            f'spawner for {self._pair.slug}: victim {self._pair.victim_name!r}, '
            f'status topic {self._status_topic}'
        )
        self._await_spawn_service()
        # Re-checked periodically, so a turtlesim that is late, or that
        # restarts under us, is still picked up without a restart of this node.
        self._service_retry_timer = self.create_timer(
            self._service_retry_period_s, self._on_service_retry)
        self._queue_victim('the first victim')

    # ------------------------------------------------------------------ setup

    def _declare_str(self, name: str, default: str) -> str:
        """Declare a string parameter and return its value."""
        self.declare_parameter(name, default)
        return str(self.get_parameter(name).value)

    def _declare_float(self, name: str, default: float) -> float:
        """Declare a float parameter and return its value."""
        self.declare_parameter(name, default)
        return float(self.get_parameter(name).value)

    def _declare_int(self, name: str, default: int) -> int:
        """Declare an integer parameter and return its value."""
        self.declare_parameter(name, default)
        return int(self.get_parameter(name).value)

    def _declare_bool(self, name: str, default: bool) -> bool:
        """Declare a boolean parameter and return its value."""
        self.declare_parameter(name, default)
        return bool(self.get_parameter(name).value)

    def _check_node_name(self, requested: str) -> None:
        """Warn when the node name parameter disagrees with the live name."""
        if requested and requested != self.get_name():
            self.get_logger().warning(
                f'node_name is {requested!r} but this node is called '
                f'{self.get_name()!r}: a name supplied through --params-file '
                'cannot be read before the node exists'
            )

    def _validate(self) -> None:
        """
        Reject parameter combinations that cannot work.

        :raises ValueError: on a bad zone, canvas or timeout, so that
            :func:`main` can log it and exit instead of spawning a victim the
            manager can never rescue. The rules themselves are pure functions
            in :mod:`rescue_turtle.validation`, so they are unit tested.
        """
        errors = spawner_configuration_errors(
            start=(self._start_x, self._start_y),
            zone=(self._zone_x_min, self._zone_x_max,
                  self._zone_y_min, self._zone_y_max),
            canvas=(self._canvas_x_min, self._canvas_x_max,
                    self._canvas_y_min, self._canvas_y_max),
            min_spawn_distance=self._min_spawn_distance,
            respawn_delay_s=self._respawn_delay_s,
            service_wait_timeout_s=self._service_wait_timeout_s,
            service_retry_period_s=self._service_retry_period_s,
        )
        if errors:
            raise ValueError(errors[0])

    def _turtlesim_services_ready(self) -> bool:
        """
        Return whether turtlesim is there to answer a kill and a spawn.

        ``/clear`` appears at the same moment as the other two, so gating on
        the two the chain cannot do without is enough. The check is asked for
        explicitly rather than assumed: ``call_async`` on a service that has
        not been discovered yet returns a future that never completes, and the
        kill-clear-spawn chain would then stall for the life of the process.
        """
        return self._kill_client.service_is_ready() and self._spawn_client.service_is_ready()

    def _await_spawn_service(self) -> None:
        """
        Wait a bounded time for the spawn service, then leave it to the retry.

        Bounded, because a node that waited here forever would keep a process
        alive with nothing to show for it. The first spawn is not lost by
        waiting: :meth:`_queue_victim` defers it and the retry timer starts it
        as soon as turtlesim is there.
        """
        if self._spawn_client.wait_for_service(timeout_sec=self._service_wait_timeout_s):
            return
        self.get_logger().error(
            f'{self._spawn_service} is not available after '
            f'{self._service_wait_timeout_s} s, so the first victim has NOT been '
            f'spawned; retrying every {self._service_retry_period_s} s until it is'
        )

    # ---------------------------------------------------------------- spawning

    def _queue_victim(self, reason: str) -> None:
        """
        Start the kill, clear, spawn chain that produces one fresh victim.

        Deferred, not skipped, while turtlesim is not there: the request is
        remembered and the retry timer starts it as soon as ``/kill`` and
        ``/spawn`` are both ready. Asking turtlesim to kill a turtle before
        ``/kill`` exists is the one thing that must not happen here, because
        the request it produces never completes and the chain would then be
        stuck for the life of the process, refusing every later respawn as
        already in flight.
        """
        if self._chain_active:
            self.get_logger().warning('a spawn is already in flight, ignoring the request')
            return
        already_waiting = bool(self._pending_reason)
        self._pending_reason = reason
        if not self._turtlesim_services_ready():
            message = (
                f'{reason} is waiting for {self._kill_service} and '
                f'{self._spawn_service}, retrying every '
                f'{self._service_retry_period_s} s'
            )
            # Announced once at info level, so that a wait is visible at all,
            # and then at debug only, so that a wait lasting minutes cannot
            # fill the log with a line a second.
            if already_waiting:
                self.get_logger().debug(message)
            else:
                self.get_logger().info(message)
            return
        self._pending_reason = ''
        self._chain_active = True
        self.get_logger().info(f'killing any live {self._pair.victim_kill_name!r} first')
        request = Kill.Request()
        request.name = self._pair.victim_kill_name
        self._kill_client.call_async(request).add_done_callback(self._on_kill_done)

    def _on_service_retry(self) -> None:
        """
        Start a chain that was deferred, once turtlesim can answer it.

        Does nothing while a chain is in flight: the victim that chain produces
        is the one that was asked for, and a second chain would fight it for
        the name.
        """
        if self._chain_active or not self._pending_reason:
            return
        self._queue_victim(self._pending_reason)

    def _on_kill_done(self, future: Future) -> None:
        """
        Continue the chain once the previous holder of the name is gone.

        The chain continues even when the kill failed: an absent victim is the
        normal case on the first run, and the spawn is what matters.
        """
        error = _service_error(future)
        if error is not None:
            self.get_logger().warning(
                f'kill of {self._pair.victim_kill_name!r} failed ({error}), '
                'spawning anyway'
            )
        self._clear_client.call_async(Empty.Request()).add_done_callback(self._on_clear_done)

    def _on_clear_done(self, future: Future) -> None:
        """Continue the chain once the canvas has been cleared."""
        error = _service_error(future)
        if error is not None:
            self.get_logger().warning(f'clear failed ({error}), spawning anyway')
        self._spawn_victim()

    def _spawn_victim(self) -> None:
        """Ask turtlesim for a new victim at a fresh, reachable pose."""
        x, y, theta = random_spawn_pose(
            self._rng,
            x_min=self._zone_x_min,
            x_max=self._zone_x_max,
            y_min=self._zone_y_min,
            y_max=self._zone_y_max,
            min_distance=self._min_spawn_distance,
            canvas_x_min=self._canvas_x_min,
            canvas_x_max=self._canvas_x_max,
            canvas_y_min=self._canvas_y_min,
            canvas_y_max=self._canvas_y_max,
            random_theta=self._random_theta,
        )
        margin = distance_to_zone(
            x, y,
            self._zone_x_min, self._zone_x_max, self._zone_y_min, self._zone_y_max)
        self.get_logger().info(
            f'spawning {self._pair.victim_name!r} at x={x:.3f} y={y:.3f} '
            f'theta={theta:.3f} rad, {margin:.3f} m clear of the start zone '
            f'(minimum {self._min_spawn_distance} m)'
        )
        request = Spawn.Request()
        request.x = x
        request.y = y
        request.theta = theta
        request.name = self._pair.victim_name
        self._spawn_client.call_async(request).add_done_callback(self._on_spawn_done)

    def _on_spawn_done(self, future: Future) -> None:
        """Report the name turtlesim actually gave the new victim."""
        self._chain_active = False
        error = _service_error(future)
        if error is not None:
            self.get_logger().error(
                f'spawn of {self._pair.victim_name!r} failed: {error}')
            return
        response = future.result()
        spawned_name = '' if response is None else response.name
        if spawned_name != self._pair.victim_name:
            self.get_logger().warning(
                f'asked for {self._pair.victim_name!r} but turtlesim returned '
                f'{spawned_name!r}: its pose is on '
                f'/{spawned_name}/pose, not {self._pair.victim_pose_topic}'
            )
        self.get_logger().info(
            f'{self._pair.victim_name!r} is alive, publishing {self._pair.victim_pose_topic}')

    # ------------------------------------------------------------------ status

    def _on_status(self, message: String) -> None:
        """Arm a respawn when the manager reports a completed rescue."""
        if message.data != self._rescue_complete_status:
            return
        if self._respawn_timer is not None:
            self.get_logger().warning(
                f'respawn already armed, ignoring duplicate {message.data!r}')
            return
        self.get_logger().info(
            f'got {message.data!r}, respawning in {self._respawn_delay_s} s')
        self._respawn_timer = self.create_timer(
            self._respawn_delay_s, self._on_respawn_timer)

    def _on_respawn_timer(self) -> None:
        """Replace the victim once the respawn delay has passed."""
        if self._respawn_timer is not None:
            self._respawn_timer.cancel()
            self._respawn_timer = None
        self._queue_victim('the respawn after a rescue')

    # --------------------------------------------------------------- lifecycle

    def destroy_node(self) -> None:
        """
        Cancel this node's timers, then destroy it.

        The retry timer outlives every chain by design, so it is the one thing
        that has to be stopped explicitly rather than left to the garbage
        collector. It is read defensively, because ``rclpy.shutdown`` destroys
        whatever nodes a half-constructed instance is already registered with:
        a startup failure part way through ``__init__`` has to exit on the
        error that caused it, not on an ``AttributeError`` from here.
        """
        for name in ('_service_retry_timer', '_respawn_timer'):
            timer = getattr(self, name, None)
            if timer is not None:
                timer.cancel()
        super().destroy_node()


def _service_error(future: Future) -> str | None:
    """
    Return a short description of a failed service call, or ``None``.

    Also marks the exception as retrieved, which keeps rclpy from printing an
    "exception was never retrieved" warning to stderr.
    """
    exception = future.exception()
    if exception is None:
        return None
    return f'{type(exception).__name__}: {exception}'


def main(args: list[str] | None = None) -> None:
    """Run the spawner node until interrupted."""
    overrides = parameter_overrides(sys.argv[1:] if args is None else args)
    try:
        # The pair is built and validated before anything is named after it, so
        # that an unusable pair is one clear line rather than an rclpy
        # complaint about a node name this code had no business deriving yet.
        pair = RescuePair(
            resolve(overrides.get('rescuer_name'), DEFAULT_RESCUER_NAME),
            resolve(overrides.get('victim_name'), DEFAULT_VICTIM_NAME))
    except ValueError as exc:
        get_logger(STARTUP_LOG_NAME).error(f'cannot start: {exc}')
        raise SystemExit(2) from exc
    node_name = overrides.get('node_name') or pair.spawner_node_name

    rclpy.init(args=args)
    node: SpawnerNode | None = None
    try:
        node = SpawnerNode(node_name)
        while rclpy.ok():
            rclpy.spin_once(node)
    except (ValueError, ParameterException, InvalidNodeNameException) as exc:
        # A mistyped parameter value or an unusable node_name is a startup
        # mistake, not a crash: the rclpy exceptions are not ValueErrors, so
        # they are named here rather than left to become a traceback.
        get_logger(STARTUP_LOG_NAME).error(f'cannot start: {exc}')
        raise SystemExit(2) from exc
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RCLError:
        # A signal can arrive inside the blocking wait, invalidating the
        # context after the rclpy.ok() check above. Treat it as shutdown.
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
