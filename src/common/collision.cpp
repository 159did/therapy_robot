#include "therapy_robot/collision.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace therapy_robot {
namespace {

struct Capsule {
  const char* name;
  Point3 a;
  Point3 b;
  double radius_m;
};

std::string trim(std::string value) {
  auto not_space = [](unsigned char c) { return !std::isspace(c); };
  value.erase(value.begin(), std::find_if(value.begin(), value.end(), not_space));
  value.erase(std::find_if(value.rbegin(), value.rend(), not_space).base(), value.end());
  return value;
}

std::vector<std::string> split_csv(const std::string& line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) fields.push_back(trim(field));
  return fields;
}

double parse_double(const std::string& text, const std::string& field,
                    int line_number) {
  char* end = nullptr;
  const double value = std::strtod(text.c_str(), &end);
  if (end == text.c_str() || *end != '\0' || !std::isfinite(value)) {
    throw std::runtime_error("collision config line " +
                             std::to_string(line_number) + ": invalid " +
                             field + "='" + text + "'");
  }
  return value;
}

bool parse_bool(std::string value, const std::string& field, int line_number) {
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (value == "1" || value == "true" || value == "yes" || value == "on") return true;
  if (value == "0" || value == "false" || value == "no" || value == "off") return false;
  throw std::runtime_error("collision config line " +
                           std::to_string(line_number) + ": invalid " + field);
}

bool env_flag(const char* name, bool fallback) {
  const char* raw = std::getenv(name);
  if (!raw || !*raw) return fallback;
  return parse_bool(raw, name, 0);
}

void require_positive(double value, const std::string& field, int line_number) {
  if (!(value > 0.0) || !std::isfinite(value)) {
    throw std::runtime_error("collision config line " +
                             std::to_string(line_number) + ": " + field +
                             " must be positive");
  }
}

void apply_setting(CollisionConfig& config, const std::string& key,
                   const std::string& raw_value, int line_number) {
  if (key == "enabled") {
    config.enabled = parse_bool(raw_value, key, line_number);
    return;
  }
  const double value = parse_double(raw_value, key, line_number);
  if (key == "safety_margin_m") {
    if (value < 0.0) throw std::runtime_error("safety_margin_m cannot be negative");
    config.safety_margin_m = value;
  } else if (key == "lift_step_m") {
    require_positive(value, key, line_number);
    config.lift_step_m = value;
  } else if (key == "joint_step_deg") {
    require_positive(value, key, line_number);
    config.joint_step_rad = value * 3.14159265358979323846 / 180.0;
  } else if (key == "lift_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.lift_radius_m = value;
  } else if (key == "upper_arm_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.upper_arm_radius_m = value;
  } else if (key == "elbow_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.elbow_radius_m = value;
  } else if (key == "forearm_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.forearm_radius_m = value;
  } else if (key == "wrist_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.wrist_radius_m = value;
  } else if (key == "tool_radius_m") {
    require_positive(value, key, line_number);
    config.envelope.tool_radius_m = value;
  } else {
    throw std::runtime_error("collision config line " +
                             std::to_string(line_number) +
                             ": unknown setting '" + key + "'");
  }
}

std::vector<Capsule> robot_capsules(const JointState& joints,
                                    const RobotGeometry& geometry,
                                    const RobotCollisionEnvelope& envelope) {
  const auto p = robot_link_points(joints, geometry);
  return {
      {"K0_lift", p.base, p.shoulder, envelope.lift_radius_m},
      {"upper_arm", p.shoulder, p.upper_arm_end, envelope.upper_arm_radius_m},
      {"K2_axis", p.k2_axis_a, p.k2_axis_b, envelope.elbow_radius_m},
      {"elbow_drop", p.upper_arm_end, p.forearm_start, envelope.elbow_radius_m},
      {"K3_axis", p.k3_axis_a, p.k3_axis_b, envelope.elbow_radius_m},
      {"forearm", p.forearm_start, p.forearm_end, envelope.forearm_radius_m},
      // The K4 motor is shorter along its axis (85 mm) than its 100 mm
      // diameter.  A sphere at the joint centre is therefore a conservative
      // bound.  Treating the full axis as a capsule incorrectly adds a motor
      // radius beyond both axial end faces and makes it wider than the slot.
      {"K4_axis", p.forearm_end, p.forearm_end, envelope.wrist_radius_m},
      {"wrist", p.forearm_end, p.wrist_end, envelope.wrist_radius_m},
      {"tool", p.wrist_end, p.tool_tip, envelope.tool_radius_m},
  };
}

