#pragma once

#include "therapy_robot/collision.hpp"
#include "therapy_robot/joint_limits.hpp"
#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <array>
#include <string>

namespace therapy_robot {

struct EndpointPositioningPreflight {
  bool ok = false;
  std::string reason;
  JointState target_joints{};
  std::array<int64_t, kAxisCount> target_native{};
  CollisionCheck collision{};
};

// Offline-only route validation. source must be a complete captured joint
// state; callers must not manufacture a SAFE_HIGH pose from a K0 height alone.
EndpointPositioningPreflight preflight_endpoint_positioning(
    const JointState& source, const Pose& target, const SharedState& limits,
    const CollisionConfig& collision_config,
    const RobotGeometry& geometry = default_geometry());

struct EndpointPositioningMeasurement {
  std::string sample_id;
  std::string side;
  Pose target{};
  JointState source{};
  JointState actual{};
};

struct EndpointPositioningResult {
  bool accepted = false;
  std::string reason;
  EndpointPositioningPreflight preflight{};
  Pose actual_pose{};
  double target_error_m = 0.0;
};

EndpointPositioningResult evaluate_endpoint_positioning_measurement(
    const EndpointPositioningMeasurement& measurement,
    const SharedState& limits, const CollisionConfig& collision_config,
    const RobotGeometry& geometry = default_geometry());

}  // namespace therapy_robot
