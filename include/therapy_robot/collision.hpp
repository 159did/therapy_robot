#pragma once

#include "therapy_robot/kinematics.hpp"

#include <string>
#include <vector>

namespace therapy_robot {

struct CollisionBox {
  std::string name;
  Point3 min{};
  Point3 max{};
};

struct RobotCollisionEnvelope {
  double lift_radius_m = 0.055;
  double upper_arm_radius_m = 0.060;
  double elbow_radius_m = 0.055;
  double forearm_radius_m = 0.060;
  double wrist_radius_m = 0.050;
  double tool_radius_m = 0.040;
};

struct CollisionConfig {
  bool configured = false;
  bool enabled = false;
  bool required = false;
  std::string source_path;
  double safety_margin_m = 0.020;
  double lift_step_m = 0.005;
  double joint_step_rad = 0.017453292519943295;  // 1 degree
  RobotCollisionEnvelope envelope{};
  std::vector<CollisionBox> obstacles;
};

struct CollisionCheck {
  bool ok = true;
  bool checked = false;
  std::string reason = "collision boundary disabled";
  std::string link_name;
  std::string obstacle_name;
  double path_fraction = 0.0;
};

CollisionConfig load_collision_config(const std::string& path, bool required = false);
CollisionConfig collision_config_from_environment();

CollisionCheck check_robot_configuration(
    const JointState& joints,
    const CollisionConfig& config,
    const RobotGeometry& geometry = default_geometry());

CollisionCheck check_robot_motion(
    const JointState& from,
    const JointState& to,
    const CollisionConfig& config,
    const RobotGeometry& geometry = default_geometry());

// Endpoint commands may cross the enclosure projection only above the cabinet,
// or during a pure K0 lift inside the storage slot.  All other sampled forearm
// positions keep at least 30 mm of outside clearance from that projection.
CollisionCheck check_endpoint_motion(
    const JointState& from,
    const JointState& to,
    const CollisionConfig& config,
    const RobotGeometry& geometry = default_geometry());

}  // namespace therapy_robot