double component(const Point3& p, int axis) {
  if (axis == 0) return p.x_m;
  if (axis == 1) return p.y_m;
  return p.z_m;
}

double point_box_distance_squared(const Point3& point,
                                  const CollisionBox& box) {
  double distance_squared = 0.0;
  for (int axis = 0; axis < 3; ++axis) {
    const double value = component(point, axis);
    const double lo = component(box.min, axis);
    const double hi = component(box.max, axis);
    if (value < lo) {
      const double distance = lo - value;
      distance_squared += distance * distance;
    } else if (value > hi) {
      const double distance = value - hi;
      distance_squared += distance * distance;
    }
  }
  return distance_squared;
}

Point3 segment_point(const Point3& a, const Point3& b, double t) {
  return {a.x_m + (b.x_m - a.x_m) * t,
          a.y_m + (b.y_m - a.y_m) * t,
          a.z_m + (b.z_m - a.z_m) * t};
}

// Exact minimum squared distance between a line segment and an axis-aligned
// box.  Splitting at the six slab crossings makes the point-to-box distance a
// quadratic on each interval, so checking its stationary point and interval
// ends avoids the false-positive box-corner behaviour of axis-wise expansion.
double segment_box_distance_squared(const Point3& a, const Point3& b,
                                    const CollisionBox& box) {
  std::vector<double> breaks{0.0, 1.0};
  for (int axis = 0; axis < 3; ++axis) {
    const double start = component(a, axis);
    const double direction = component(b, axis) - start;
    if (std::abs(direction) < 1e-15) continue;
    for (const double plane : {component(box.min, axis),
                               component(box.max, axis)}) {
      const double t = (plane - start) / direction;
      if (t > 0.0 && t < 1.0) breaks.push_back(t);
    }
  }
  std::sort(breaks.begin(), breaks.end());
  breaks.erase(std::unique(breaks.begin(), breaks.end(),
                           [](double lhs, double rhs) {
                             return std::abs(lhs - rhs) < 1e-14;
                           }),
               breaks.end());

  double best = std::numeric_limits<double>::infinity();
  auto evaluate = [&](double t) {
    best = std::min(best,
                    point_box_distance_squared(segment_point(a, b, t), box));
  };
  for (std::size_t interval = 1; interval < breaks.size(); ++interval) {
    const double lo_t = breaks[interval - 1];
    const double hi_t = breaks[interval];
    const double mid_t = (lo_t + hi_t) * 0.5;
    double quadratic = 0.0;
    double linear = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
      const double start = component(a, axis);
      const double direction = component(b, axis) - start;
      const double mid = start + direction * mid_t;
      double constant = 0.0;
      double slope = 0.0;
      if (mid < component(box.min, axis)) {
        constant = component(box.min, axis) - start;
        slope = -direction;
      } else if (mid > component(box.max, axis)) {
        constant = start - component(box.max, axis);
        slope = direction;
      } else {
        continue;
      }
      quadratic += slope * slope;
      linear += 2.0 * constant * slope;
    }
    evaluate(lo_t);
    evaluate(hi_t);
    if (quadratic > 1e-24) {
      const double stationary = -linear / (2.0 * quadratic);
      if (stationary > lo_t && stationary < hi_t) evaluate(stationary);
    }
  }
  return best;
}

JointState interpolate(const JointState& a, const JointState& b, double t) {
  auto lerp = [t](double x, double y) { return x + (y - x) * t; };
  return {lerp(a.k0_m, b.k0_m), lerp(a.k1_rad, b.k1_rad),
          lerp(a.k2_rad, b.k2_rad), lerp(a.k3_rad, b.k3_rad),
          lerp(a.k4_rad, b.k4_rad)};
}

