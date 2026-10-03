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
Node holding the IDLE/RESCUE state machine for one rescue pair.

The manager watches the rescuer and victim poses of its pair and does three
things: turn the background red when they come within ``attach_distance``,
drag the victim along with the rescuer while the rescue is running, and turn
the background back to the default when the victim reaches the start zone.

The whole FSM runs on one control timer, so there is a single evaluation rate,
no reentrancy, and no transition can see half of a pose pair. The pose
callbacks only cache the newest message.

One deviation from a plain IDLE/RESCUE machine is deliberate and documented
where it is decided: IDLE holds still for a moment after a rescue, because at
SUCCESS the victim is still on the rescuer and attaching straight back onto it
would restart the same rescue. The hold and its release live in
:mod:`rescue_turtle.states`, as a pure function over the two poses.
"""

import sys
import time

import rclpy
from rclpy._rclpy_pybind11 import RCLError
from rclpy.exceptions import InvalidNodeNameException
from rclpy.exceptions import ParameterException
from rclpy.executors import ExternalShutdownException
from rclpy.logging import get_logger
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rclpy.task import Future
from std_msgs.msg import String
from std_srvs.srv import Empty
from turtlesim_msgs.msg import Pose
from turtlesim_msgs.srv import TeleportAbsolute

from .arg_overrides import parameter_overrides
from .geometry import distance
from .geometry import in_zone
from .geometry import Point
from .rescue_pair import DEFAULT_RESCUER_NAME
from .rescue_pair import DEFAULT_VICTIM_NAME
from .rescue_pair import RescuePair
from .rescue_pair import resolve
from .states import hold_release_reason
from .states import RescueState
from .validation import manager_configuration_errors

#: Zone defaults, half-width 0.6 around the measured start pose.
DEFAULT_ZONE_MIN = 4.944
DEFAULT_ZONE_MAX = 6.144

#: Start pose and spawn clearance, measured from a stock turtlesim.
DEFAULT_START_X = 5.544444
DEFAULT_START_Y = 5.544444
DEFAULT_MIN_SPAWN_DISTANCE = 2.0

#: Background colours. Aqua blue at rest, lime green while rescuing: the rescue
#: is the good news, so it is not the colour a mistake looks like.
DEFAULT_COLOR = (0, 200, 255)
DEFAULT_RESCUE_COLOR = (0, 255, 0)

#: Node holding the background parameters, and their names on it.
DEFAULT_TURTLESIM_NODE = 'turtlesim'
BACKGROUND_R = 'background_r'
BACKGROUND_G = 'background_g'
BACKGROUND_B = 'background_b'
BACKGROUND_NAMES = (BACKGROUND_R, BACKGROUND_G, BACKGROUND_B)

#: Queue depth for the pose subscriptions and the status publisher.
QUEUE_DEPTH = 10

#: The status topic keeps its last samples, so a late subscriber still sees
#: the idle published at startup. See the publisher in ``__init__``.
STATUS_QOS = QoSProfile(
    history=HistoryPolicy.KEEP_LAST,
    depth=QUEUE_DEPTH,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)

#: Logger name for a failure that happens before a node name can be derived.
STARTUP_LOG_NAME = 'rescue_turtle_rescue_manager'


class RescueManagerNode(Node):
    """The IDLE/RESCUE state machine for exactly one :class:`RescuePair`."""

    def __init__(self, node_name: str) -> None:
        """Read every knob from parameters, then start the control timer."""
        super().__init__(node_name)

        self._rescuer_name = self._declare_str('rescuer_name', DEFAULT_RESCUER_NAME)
        self._victim_name = self._declare_str('victim_name', DEFAULT_VICTIM_NAME)
        self._pair = RescuePair(self._rescuer_name, self._victim_name)
        self._check_node_name(self._declare_str('node_name', ''))

        self._rescuer_pose_topic = resolve(
            self._declare_str('rescuer_pose_topic', ''), self._pair.rescuer_pose_topic)
        self._victim_pose_topic = resolve(
            self._declare_str('victim_pose_topic', ''), self._pair.victim_pose_topic)
        self._teleport_service = resolve(
            self._declare_str('victim_teleport_service', ''),
            self._pair.victim_teleport_service)
        self._status_topic = resolve(
            self._declare_str('status_topic', ''), self._pair.status_topic)
        self._clear_service = self._declare_str('clear_service', '/clear')
        self._turtlesim_node = self._declare_str('turtlesim_node', DEFAULT_TURTLESIM_NODE)

        self._attach_distance = self._declare_float('attach_distance', 0.7)
        self._follow_rate_hz = self._declare_float('follow_rate_hz', 20.0)
        self._pose_timeout_s = self._declare_float('pose_timeout_s', 1.0)
        self._service_wait_timeout_s = self._declare_float('service_wait_timeout_s', 5.0)
        self._zone_x_min = self._declare_float('start_zone_x_min', DEFAULT_ZONE_MIN)
        self._zone_x_max = self._declare_float('start_zone_x_max', DEFAULT_ZONE_MAX)
        self._zone_y_min = self._declare_float('start_zone_y_min', DEFAULT_ZONE_MIN)
        self._zone_y_max = self._declare_float('start_zone_y_max', DEFAULT_ZONE_MAX)

        self._rescue_color = self._declare_color('rescue_color', DEFAULT_RESCUE_COLOR)
        self._default_color = self._declare_color('default_color', DEFAULT_COLOR)
        self._status_idle = self._declare_str('status_idle', 'idle')
        self._status_rescue = self._declare_str('status_rescue', 'rescue_started')
        self._status_complete = self._declare_str('status_complete', 'rescue_complete')
        self._validate()

        # Instance state only: two managers in one process, or two processes on
        # the machine, cannot see or disturb each other's copy of any of it.
        self._rescuer_pose: tuple[Pose, float] | None = None
        self._victim_pose: tuple[Pose, float] | None = None
        self._state = RescueState.IDLE
        self._teleport_in_flight = False
        self._awaiting_respawn = False
        self._pose_at_success: Point | None = None
        self._rescue_started_at = 0.0

        # TRANSIENT_LOCAL, so the idle published at startup reaches a subscriber
        # that asks for the status later. The status topic is the package's main
        # testing hook, and on a volatile publisher the startup idle is simply
        # dropped when nothing is listening yet, which leaves a late
        # `ros2 topic echo` with nothing to see. A volatile subscriber, which
        # is what the spawner is, is still compatible with it and still gets
        # every later status.
        self._status_pub = self.create_publisher(
            String, self._status_topic, STATUS_QOS)
        self._rescuer_pose_sub = self.create_subscription(
            Pose, self._rescuer_pose_topic, self._on_rescuer_pose, QUEUE_DEPTH)
        self._victim_pose_sub = self.create_subscription(
            Pose, self._victim_pose_topic, self._on_victim_pose, QUEUE_DEPTH)
        self._teleport_client = self.create_client(
            TeleportAbsolute, self._teleport_service)
        self._clear_client = self.create_client(Empty, self._clear_service)
        self._param_client = AsyncParameterClient(self, self._turtlesim_node)

        self.get_logger().info(
            f'rescue manager for {self._pair.slug}: attaching within '
            f'{self._attach_distance} m, status topic {self._status_topic}, '
            f'control rate {self._follow_rate_hz} Hz'
        )
        self._await_parameter_services()
        # This node owns the background colour, so it starts from the default
        # rather than inheriting whatever a previous run left on the window.
        self._set_background(self._default_color, 'default')
        self._publish_status(self._status_idle)
        self._timer = self.create_timer(1.0 / self._follow_rate_hz, self._on_control_tick)

    # ------------------------------------------------------------------ setup

    def _declare_str(self, name: str, default: str) -> str:
        """Declare a string parameter and return its value."""
        self.declare_parameter(name, default)
        return str(self.get_parameter(name).value)

    def _declare_float(self, name: str, default: float) -> float:
        """Declare a float parameter and return its value."""
        self.declare_parameter(name, default)
        return float(self.get_parameter(name).value)

    def _declare_color(self, prefix: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
        """Declare the ``<prefix>_r/g/b`` parameters and return the triple."""
        red = self._declare_int(f'{prefix}_r', default[0])
        green = self._declare_int(f'{prefix}_g', default[1])
        blue = self._declare_int(f'{prefix}_b', default[2])
        return red, green, blue

    def _declare_int(self, name: str, default: int) -> int:
        """Declare an integer parameter and return its value."""
        self.declare_parameter(name, default)
        return int(self.get_parameter(name).value)

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
        Reject parameter values the state machine cannot work with.

        :raises ValueError: on a bad distance, rate, timeout, zone or colour,
            so that :func:`main` can log it and exit instead of a node that
            attaches on the wrong terms. The rules themselves are pure
            functions in :mod:`rescue_turtle.validation`, so they are unit
            tested.
        """
        errors = manager_configuration_errors(
            attach_distance=self._attach_distance,
            follow_rate_hz=self._follow_rate_hz,
            pose_timeout_s=self._pose_timeout_s,
            service_wait_timeout_s=self._service_wait_timeout_s,
            zone=(self._zone_x_min, self._zone_x_max,
                  self._zone_y_min, self._zone_y_max),
            rescue_color=self._rescue_color,
            default_color=self._default_color,
        )
        if errors:
            raise ValueError(errors[0])

    def _await_parameter_services(self) -> None:
        """Wait a bounded time for the background parameters to be settable."""
        if self._param_client.wait_for_services(timeout_sec=self._service_wait_timeout_s):
            return
        self.get_logger().error(
            f'the parameter services of {self._turtlesim_node!r} are not available '
            f'after {self._service_wait_timeout_s} s; the background will not change'
        )

    # ------------------------------------------------------------------- poses

    def _on_rescuer_pose(self, message: Pose) -> None:
        """
        Cache the newest rescuer pose and when it arrived.

        ``turtlesim_msgs/msg/Pose`` carries no header, so the stamp is local
        arrival time, which is all the staleness guard needs.
        """
        self._rescuer_pose = (message, time.monotonic())

    def _on_victim_pose(self, message: Pose) -> None:
        """Cache the newest victim pose and when it arrived."""
        self._victim_pose = (message, time.monotonic())

    def _fresh_pose(self, cached: tuple[Pose, float] | None) -> Pose | None:
        """
        Return a cached pose only while it is newer than the stale timeout.

        A pose that has gone stale counts as absent, which is what keeps the
        gap while the victim is killed and respawned from producing a bogus
        attach or a bogus success.
        """
        if cached is None:
            return None
        pose, stamp = cached
        if time.monotonic() - stamp > self._pose_timeout_s:
            return None
        return pose

    # ----------------------------------------------------------- state machine

    def _on_control_tick(self) -> None:
        """Evaluate the whole state machine once, from the newest poses."""
        if self._state is RescueState.IDLE:
            self._update_idle()
        else:
            self._update_rescue()

    def _update_idle(self) -> None:
        """Attach when the pair is close enough, unless a respawn is pending."""
        rescuer = self._fresh_pose(self._rescuer_pose)
        victim = self._fresh_pose(self._victim_pose)
        if self._awaiting_respawn:
            self._release_hold(rescuer, victim)
            return
        if rescuer is None or victim is None:
            return
        separation = distance(rescuer.x, rescuer.y, victim.x, victim.y)
        if separation >= self._attach_distance:
            return

        self._state = RescueState.RESCUE
        self._rescue_started_at = time.monotonic()
        self._set_background(self._rescue_color, 'rescue')
        #self._call_clear()
        self._set_safety_zone()
        self._publish_status(self._status_rescue)
        self.get_logger().info(
            f'rescue started: the pair is {separation:.3f} m apart, inside the '
            f'{self._attach_distance} m attach distance'
        )

    def _release_hold(
        self, rescuer: Pose | None, victim: Pose | None
    ) -> None:
        """
        Let IDLE attach again as soon as the rescued victim is no longer there.

        The decision itself is the pure predicate
        :func:`rescue_turtle.states.hold_release_reason`, which is judged
        against the pose recorded at the success rather than against the
        geometry of the pair. Judging it geometrically does not work: the hold
        exists precisely because the pair is still close together, and
        separation can only be reached when ``attach_distance`` is smaller than
        the distance a fresh victim spawns at, which is a legal pair of
        parameters and would leave the game stopped for good with nothing in the
        log to explain it.
        """
        reason = hold_release_reason(
            _point(rescuer), _point(victim), self._pose_at_success, self._attach_distance)
        if reason is None:
            return
        self._awaiting_respawn = False
        self._pose_at_success = None
        self.get_logger().info(
            f'releasing the post-success hold, {reason.value}; attaching again '
            'from now on'
        )

    def _update_rescue(self) -> None:
        """Finish the rescue in the start zone, otherwise follow the rescuer."""
        victim = self._fresh_pose(self._victim_pose)
        if victim is None:
            return
        if in_zone(victim.x, victim.y,
                   self._zone_x_min, self._zone_x_max, self._zone_y_min, self._zone_y_max):
            self._finish_rescue(victim)
            return
        self._follow_rescuer()

    def _finish_rescue(self, victim: Pose) -> None:
        """
        Log and publish the success, then go back to IDLE.

        SUCCESS is an event, not a state: the respawn belongs to the spawner,
        and the transition is immediate.

        The victim is still sitting where the rescuer brought it, so IDLE
        attaches again on its very next tick and the game loops on the same
        turtle. The pose is therefore recorded here and IDLE holds until the
        live victim is somewhere else, which is the spawner's respawn. The hold
        and its release are logged, so a hold that never ends is visible rather
        than silent.
        """
        duration = time.monotonic() - self._rescue_started_at
        self._state = RescueState.IDLE
        self._awaiting_respawn = True
        self._pose_at_success = (victim.x, victim.y)
        self._set_background(self._default_color, 'default')
        self._call_clear()
        self._publish_status(self._status_complete)
        self.get_logger().info(
            f'SUCCESS: {self._pair.victim_name!r} reached the start zone at '
            f'x={victim.x:.3f} y={victim.y:.3f} after {duration:.2f} s'
        )
        self.get_logger().info(
            f'holding IDLE until {self._pair.victim_name!r} has been replaced: a '
            'victim still on the rescuer is one the spawner has yet to respawn'
        )

    def _follow_rescuer(self) -> None:
        """Teleport the victim onto the rescuer's pose, one request in flight."""
        if self._teleport_in_flight:
            return
        if not self._teleport_client.service_is_ready():
            return
        rescuer = self._fresh_pose(self._rescuer_pose)
        if rescuer is None:
            return
        request = TeleportAbsolute.Request()
        request.x = rescuer.x
        request.y = rescuer.y
        request.theta = rescuer.theta
        self._teleport_in_flight = True
        self._teleport_client.call_async(request).add_done_callback(self._on_teleport_done)

    def _on_teleport_done(self, future: Future) -> None:
        """Release the in-flight flag and report a failed teleport."""
        self._teleport_in_flight = False
        error = _service_error(future)
        if error is not None:
            self.get_logger().warning(
                f'{self._teleport_service} failed ({error}), trying again on the '
                'next control tick'
            )

    # -------------------------------------------------------------- signalling

    def _call_clear(self) -> None:
        """Clear the canvas so the new background colour is what is drawn."""
        self._clear_client.call_async(Empty.Request()).add_done_callback(self._on_clear_done)

    def _on_clear_done(self, future: Future) -> None:
        """Report a failed clear; the colour is set either way."""
        error = _service_error(future)
        if error is not None:
            self.get_logger().warning(f'{self._clear_service} failed: {error}')

    def _set_background(self, color: tuple[int, int, int], role: str) -> None:
        """
        Set the background parameters of the turtlesim node.

        Goes through the parameter client rather than the raw parameter
        services, so the request shape and the result checking are rclpy's.
        """
        parameters = [
            Parameter(name, Parameter.Type.INTEGER, value)
            for name, value in zip(BACKGROUND_NAMES, color)
        ]
        future = self._param_client.set_parameters(parameters)
        future.add_done_callback(
            lambda done: self._on_background_set(done, role))

    def _on_background_set(self, future: Future, role: str) -> None:
        """Log the outcome of a background parameter request."""
        error = _service_error(future)
        if error is not None:
            self.get_logger().error(
                f'could not set the {role} background on {self._turtlesim_node!r}: '
                f'{error}'
            )
            return
        response = future.result()
        if response is None:
            return
        for result in response.results:
            if not result.successful:
                self.get_logger().warning(
                    f'{self._turtlesim_node!r} rejected a {role} background '
                    f'component: {result.reason}'
                )

    def _publish_status(self, status: str) -> None:
        """Publish one status string on the pair-scoped status topic."""
        message = String()
        message.data = status
        self._status_pub.publish(message)


def _point(pose: Pose | None) -> Point | None:
    """Return a pose as the two coordinates the state machine reasons about."""
    return None if pose is None else (pose.x, pose.y)


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
    """Run the rescue manager node until interrupted."""
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
    node_name = overrides.get('node_name') or pair.node_name

    rclpy.init(args=args)
    node: RescueManagerNode | None = None
    try:
        node = RescueManagerNode(node_name)
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
