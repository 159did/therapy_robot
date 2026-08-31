#pragma once

#include <array>
#include <string>

namespace therapy_robot {

struct RobotGeometry {
  double base_height_m = 0.710;
  double upper_arm_m = 0.580;
  double forearm_m = 0.229;
  double wrist_forward_offset_m = 0.119;
  double forearm_drop_m = 0.080;
  double tool_length_m = 0.1531;
  double camera_mount_offset_y_m = -0.217;
  double camera_mount_offset_z_m = 0.1452;
};

struct JointState {
  double k0_m = 0.0;
  double k1_rad = 0.0;
  double k2_rad = 0.0;
  double k3_rad = 0.0;
  double k4_rad = 0.0;
};

struct Pose {
  double x_m = 0.0;
  double y_m = 0.0;
  double z_m = 0.0;
  double rx_rad = 0.0;
  double ry_rad = 0.0;
  double rz_rad = 0.0;
};

struct Point3 {
  double x_m = 0.0;
  double y_m = 0.0;
  double z_m = 0.0;
};

// Named points for every moving link.  Collision checking and visualization
// should derive their geometry from this result instead of maintaining a
// second copy of the forward-kinematics equations.
struct RobotLinkPoints {
  Point3 base{};
  Point3 shoulder{};
  Point3 upper_arm_end{};
  Point3 forearm_start{};
  Point3 forearm_end{};
  Point3 wrist_end{};
  Point3 tool_tip{};
  Point3 k2_axis_a{};
  Point3 k2_axis_b{};
  Point3 k3_axis_a{};
  Point3 k3_axis_b{};
  Point3 k4_axis_a{};
  Point3 k4_axis_b{};
};

struct IkResult {
  bool ok = false;
  JointState joints{};
  std::string error;
};

RobotGeometry default_geometry();
RobotLinkPoints robot_link_points(const JointState& joints,
                                  const RobotGeometry& geometry = default_geometry());
Pose forward_kinematics(const JointState& joints, const RobotGeometry& geometry = default_geometry());
IkResult inverse_kinematics(const Pose& target, const RobotGeometry& geometry = default_geometry());
// Resolve redundant IK solutions near the supplied physical joint state. This
// is the required overload for jog/interactive motion: a small Cartesian
// command must not switch to a distant elbow/wrist branch.
IkResult inverse_kinematics(const Pose& target, const JointState& preferred,
                            const RobotGeometry& geometry = default_geometry());
// Solve IK while keeping the forearm planar yaw fixed.  The returned K2
// compensates K1 so q.k1 + q.k2 + pi remains equal to forearm_yaw_rad.
IkResult inverse_kinematics_fixed_forearm_yaw(
    const Pose& target, double forearm_yaw_rad,
    const JointState& preferred,
    const RobotGeometry& geometry = default_geometry());
std::array<double, 3> axis_from_rx_ry(double rx_rad, double ry_rad);
std::array<double, 2> rx_ry_from_axis(const std::array<double, 3>& axis);

}