CollisionCheck disabled_result() {
  return {true, false, "collision boundary disabled", "", "", 0.0};
}

}  // namespace

CollisionConfig load_collision_config(const std::string& path, bool required) {
  CollisionConfig config;
  config.required = required;
  config.source_path = path;
  if (path.empty()) {
    if (required) throw std::runtime_error("collision config is required but path is empty");
    return config;
  }

  std::ifstream input(path);
  if (!input) {
    if (required) throw std::runtime_error("required collision config not found: " + path);
    return config;
  }
  config.configured = true;

  std::string line;
  int line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    line = trim(line);
    if (line.empty() || line[0] == '#') continue;
    const auto fields = split_csv(line);
    if (fields.empty()) continue;
    if (fields[0] == "setting") {
      if (fields.size() != 3) {
        throw std::runtime_error("collision config line " +
                                 std::to_string(line_number) +
                                 ": setting requires 3 fields");
      }
      apply_setting(config, fields[1], fields[2], line_number);
    } else if (fields[0] == "box") {
      if (fields.size() != 8 || fields[1].empty()) {
        throw std::runtime_error("collision config line " +
                                 std::to_string(line_number) +
                                 ": box requires name and 6 coordinates");
      }
      CollisionBox box;
      box.name = fields[1];
      box.min = {parse_double(fields[2], "x_min", line_number),
                 parse_double(fields[4], "y_min", line_number),
                 parse_double(fields[6], "z_min", line_number)};
      box.max = {parse_double(fields[3], "x_max", line_number),
                 parse_double(fields[5], "y_max", line_number),
                 parse_double(fields[7], "z_max", line_number)};
      if (!(box.min.x_m < box.max.x_m && box.min.y_m < box.max.y_m &&
            box.min.z_m < box.max.z_m)) {
        throw std::runtime_error("collision config line " +
                                 std::to_string(line_number) +
                                 ": box min must be smaller than max");
      }
      config.obstacles.push_back(box);
    } else {
      throw std::runtime_error("collision config line " +
                               std::to_string(line_number) +
                               ": unknown record type '" + fields[0] + "'");
    }
  }

  if (config.enabled && config.obstacles.empty()) {
    throw std::runtime_error("collision checking is enabled but no obstacle boxes are configured");
  }
  if (required && !config.enabled) {
    throw std::runtime_error("collision config is required but enabled=false: " + path);
  }
  return config;
}

CollisionConfig collision_config_from_environment() {
  const bool required = env_flag("THERAPY_ROBOT_COLLISION_REQUIRED", false);
  const char* raw_path = std::getenv("THERAPY_ROBOT_COLLISION_CONFIG");
  return load_collision_config(raw_path ? raw_path : "", required);
}

CollisionCheck check_robot_configuration(const JointState& joints,
                                          const CollisionConfig& config,
                                          const RobotGeometry& geometry) {
  if (!config.enabled) return disabled_result();
  for (const auto& link : robot_capsules(joints, geometry, config.envelope)) {
    const double expansion = link.radius_m + config.safety_margin_m;
    for (const auto& obstacle : config.obstacles) {
      const double minimum_distance_squared =
          segment_box_distance_squared(link.a, link.b, obstacle);
      if (minimum_distance_squared <= expansion * expansion) {
        CollisionCheck result;
        result.ok = false;
        result.checked = true;
        result.link_name = link.name;
        result.obstacle_name = obstacle.name;
        result.reason = std::string("collision boundary: ") + link.name +
                        " intersects " + obstacle.name;
        return result;
      }
    }
  }
  return {true, true, "collision-free", "", "", 0.0};
}

