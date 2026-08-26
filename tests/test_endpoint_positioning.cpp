#include "therapy_robot/endpoint_positioning.hpp"

#include <cmath>
#include <iostream>
#include <limits>

namespace {

therapy_robot::CollisionConfig test_collision_config() {
  therapy_robot::CollisionConfig config;
  config.configured = true;
  config.enabled = true;
  config.required = true;
  config.safety_margin_m = 0.001;
  config.lift_step_m = 0.002;
  config.joint_step_rad = 0.008726646259971648;
  config.obstacles.push_back({"far_fixture", {5.0, 5.0, 5.0}, {6.0, 6.0, 6.0}});
  return config;
}

bool require(bool condition, const char* message) {
  if (condition) return true;
  std::cerr << "FAILED: " << message << '\n';
  return false;
}

}  // namespace

int main() {
  therapy_robot::SharedState limits;
  therapy_robot::initialize_defaults(limits);
  const auto collision = test_collision_config();
  const auto tolerance = therapy_robot::default_endpoint_positioning_tolerance();
  const therapy_robot::JointState source{0.050, 0.10, -0.20, 0.02, -0.03};
  const auto target = therapy_robot::forward_kinematics(source);

  const auto preflight = therapy_robot::preflight_endpoint_positioning(
      source, target, limits, collision);
  if (!require(preflight.ok, "nominal preflight must pass") ||
      !require(preflight.collision.checked, "nominal collision must be checked")) {
    return 1;
  }

  therapy_robot::EndpointPositioningMeasurement measurement;
  measurement.sample_id = "left-01";
  measurement.side = "left";
  measurement.source = source;
  measurement.target = target;
  measurement.actual = {0.0502, 0.1001, -0.1999, 0.0200, -0.0300};
  const auto result = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision, therapy_robot::default_geometry(), tolerance);
  if (!require(result.accepted, "nominal feedback must be accepted") ||
      !require(result.target_error_m > 0.0, "feedback perturbation must change endpoint") ||
      !require(result.orientation_check_passed, "nominal orientation must pass")) {
    return 1;
  }

  measurement.actual.k0_m = 1.0;
  const auto out_of_limit = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision);
  if (!require(!out_of_limit.accepted, "out-of-limit feedback must be rejected") ||
      !require(out_of_limit.reason.find("soft limit") != std::string::npos,
               "out-of-limit rejection must name soft limit")) {
    return 1;
  }

  measurement.actual = source;
  measurement.actual.k1_rad += 0.1;
  const auto position_rejected = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision, therapy_robot::default_geometry(),
      {1e-6, 0.5});
  if (!require(!position_rejected.accepted, "position error above threshold must reject") ||
      !require(position_rejected.reason == "position_error_exceeds_tolerance",
               "position rejection reason must be explicit")) {
    return 1;
  }

  measurement.actual = source;
  measurement.target.rx_rad = 0.1;
  const auto orientation_rejected = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision, therapy_robot::default_geometry(),
      {1.0, 0.01});
  if (!require(!orientation_rejected.accepted, "orientation error above threshold must reject") ||
      !require(orientation_rejected.reason == "orientation_error_exceeds_tolerance",
               "orientation rejection reason must be explicit")) {
    return 1;
  }

  const auto invalid_tolerance = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision, therapy_robot::default_geometry(), {0.0, 0.01});
  if (!require(!invalid_tolerance.accepted, "invalid tolerance must reject") ||
      !require(invalid_tolerance.reason.find("invalid tolerance") != std::string::npos,
               "invalid tolerance reason must be explicit")) {
    return 1;
  }

  measurement.actual = source;
  measurement.target = target;
  measurement.target.x_m = std::numeric_limits<double>::quiet_NaN();
  const auto non_finite = therapy_robot::evaluate_endpoint_positioning_measurement(
      measurement, limits, collision);
  if (!require(!non_finite.accepted, "NaN target must be rejected") ||
      !require(non_finite.reason.find("non-finite") != std::string::npos,
               "NaN rejection must name non-finite value")) {
    return 1;
  }

  therapy_robot::CollisionConfig disabled = collision;
  disabled.enabled = false;
  const auto collision_disabled = therapy_robot::preflight_endpoint_positioning(
      source, target, limits, disabled);
  if (!require(!collision_disabled.ok, "disabled collision config must be rejected") ||
      !require(collision_disabled.reason.find("required-and-enabled") != std::string::npos,
               "collision rejection must name enabled requirement")) {
    return 1;
  }
  std::cout << "endpoint positioning preflight and feedback metrics verified\n";
  return 0;
}
