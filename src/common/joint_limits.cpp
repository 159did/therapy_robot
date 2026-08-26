#include "therapy_robot/joint_limits.hpp"

#include <cmath>

namespace therapy_robot {

bool native_targets_from_joints(const SharedState& state,
                                const JointState& joints,
                                std::array<int64_t, kAxisCount>& requested,
                                std::string& reason) {
  constexpr double kRadToDeg = 180.0 / 3.14159265358979323846;
  const std::array<double, kAxisCount> display{{
      joints.k0_m * 1000.0,
      joints.k1_rad * kRadToDeg,
      joints.k2_rad * kRadToDeg,
      joints.k3_rad * kRadToDeg,
      joints.k4_rad * kRadToDeg,
  }};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    if (!std::isfinite(display[idx])) {
      reason = "K" + std::to_string(idx) + " joint value is not finite";
      return false;
    }
    const auto& axis = state.axis_map[idx];
    if (!std::isfinite(axis.motor_native_to_gui_display) ||
        std::abs(axis.motor_native_to_gui_display) < 1e-12) {
      reason = "K" + std::to_string(idx) + " conversion scale is invalid";
      return false;
    }
    requested[idx] = static_cast<int64_t>(std::llround(
        display[idx] / axis.motor_native_to_gui_display));
    if (requested[idx] < axis.min_motor_native ||
        requested[idx] > axis.max_motor_native) {
      reason = "IK target exceeds K" + std::to_string(idx) + " soft limit";
      return false;
    }
  }
  reason = "ok";
  return true;
}

}  // namespace therapy_robot
