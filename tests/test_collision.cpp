#include "therapy_robot/collision.hpp"

#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace therapy_robot;

namespace {

void expect(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

CollisionConfig base_config() {
  CollisionConfig config;
  config.configured = true;
  config.enabled = true;
  config.safety_margin_m = 0.0;
  config.lift_step_m = 0.005;
  config.joint_step_rad = 1.0 * 3.14159265358979323846 / 180.0;
  return config;
}

CollisionConfig measured_enclosure_config() {
  CollisionConfig config = base_config();
  config.safety_margin_m = 0.001;
  config.lift_step_m = 0.002;
  config.joint_step_rad = 0.5 * 3.14159265358979323846 / 180.0;
  config.envelope.lift_radius_m = 0.055;
  config.envelope.upper_arm_radius_m = 0.060;
  config.envelope.elbow_radius_m = 0.044;
  config.envelope.forearm_radius_m = 0.0535;
  config.envelope.wrist_radius_m = 0.050;
  config.envelope.tool_radius_m = 0.040;
  config.obstacles = {
      {"enclosure_left", {-0.1805, -0.1155, -0.0125},
       {-0.0750, 0.6500, 0.7475}},
      {"enclosure_right", {0.0750, -0.1155, -0.0125},
       {0.1805, 0.6500, 0.7475}},
      {"enclosure_rear", {-0.0750, -0.1155, -0.0125},
       {0.0750, -0.1000, 0.7475}},
      {"forearm_lower_stop", {-0.0425, 0.3510, 0.5545},
       {0.0425, 0.5800, 0.5745}},
  };
  return config;
}

void test_link_points_match_forward_kinematics() {
  JointState joints;
  joints.k0_m = -0.12;
  joints.k1_rad = 0.25;
  joints.k2_rad = -0.30;
  joints.k3_rad = 0.15;
  joints.k4_rad = -0.20;
  const auto links = robot_link_points(joints);
  const auto pose = forward_kinematics(joints);
  expect(std::abs(links.tool_tip.x_m - pose.x_m) < 1e-12,
         "tool tip x must match forward kinematics");
  expect(std::abs(links.tool_tip.y_m - pose.y_m) < 1e-12,
         "tool tip y must match forward kinematics");
  expect(std::abs(links.tool_tip.z_m - pose.z_m) < 1e-12,
         "tool tip z must match forward kinematics");
}

void test_zero_pose_is_folded_storage_geometry() {
  const auto links = robot_link_points({});
  expect(std::abs(links.upper_arm_end.y_m - 0.580) < 1e-12,
         "zero-pose upper arm must point forward");
  expect(std::abs(links.forearm_end.y_m - 0.351) < 1e-12,
         "K2 zero must fold the 229 mm forearm back under the upper arm");
  expect(std::abs(links.wrist_end.y_m - 0.232) < 1e-12,
         "K4 rigid link must continue toward the rear in the storage pose");
  const auto target = forward_kinematics({});
  const auto ik = inverse_kinematics(target);
  expect(ik.ok, "folded storage zero pose must be solvable by IK");
  expect(std::abs(ik.joints.k1_rad) < 1e-6 &&
             std::abs(ik.joints.k2_rad) < 1e-6,
         "storage-pose IK must return K1=K2=0");
}

void test_disabled_is_explicitly_skipped() {
  CollisionConfig config;
  auto result = check_robot_configuration({}, config);
  expect(result.ok, "disabled checker must not reject motion");
  expect(!result.checked, "disabled checker must report checked=false");
}

void test_clear_configuration() {
  auto config = base_config();
  config.obstacles.push_back({"far_box", {2.0, 2.0, 2.0}, {2.1, 2.1, 2.1}});
  auto result = check_robot_configuration({}, config);
  expect(result.ok && result.checked, "far obstacle should be collision-free");
}

void test_upper_arm_collision() {
  auto config = base_config();
  config.obstacles.push_back(
      {"front_panel", {-0.01, 0.25, 0.69}, {0.01, 0.35, 0.73}});
  auto result = check_robot_configuration({}, config);
  expect(!result.ok, "upper arm must collide with the panel");
  expect(result.link_name == "upper_arm", "collision should identify upper_arm");
  expect(result.obstacle_name == "front_panel", "collision should identify panel");
}

void test_path_crossing_is_rejected() {
  auto config = base_config();
  config.envelope.upper_arm_radius_m = 0.025;
  config.envelope.lift_radius_m = 0.025;
  config.envelope.elbow_radius_m = 0.025;
  config.envelope.forearm_radius_m = 0.025;
  config.envelope.wrist_radius_m = 0.025;
  config.envelope.tool_radius_m = 0.020;
  config.obstacles.push_back(
      {"middle_panel", {-0.025, 0.28, 0.68}, {0.025, 0.36, 0.74}});

  JointState left;
  left.k1_rad = -60.0 * 3.14159265358979323846 / 180.0;
  JointState right;
  right.k1_rad = 60.0 * 3.14159265358979323846 / 180.0;
  expect(check_robot_configuration(left, config).ok,
         "left endpoint should be clear");
  expect(check_robot_configuration(right, config).ok,
         "right endpoint should be clear");
  auto result = check_robot_motion(left, right, config);
  expect(!result.ok, "path crossing the middle panel must be rejected");
  expect(result.path_fraction > 0.0 && result.path_fraction < 1.0,
         "path collision must report an intermediate fraction");
}

void test_margin_expands_obstacles() {
  auto config = base_config();
  config.envelope.upper_arm_radius_m = 0.01;
  config.obstacles.push_back(
      {"near_panel", {0.035, 0.40, 0.725}, {0.055, 0.50, 0.735}});
  config.safety_margin_m = 0.0;
  expect(check_robot_configuration({}, config).ok,
         "panel should be clear without margin");
  config.safety_margin_m = 0.030;
  expect(!check_robot_configuration({}, config).ok,
         "safety margin should conservatively reject the near panel");
}

void test_measured_enclosure_accepts_storage_zero() {
  const auto result =
      check_robot_configuration({}, measured_enclosure_config());
  expect(result.ok && result.checked,
         "measured enclosure must accept the calibrated storage zero pose; got " +
             result.link_name + " vs " + result.obstacle_name + ": " +
             result.reason);
}

void test_measured_forearm_stop_rejects_downward_motion() {
  auto target = JointState{};
  target.k0_m = -0.003;
  const auto result =
      check_robot_motion({}, target, measured_enclosure_config());
  expect(!result.ok, "3 mm downward motion must hit the forearm stop");
  expect(result.obstacle_name == "forearm_lower_stop",
         "downward collision must identify the forearm stop");
  expect(result.path_fraction > 0.0 && result.path_fraction < 1.0,
         "downward collision must be found along the sampled path");
}

void test_measured_slot_rejects_side_swing() {
  JointState target;
  target.k1_rad = 20.0 * 3.14159265358979323846 / 180.0;
  const auto result =
      check_robot_motion({}, target, measured_enclosure_config());
  expect(!result.ok, "K1 side swing inside the enclosure must hit a slot wall");
  expect(result.obstacle_name == "enclosure_left" ||
             result.obstacle_name == "enclosure_right",
         "side swing must identify an enclosure side wall");
  expect(result.path_fraction > 0.0 && result.path_fraction < 1.0,
         "side-wall collision must be found before the requested endpoint");
}

void test_endpoint_projection_guard_allows_only_safe_approach_modes() {
  const auto config = measured_enclosure_config();
  const JointState storage{};
  const JointState high{0.3131, 0.0, 0.0, 0.0, 0.0};
  const auto high_out = inverse_kinematics(
      {0.575, 0.250, 0.790, 0.0, 0.0, 0.0}, high);
  expect(high_out.ok, "high exterior endpoint must be reachable");
  const auto low_out = inverse_kinematics(
      {0.575, 0.250, 0.650, 0.0, 0.0, 0.0}, high_out.joints);
  expect(low_out.ok, "low exterior endpoint must be reachable");

  expect(check_endpoint_motion(storage, high, config).ok,
         "pure K0 lift inside the storage slot must remain available");
  expect(check_endpoint_motion(high, high_out.joints, config).ok,
         "high-plane deployment above the enclosure must remain available");
  expect(check_endpoint_motion(high_out.joints, low_out.joints, config).ok,
         "vertical descent through the exterior corridor must remain available");
  expect(!check_endpoint_motion(storage, low_out.joints, config).ok,
         "one-step low endpoint deployment from storage must be rejected");
}

void test_endpoint_projection_guard_adds_clearance_beyond_box_collision() {
  auto config = base_config();
  config.safety_margin_m = 0.001;
  config.envelope.forearm_radius_m = 0.0535;
  // Put the physical wall boxes far away in Y so the generic capsule/box
  // checker is clear. Their X/Z dimensions still define the calibrated
  // enclosure projection used by endpoint motion.
  config.obstacles = {
      {"enclosure_left", {-0.1805, 10.0, -0.0125},
       {-0.0750, 11.0, 0.7475}},
      {"enclosure_right", {0.0750, 10.0, -0.0125},
       {0.1805, 11.0, 0.7475}},
  };
  JointState low_rotation;
  low_rotation.k1_rad = 0.01;
  expect(check_robot_motion({}, low_rotation, config).ok,
         "generic box collision should be clear in the synthetic model");
  const auto endpoint = check_endpoint_motion({}, low_rotation, config);
  expect(!endpoint.ok,
         "endpoint projection guard must reject low forearm rotation");
  expect(endpoint.link_name == "forearm" &&
             endpoint.obstacle_name == "enclosure_projection",
         "projection rejection must identify the forearm and enclosure projection");
}

void test_config_parser_and_required_fail_closed() {
  const std::string path = "collision_test_config.csv";
  {
    std::ofstream output(path);
    output << "setting,enabled,true\n";
    output << "setting,safety_margin_m,0.025\n";
    output << "box,panel,-0.1,0.1,0.2,0.3,0.4,0.5\n";
  }
  const auto enabled = load_collision_config(path, true);
  expect(enabled.configured && enabled.enabled,
         "enabled config should load and satisfy required mode");
  expect(enabled.obstacles.size() == 1,
         "config parser should load one obstacle");
  expect(std::abs(enabled.safety_margin_m - 0.025) < 1e-12,
         "config parser should load safety margin");

  {
    std::ofstream output(path);
    output << "setting,enabled,false\n";
  }
  bool threw = false;
  try {
    (void)load_collision_config(path, true);
  } catch (const std::exception&) {
    threw = true;
  }
  std::remove(path.c_str());
  expect(threw, "required mode must reject enabled=false");
}

}  // namespace

int main() {
  try {
    test_link_points_match_forward_kinematics();
    test_zero_pose_is_folded_storage_geometry();
    test_disabled_is_explicitly_skipped();
    test_clear_configuration();
    test_upper_arm_collision();
    test_path_crossing_is_rejected();
    test_margin_expands_obstacles();
    test_measured_enclosure_accepts_storage_zero();
    test_measured_forearm_stop_rejects_downward_motion();
    test_measured_slot_rejects_side_swing();
    test_endpoint_projection_guard_allows_only_safe_approach_modes();
    test_endpoint_projection_guard_adds_clearance_beyond_box_collision();
    test_config_parser_and_required_fail_closed();
    std::cout << "collision tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "collision test failed: " << error.what() << '\n';
    return 1;
  }
}