CollisionCheck check_robot_motion(const JointState& from, const JointState& to,
                                  const CollisionConfig& config,
                                  const RobotGeometry& geometry) {
  if (!config.enabled) return disabled_result();
  const double lift_steps = std::abs(to.k0_m - from.k0_m) / config.lift_step_m;
  const double joint_delta = std::max(
      {std::abs(to.k1_rad - from.k1_rad),
       std::abs(to.k2_rad - from.k2_rad),
       std::abs(to.k3_rad - from.k3_rad),
       std::abs(to.k4_rad - from.k4_rad)});
  const double joint_steps = joint_delta / config.joint_step_rad;
  const int steps = std::max(1, static_cast<int>(std::ceil(std::max(lift_steps, joint_steps))));
  if (steps > 20000) {
    return {false, true, "collision path sampling exceeds 20000 steps", "", "", 0.0};
  }
  for (int i = 0; i <= steps; ++i) {
    const double fraction = static_cast<double>(i) / steps;
    auto result = check_robot_configuration(interpolate(from, to, fraction),
                                            config, geometry);
    if (!result.ok) {
      result.path_fraction = fraction;
      std::ostringstream reason;
      reason << result.reason << " at path " <<
          static_cast<int>(std::lround(fraction * 100.0)) << "%";
      result.reason = reason.str();
      return result;
    }
  }
  return {true, true, "collision-free path", "", "", 1.0};
}

CollisionCheck check_endpoint_motion(const JointState& from, const JointState& to,
                                     const CollisionConfig& config,
                                     const RobotGeometry& geometry) {
  const auto base_check = check_robot_motion(from, to, config, geometry);
  if (!base_check.ok || !config.enabled) return base_check;

  // Derive the projection directly from the calibrated enclosure model. A
  // different collision model without both side walls keeps normal checking.
  double enclosure_half_width_m = 0.0;
  double enclosure_top_m = -std::numeric_limits<double>::infinity();
  bool found_enclosure_side = false;
  for (const auto& obstacle : config.obstacles) {
    if (obstacle.name != "enclosure_left" && obstacle.name != "enclosure_right") continue;
    found_enclosure_side = true;
    enclosure_half_width_m = std::max(
        enclosure_half_width_m,
        std::max(std::abs(obstacle.min.x_m), std::abs(obstacle.max.x_m)));
    enclosure_top_m = std::max(enclosure_top_m, obstacle.max.z_m);
  }
  if (!found_enclosure_side || !std::isfinite(enclosure_top_m)) return base_check;

  constexpr double kAdditionalOutsideClearanceM = 0.030;
  constexpr double kPureLiftJointToleranceRad = 0.001;
  const bool pure_lift =
      std::abs(to.k1_rad - from.k1_rad) <= kPureLiftJointToleranceRad &&
      std::abs(to.k2_rad - from.k2_rad) <= kPureLiftJointToleranceRad &&
      std::abs(to.k3_rad - from.k3_rad) <= kPureLiftJointToleranceRad &&
      std::abs(to.k4_rad - from.k4_rad) <= kPureLiftJointToleranceRad;

  for (int sample_index = 0; sample_index <= 60; ++sample_index) {
    const double fraction = static_cast<double>(sample_index) / 60.0;
    const auto joints = interpolate(from, to, fraction);
    const auto links = robot_link_points(joints, geometry);
    const double forearm_surface_bottom_m =
        std::min(links.forearm_start.z_m, links.forearm_end.z_m) -
        config.envelope.forearm_radius_m - config.safety_margin_m;
    if (pure_lift || forearm_surface_bottom_m >= enclosure_top_m) continue;

    const double forearm_min_abs_x_m = std::min(
        std::abs(links.forearm_start.x_m), std::abs(links.forearm_end.x_m));
    const bool crosses_projection_center =
        links.forearm_start.x_m * links.forearm_end.x_m <= 0.0;
    const double outside_clearance_m = forearm_min_abs_x_m -
        config.envelope.forearm_radius_m - config.safety_margin_m -
        enclosure_half_width_m;
    if (!crosses_projection_center && outside_clearance_m >= kAdditionalOutsideClearanceM) {
      continue;
    }

    CollisionCheck result;
    result.ok = false;
    result.checked = true;
    result.link_name = "forearm";
    result.obstacle_name = "enclosure_projection";
    result.path_fraction = fraction;
    std::ostringstream reason;
    reason << "forearm enters enclosure vertical projection at "
           << fraction * 100.0 << "% (outside clearance="
           << outside_clearance_m * 1000.0
           << " mm, required >= 30 mm; raise K0 first or use the safe high-plane path)";
    result.reason = reason.str();
    return result;
  }
  return base_check;
}

}  // namespace therapy_robot
