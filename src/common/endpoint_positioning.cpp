#include "therapy_robot/endpoint_positioning.hpp"

#include <cmath>

namespace therapy_robot {
namespace {

bool finite_pose(const Pose& pose) {
  return std::isfinite(pose.x_m) && std::isfinite(pose.y_m) &&
         std::isfinite(pose.z_m) && std::isfinite(pose.rx_rad) &&
         std::isfinite(pose.ry_rad) && std::isfinite(pose.rz_rad);
}

double position_distance(const Pose& lhs, const Pose& rhs) {
  return std::hypot(std::hypot(lhs.x_m - rhs.x_m, lhs.y_m - rhs.y_m),
                    lhs.z_m - rhs.z_m);
}

}  // namespace

EndpointPositioningPreflight preflight_endpoint_positioning(
    const JointState& source, const Pose& target, const SharedState& limits,
    const CollisionConfig& collision_config, const RobotGeometry& geometry) {
  EndpointPositioningPreflight output{};
  std::array<int64_t, kAxisCount> source_native{};
  std::string reason;
  if (!native_targets_from_joints(limits, source, source_native, reason)) {
    output.reason = "source joints rejected: " + reason;
    return output;
  }
  if (!finite_pose(target)) {
    output.reason = "target pose contains a non-finite value";
    return output;
  }
  if (!collision_config.configured || !collision_config.enabled ||
      collision_config.obstacles.empty()) {
    output.reason = "collision configuration is not required-and-enabled";
    return output;
  }
  const auto target_result = inverse_kinematics(target, source, geometry);
  if (!target_result.ok) {
    output.reason = "IK rejected target: " + target_result.error;
    return output;
  }
  output.target_joints = target_result.joints;
  if (!native_targets_from_joints(limits, output.target_joints,
                                  output.target_native, reason)) {
    output.reason = "target joints rejected: " + reason;
    return output;
  }
  const auto source_collision =
      check_robot_configuration(source, collision_config, geometry);
  if (!source_collision.ok || !source_collision.checked) {
    output.collision = source_collision;
    output.reason = "source collision check rejected: " + source_collision.reason;
    return output;
  }
  output.collision = check_endpoint_motion(source, output.target_joints,
                                           collision_config, geometry);
  if (!output.collision.ok || !output.collision.checked) {
    output.reason = "endpoint path rejected: " + output.collision.reason;
    return output;
  }
  output.ok = true;
  output.reason = "ok";
  return output;
}

EndpointPositioningResult evaluate_endpoint_positioning_measurement(
    const EndpointPositioningMeasurement& measurement,
    const SharedState& limits, const CollisionConfig& collision_config,
    const RobotGeometry& geometry) {
  EndpointPositioningResult output{};
  output.preflight = preflight_endpoint_positioning(
      measurement.source, measurement.target, limits, collision_config, geometry);
  if (!output.preflight.ok) {
    output.reason = output.preflight.reason;
    return output;
  }
  std::array<int64_t, kAxisCount> actual_native{};
  std::string reason;
  if (!native_targets_from_joints(limits, measurement.actual, actual_native, reason)) {
    output.reason = "actual feedback rejected: " + reason;
    return output;
  }
  const auto actual_collision =
      check_robot_configuration(measurement.actual, collision_config, geometry);
  if (!actual_collision.ok || !actual_collision.checked) {
    output.reason = "actual feedback collision check rejected: " +
                    actual_collision.reason;
    return output;
  }
  output.actual_pose = forward_kinematics(measurement.actual, geometry);
  output.target_error_m = position_distance(output.actual_pose, measurement.target);
  output.accepted = true;
  output.reason = "ok";
  return output;
}

}  // namespace therapy_robot
