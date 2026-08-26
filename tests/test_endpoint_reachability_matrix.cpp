#include "therapy_robot/collision.hpp"
#include "therapy_robot/endpoint_positioning.hpp"
#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <cmath>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace {

struct ReachabilityCase {
  std::string name;
  therapy_robot::Pose target;
  bool expected_reachable = false;
  std::string expected_reason_fragment;
};

ReachabilityCase joint_target(const std::string& name,
                              const therapy_robot::JointState& joints,
                              bool expected_reachable,
                              std::string expected_reason_fragment = {}) {
  return {name, therapy_robot::forward_kinematics(joints), expected_reachable,
          std::move(expected_reason_fragment)};
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 2) {
    std::cerr << "usage: test_endpoint_reachability_matrix "
                 "enclosure-collision.csv\n";
    return 2;
  }

  therapy_robot::SharedState limits;
  therapy_robot::initialize_defaults(limits);
  const auto collision = therapy_robot::load_collision_config(argv[1], true);
  constexpr double kDeg = 3.14159265358979323846 / 180.0;

  // Use the documented high-plane K0 height and a complete five-axis source
  // pose. This is software-only path validation; it does not authorize or
  // issue a motor command.
  const therapy_robot::JointState source{0.3131, 0.0, 0.0, 0.0, 0.0};
  const std::vector<ReachabilityCase> cases{
      joint_target("high-center",
                   {0.3131, 0.0, 0.0, 0.0, 0.0}, true),
      joint_target("high-left-15",
                   {0.3131, -15.0 * kDeg, 0.0, 0.0, 0.0}, true),
      joint_target("high-right-15",
                   {0.3131, 15.0 * kDeg, 0.0, 0.0, 0.0}, true),
      joint_target("high-left-30",
                   {0.3131, -30.0 * kDeg, 0.0, 0.0, 0.0}, true),
      joint_target("high-right-30",
                   {0.3131, 30.0 * kDeg, 0.0, 0.0, 0.0}, true),
      joint_target("high-left-45-elbow-15",
                   {0.3131, -45.0 * kDeg, 15.0 * kDeg, 0.0, 0.0}, true),
      joint_target("high-right-45-elbow-minus-15",
                   {0.3131, 45.0 * kDeg, -15.0 * kDeg, 0.0, 0.0}, true),
      joint_target("high-left-60-elbow-30",
                   {0.3131, -60.0 * kDeg, 30.0 * kDeg, 0.0, 0.0}, true),
      joint_target("high-right-60-elbow-minus-30",
                   {0.3131, 60.0 * kDeg, -30.0 * kDeg, 0.0, 0.0}, true),
      joint_target("high-right-wrist-tilt",
                   {0.3131, 30.0 * kDeg, -20.0 * kDeg,
                    -15.0 * kDeg, 20.0 * kDeg}, true),
      joint_target("high-right-elbow-wrist",
                   {0.3131, 20.0 * kDeg, -45.0 * kDeg,
                    -10.0 * kDeg, 30.0 * kDeg}, true),
      joint_target("collision-left-wrist",
                   {0.3131, -30.0 * kDeg, 20.0 * kDeg,
                    15.0 * kDeg, -20.0 * kDeg}, false,
                   "collision boundary"),
      joint_target("collision-left-elbow-wrist",
                   {0.3131, -20.0 * kDeg, 45.0 * kDeg,
                    10.0 * kDeg, -30.0 * kDeg}, false,
                   "collision boundary"),
      {"outside-workspace", {2.0, 0.0, 0.80, 0.0, 0.0, 0.0}, false,
       "IK rejected target"},
  };

  std::size_t reachable = 0;
  std::size_t rejected = 0;
  bool valid = true;
  std::cout << std::setprecision(9);
  for (const auto& test_case : cases) {
    const auto result = therapy_robot::preflight_endpoint_positioning(
        source, test_case.target, limits, collision);
    if (result.ok) {
      ++reachable;
    } else {
      ++rejected;
    }
    const bool reachability_matches =
        result.ok == test_case.expected_reachable;
    const bool reason_matches = test_case.expected_reason_fragment.empty() ||
        result.reason.find(test_case.expected_reason_fragment) !=
            std::string::npos;
    valid = valid && reachability_matches && reason_matches;
    std::cout << "POINT name=" << test_case.name
              << " reachable=" << (result.ok ? "true" : "false")
              << " expected="
              << (test_case.expected_reachable ? "true" : "false")
              << " x_m=" << test_case.target.x_m
              << " y_m=" << test_case.target.y_m
              << " z_m=" << test_case.target.z_m
              << " reason=\"" << result.reason << "\"\n";
    if (!reachability_matches || !reason_matches) {
      std::cerr << "FAILED: " << test_case.name
                << " did not match the expected reachability/reason\n";
    }
  }

  std::cout << "SUMMARY total=" << cases.size()
            << " reachable=" << reachable
            << " rejected=" << rejected
            << " serial_accessed=false"
            << " d405_accessed=false"
            << " motor_command_generated=false\n";
  return valid ? 0 : 1;
}
