#include "therapy_robot/kinematics.hpp"

#include <algorithm>
#include <cmath>

namespace therapy_robot {
namespace {
constexpr double kPi = 3.14159265358979323846;

double clamp(double v, double lo, double hi) {
  return std::max(lo, std::min(hi, v));
}

double wrap_pi(double v) {
  while (v > kPi) v -= 2.0 * kPi;
  while (v < -kPi) v += 2.0 * kPi;
  return v;
}

std::array<double, 3> add(std::array<double, 3> a, std::array<double, 3> b) {
  return {a[0] + b[0], a[1] + b[1], a[2] + b[2]};
}

std::array<double, 3> sub(std::array<double, 3> a, std::array<double, 3> b) {
  return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
}

std::array<double, 3> mul(std::array<double, 3> a, double s) {
  return {a[0] * s, a[1] * s, a[2] * s};
}

double dot(std::array<double, 3> a, std::array<double, 3> b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

double norm(std::array<double, 3> a) {
  return std::sqrt(dot(a, a));
}

std::array<double, 3> normalize(std::array<double, 3> a) {
  double n = norm(a);
  if (n < 1e-12) return {0.0, 0.0, 1.0};
  return mul(a, 1.0 / n);
}

std::array<double, 3> planar_dir(double a) {
  return {std::sin(a), std::cos(a), 0.0};
}

std::array<double, 3> side_dir(double a) {
  return {std::cos(a), -std::sin(a), 0.0};
}

std::array<double, 3> cross(std::array<double, 3> a, std::array<double, 3> b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}

std::array<double, 3> rotate_around_axis(std::array<double, 3> v, std::array<double, 3> axis, double angle) {
  auto k = normalize(axis);
  double c = std::cos(angle);
  double s = std::sin(angle);
  return add(add(mul(v, c), mul(cross(k, v), s)), mul(k, dot(k, v) * (1.0 - c)));
}

Point3 point3(const std::array<double, 3>& value) {
  return {value[0], value[1], value[2]};
}

bool orientation_for_yaw(const std::array<double, 3>& axis, double yaw, double& k3, double& k4) {
  auto forward = planar_dir(yaw);
  double a_forward = clamp(dot(axis, forward), -1.0, 1.0);
  auto perp = sub(axis, mul(forward, a_forward));
  double perp_norm = norm(perp);
  if (perp_norm < 1e-9) {
    k3 = 0.0;
    k4 = a_forward >= 0.0 ? -kPi / 2.0 : kPi / 2.0;
  } else {
    auto up_after_roll = mul(perp, 1.0 / perp_norm);
    auto side0 = side_dir(yaw);
    k3 = std::atan2(dot(up_after_roll, side0), up_after_roll[2]);
    k4 = -std::atan2(a_forward, perp_norm);
  }
  return k3 >= -kPi / 4.0 && k3 <= kPi / 4.0 && k4 >= -kPi / 3.0 && k4 <= kPi / 3.0;
}
}

RobotGeometry default_geometry() {
  return {};
}

std::array<double, 3> axis_from_rx_ry(double rx_rad, double ry_rad) {
  double sx = std::sin(rx_rad);
  double cx = std::cos(rx_rad);
  double sy = std::sin(ry_rad);
  double cy = std::cos(ry_rad);
  return normalize({sy * cx, -sx, cy * cx});
}

std::array<double, 2> rx_ry_from_axis(const std::array<double, 3>& axis_raw) {
  auto axis = normalize(axis_raw);
  return {std::asin(clamp(-axis[1], -1.0, 1.0)), std::atan2(axis[0], axis[2])};
}

Pose forward_kinematics(const JointState& q, const RobotGeometry& g) {
  const auto links = robot_link_points(q, g);
  auto axis = normalize({links.wrist_end.x_m - links.tool_tip.x_m,
                         links.wrist_end.y_m - links.tool_tip.y_m,
                         links.wrist_end.z_m - links.tool_tip.z_m});
  auto angles = rx_ry_from_axis(axis);
  return {links.tool_tip.x_m, links.tool_tip.y_m, links.tool_tip.z_m,
          angles[0], angles[1], 0.0};
}

RobotLinkPoints robot_link_points(const JointState& q, const RobotGeometry& g) {
  std::array<double, 3> p0{0.0, 0.0, 0.0};
  std::array<double, 3> p1{0.0, 0.0, g.base_height_m + q.k0_m};
  auto p2 = add(p1, mul(planar_dir(q.k1_rad), g.upper_arm_m));
  std::array<double, 3> p3{p2[0], p2[1], p2[2] - g.forearm_drop_m};
  // K2 motor zero is the stowed pose: the forearm folds back underneath the
  // upper arm.  The geometric forearm yaw therefore includes a 180-degree
  // offset from the motor's displayed K2 angle.
  double yaw = q.k1_rad + q.k2_rad + kPi;
  auto forward = planar_dir(yaw);
  auto p4 = add(p3, mul(forward, g.forearm_m));
  auto side = rotate_around_axis(side_dir(yaw), forward, q.k3_rad);
  auto offset_forward = rotate_around_axis(forward, side, q.k4_rad);
  auto axis = rotate_around_axis(rotate_around_axis({0.0, 0.0, 1.0}, forward, q.k3_rad), side, q.k4_rad);
  auto wrist = add(p4, mul(offset_forward, g.wrist_forward_offset_m));
  auto tip = sub(wrist, mul(axis, g.tool_length_m));
  auto k2_half = mul(std::array<double, 3>{0.0, 0.0, 1.0}, 0.090);
  auto k3_half = mul(forward, 0.080);
  // K4 is contained by the 85 mm-wide forearm envelope.  The former 180 mm
  // placeholder made the stowed robot wider than its confirmed 150 mm slot
  // and caused a guaranteed false collision at zero.
  auto k4_half = mul(side, 0.0425);
  return {
      point3(p0),
      point3(p1),
      point3(p2),
      point3(p3),
      point3(p4),
      point3(wrist),
      point3(tip),
      point3(sub(p2, k2_half)),
      point3(add(p2, k2_half)),
      point3(sub(p3, k3_half)),
      point3(add(p3, k3_half)),
      point3(sub(p4, k4_half)),
      point3(add(p4, k4_half)),
  };
}

namespace {
IkResult inverse_kinematics_impl(const Pose& target, const RobotGeometry& g,
                                 const JointState* preferred) {
  auto axis = axis_from_rx_ry(target.rx_rad, target.ry_rad);
  std::array<double, 3> tip{target.x_m, target.y_m, target.z_m};
  JointState best{};
  double best_cost = 1e9;
  double best_motion_cost = 1e9;
  bool found = false;

  auto try_yaw = [&](double yaw) {
    double k3 = 0.0;
    double k4 = 0.0;
    if (!orientation_for_yaw(axis, yaw, k3, k4)) return;
    auto forward = planar_dir(yaw);
    auto side = rotate_around_axis(side_dir(yaw), forward, k3);
    auto offset_forward = rotate_around_axis(forward, side, k4);
    auto p4 = sub(add(tip, mul(axis, g.tool_length_m)), mul(offset_forward, g.wrist_forward_offset_m));
    double lift = p4[2] - g.base_height_m + g.forearm_drop_m;
    // Stowed is K0=0 and positive K0 raises the arm. A 1 mm numerical/
    // feedback guard prevents encoder noise around zero from breaking XY jog;
    // accepted targets are clamped back into the physical command range.
    if (lift < -0.001 - 1e-9) return;
    lift = std::max(lift, 0.0);
    auto p1_vec = sub({p4[0], p4[1], 0.0}, mul(forward, g.forearm_m));
    double p1_len = std::hypot(p1_vec[0], p1_vec[1]);
    double cost = std::abs(p1_len - g.upper_arm_m);
    double k1 = std::atan2(p1_vec[0], p1_vec[1]);
    double k2 = wrap_pi(yaw - k1 - kPi);
    if (k1 < -kPi / 2.0 || k1 > kPi / 2.0 || k2 < -kPi / 2.0 || k2 > kPi / 2.0) return;
    double motion_cost = 0.0;
    if (preferred) {
      const double dk0 = (lift - preferred->k0_m) / 0.100;
      const double dk1 = wrap_pi(k1 - preferred->k1_rad);
      const double dk2 = wrap_pi(k2 - preferred->k2_rad);
      const double dk3 = wrap_pi(k3 - preferred->k3_rad);
      const double dk4 = wrap_pi(k4 - preferred->k4_rad);
      motion_cost = dk0 * dk0 + dk1 * dk1 + dk2 * dk2 +
                    dk3 * dk3 + dk4 * dk4;
    }
    // Geometry remains the primary criterion. Within one micrometre of an
    // equally accurate solution, prefer the branch nearest the real feedback.
    const bool better_geometry = cost < best_cost - 1e-6;
    const bool same_geometry = std::abs(cost - best_cost) <= 1e-6;
    if (better_geometry ||
        (same_geometry && motion_cost < best_motion_cost)) {
      best_cost = cost;
      best_motion_cost = motion_cost;
      best = {lift, k1, k2, k3, k4};
      found = true;
    }
  };

  for (int i = -720; i <= 720; ++i) {
    try_yaw(i * kPi / 720.0);
  }
  if (found) {
    double center = best.k1_rad + best.k2_rad + kPi;
    for (int step = 0; step < 4; ++step) {
      double span = kPi / (720.0 * std::pow(5.0, step));
      double current = center;
      for (int i = -10; i <= 10; ++i) try_yaw(current + i * span / 10.0);
      center = best.k1_rad + best.k2_rad + kPi;
    }
  }
  if (!found) {
    return {false, {}, "target outside K4 rigid-tool workspace"};
  }
  if (best_cost > 1e-5) {
    return {false, {}, "target xy outside two-link workspace"};
  }
  return {true, best, "ok"};
}

}  // namespace

IkResult inverse_kinematics(const Pose& target, const RobotGeometry& g) {
  return inverse_kinematics_impl(target, g, nullptr);
}

IkResult inverse_kinematics(const Pose& target, const JointState& preferred,
                            const RobotGeometry& g) {
  return inverse_kinematics_impl(target, g, &preferred);
}

IkResult inverse_kinematics_fixed_forearm_yaw(
    const Pose& target, double forearm_yaw_rad,
    const JointState& preferred, const RobotGeometry& g) {
  auto axis = axis_from_rx_ry(target.rx_rad, target.ry_rad);
  double k3 = 0.0;
  double k4 = 0.0;
  if (!orientation_for_yaw(axis, forearm_yaw_rad, k3, k4))
    return {false, {}, "requested forearm yaw is incompatible with tool orientation"};
  auto forward = planar_dir(forearm_yaw_rad);
  auto side = rotate_around_axis(side_dir(forearm_yaw_rad), forward, k3);
  auto offset_forward = rotate_around_axis(forward, side, k4);
  std::array<double, 3> tip{target.x_m, target.y_m, target.z_m};
  auto p4 = sub(add(tip, mul(axis, g.tool_length_m)),
                mul(offset_forward, g.wrist_forward_offset_m));
  double lift = p4[2] - g.base_height_m + g.forearm_drop_m;
  if (lift < -0.001 - 1e-9) return {false, {}, "target requires negative K0 lift"};
  lift = std::max(lift, 0.0);
  auto p1_vec = sub({p4[0], p4[1], 0.0}, mul(forward, g.forearm_m));
  double p1_len = std::hypot(p1_vec[0], p1_vec[1]);
  if (std::abs(p1_len - g.upper_arm_m) > 1e-5)
    return {false, {}, "target xy outside fixed-forearm-yaw workspace"};
  double k1 = std::atan2(p1_vec[0], p1_vec[1]);
  double k2 = wrap_pi(forearm_yaw_rad - k1 - kPi);
  if (k1 < -kPi / 2.0 || k1 > kPi / 2.0 ||
      k2 < -kPi / 2.0 || k2 > kPi / 2.0)
    return {false, {}, "fixed forearm yaw requires joint outside limits"};
  JointState result{lift, k1, k2, k3, k4};
  const double dk0 = (lift - preferred.k0_m) / 0.100;
  const double dk1 = wrap_pi(k1 - preferred.k1_rad);
  const double dk2 = wrap_pi(k2 - preferred.k2_rad);
  const double dk3 = wrap_pi(k3 - preferred.k3_rad);
  const double dk4 = wrap_pi(k4 - preferred.k4_rad);
  (void)(dk0 * dk0 + dk1 * dk1 + dk2 * dk2 + dk3 * dk3 + dk4 * dk4);
  return {true, result, "ok"};
}

}
