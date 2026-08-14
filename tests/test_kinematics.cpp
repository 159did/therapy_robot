#include "therapy_robot/kinematics.hpp"

#include <array>
#include <cmath>
#include <cstdlib>
#include <iostream>

using therapy_robot::JointState;
using therapy_robot::Pose;

namespace {
constexpr double kPi = 3.14159265358979323846;

double angle_error(double a, double b) {
  return std::abs(std::atan2(std::sin(a - b), std::cos(a - b)));
}

bool near(double a, double b, double tolerance) {
  return std::abs(a - b) <= tolerance;
}

bool verify_roundtrip(const JointState& q) {
  const Pose pose = therapy_robot::forward_kinematics(q);
  const auto ik = therapy_robot::inverse_kinematics(pose, q);
  if (!ik.ok) {
    std::cerr << "IK rejected an FK pose: " << ik.error << '\n';
    return false;
  }
  const Pose recovered = therapy_robot::forward_kinematics(ik.joints);
  const double position_error = std::sqrt(
      std::pow(recovered.x_m - pose.x_m, 2) +
      std::pow(recovered.y_m - pose.y_m, 2) +
      std::pow(recovered.z_m - pose.z_m, 2));
  if (position_error > 2e-5 ||
      angle_error(recovered.rx_rad, pose.rx_rad) > 2e-5 ||
      angle_error(recovered.ry_rad, pose.ry_rad) > 2e-5) {
    std::cerr << "FK/IK residual too large: " << position_error << " m\n";
    return false;
  }
  // A no-motion Cartesian target must stay on the current IK branch.
  if (!near(ik.joints.k0_m, q.k0_m, 2e-4) ||
      angle_error(ik.joints.k1_rad, q.k1_rad) > 2e-3 ||
      angle_error(ik.joints.k2_rad, q.k2_rad) > 2e-3 ||
      angle_error(ik.joints.k3_rad, q.k3_rad) > 2e-3 ||
      angle_error(ik.joints.k4_rad, q.k4_rad) > 2e-3) {
    std::cerr << "IK changed branch for an unchanged endpoint\n";
    return false;
  }
  return true;
}
}  // namespace

int main() {
  const std::array<JointState, 4> samples{{
      {0.0, 0.0, 0.0, 0.0, 0.0},
      {0.005, 10.0 * kPi / 180.0, -20.0 * kPi / 180.0,
       5.0 * kPi / 180.0, -8.0 * kPi / 180.0},
      {0.010, -25.0 * kPi / 180.0, 35.0 * kPi / 180.0,
       -10.0 * kPi / 180.0, 15.0 * kPi / 180.0},
      {0.015, 40.0 * kPi / 180.0, -45.0 * kPi / 180.0,
       15.0 * kPi / 180.0, 20.0 * kPi / 180.0},
  }};

  for (const auto& sample : samples) {
    if (!verify_roundtrip(sample)) return EXIT_FAILURE;
  }

  const Pose zero = therapy_robot::forward_kinematics({});
  if (!near(zero.x_m, 0.0, 1e-9) ||
      !near(zero.y_m, 0.232, 1e-9) ||
      !near(zero.z_m, 0.4769, 1e-9)) {
    std::cerr << "Existing coordinate frame changed unexpectedly\n";
    return EXIT_FAILURE;
  }
  std::cout << "kinematics roundtrip and existing +Y zero frame verified\n";
  return EXIT_SUCCESS;
}
