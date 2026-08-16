#include "therapy_robot/motion_plan.hpp"

#include "therapy_robot/collision.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <locale>
#include <stdexcept>
#include <string_view>
#include <sstream>
#include <unordered_set>
#include <utility>

namespace therapy_robot {
namespace {

constexpr const char* kSchemaVersion = "b2.motion-plan.v1";
constexpr const char* kCoordinateFrame = "robot_base";
constexpr const char* kLinearUnit = "m";
constexpr const char* kAngularUnit = "rad";

void require_finite(double value, const char* field) {
  if (!std::isfinite(value)) {
    throw std::invalid_argument(std::string(field) + " must be finite");
  }
}

void validate_joints(const JointState& joints, const char* field) {
  require_finite(joints.k0_m, (std::string(field) + ".k0_m").c_str());
  require_finite(joints.k1_rad, (std::string(field) + ".k1_rad").c_str());
  require_finite(joints.k2_rad, (std::string(field) + ".k2_rad").c_str());
  require_finite(joints.k3_rad, (std::string(field) + ".k3_rad").c_str());
  require_finite(joints.k4_rad, (std::string(field) + ".k4_rad").c_str());
}

bool joints_equal(const JointState& lhs, const JointState& rhs) {
  return lhs.k0_m == rhs.k0_m && lhs.k1_rad == rhs.k1_rad &&
         lhs.k2_rad == rhs.k2_rad && lhs.k3_rad == rhs.k3_rad &&
         lhs.k4_rad == rhs.k4_rad;
}

bool geometry_valid(const RobotGeometry& geometry) {
  const std::array<double, 8> finite_values = {
      geometry.base_height_m,
      geometry.upper_arm_m,
      geometry.forearm_m,
      geometry.wrist_forward_offset_m,
      geometry.forearm_drop_m,
      geometry.tool_length_m,
      geometry.camera_mount_offset_y_m,
      geometry.camera_mount_offset_z_m};
  if (!std::all_of(finite_values.begin(), finite_values.end(),
                   [](double value) { return std::isfinite(value); })) {
    return false;
  }
  return geometry.base_height_m > 0.0 && geometry.upper_arm_m > 0.0 &&
         geometry.forearm_m > 0.0 && geometry.wrist_forward_offset_m > 0.0 &&
         geometry.forearm_drop_m > 0.0 && geometry.tool_length_m > 0.0;
}

bool envelope_valid(const RobotCollisionEnvelope& envelope) {
  const std::array<double, 6> radii = {
      envelope.lift_radius_m, envelope.upper_arm_radius_m,
      envelope.elbow_radius_m, envelope.forearm_radius_m,
      envelope.wrist_radius_m, envelope.tool_radius_m};
  return std::all_of(radii.begin(), radii.end(), [](double radius) {
    return std::isfinite(radius) && radius > 0.0;
  });
}

std::optional<std::string> collision_config_error(
    const CollisionConfig& config) {
  if (!config.configured) return "collision_config_missing";
  if (!config.enabled) return "collision_config_disabled";
  if (config.obstacles.empty()) return "collision_config_empty";
  if (!std::isfinite(config.safety_margin_m) || config.safety_margin_m < 0.0 ||
      !std::isfinite(config.lift_step_m) || config.lift_step_m <= 0.0 ||
      !std::isfinite(config.joint_step_rad) || config.joint_step_rad <= 0.0 ||
      !envelope_valid(config.envelope)) {
    return "collision_config_invalid";
  }
  for (const auto& obstacle : config.obstacles) {
    if (obstacle.name.empty() || !std::isfinite(obstacle.min.x_m) ||
        !std::isfinite(obstacle.min.y_m) ||
        !std::isfinite(obstacle.min.z_m) ||
        !std::isfinite(obstacle.max.x_m) ||
        !std::isfinite(obstacle.max.y_m) ||
        !std::isfinite(obstacle.max.z_m) ||
        obstacle.min.x_m >= obstacle.max.x_m ||
        obstacle.min.y_m >= obstacle.max.y_m ||
        obstacle.min.z_m >= obstacle.max.z_m) {
      return "collision_config_invalid";
    }
  }
  return std::nullopt;
}

void validate_identifier(const std::string& value, const char* field) {
  if (value.empty()) {
    throw std::invalid_argument(std::string(field) + " must not be empty");
  }
  const bool safe = std::all_of(value.begin(), value.end(), [](unsigned char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
           (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.';
  });
  if (!safe) {
    throw std::invalid_argument(std::string(field) +
                                " must use only ASCII letters, digits, '.', '_' or '-'");
  }
}

void append_json_string(std::ostringstream& output, std::string_view value) {
  output.put('"');
  constexpr char hex[] = "0123456789abcdef";
  for (const unsigned char character : value) {
    switch (character) {
      case '"':
        output << "\\\"";
        break;
      case '\\':
        output << "\\\\";
        break;
      case '\b':
        output << "\\b";
        break;
      case '\f':
        output << "\\f";
        break;
      case '\n':
        output << "\\n";
        break;
      case '\r':
        output << "\\r";
        break;
      case '\t':
        output << "\\t";
        break;
      default:
        if (character < 0x20U) {
          output << "\\u00" << hex[(character >> 4U) & 0x0fU]
                 << hex[character & 0x0fU];
        } else {
          output.put(static_cast<char>(character));
        }
        break;
    }
  }
  output.put('"');
}

void append_json_number(std::ostringstream& output, double value) {
  output << std::setprecision(std::numeric_limits<double>::max_digits10)
         << value;
}

void append_json_bool(std::ostringstream& output, bool value) {
  output << (value ? "true" : "false");
}

void append_json_joints(std::ostringstream& output, const JointState& joints) {
  output << "{\"k0_m\":";
  append_json_number(output, joints.k0_m);
  output << ",\"k1_rad\":";
  append_json_number(output, joints.k1_rad);
  output << ",\"k2_rad\":";
  append_json_number(output, joints.k2_rad);
  output << ",\"k3_rad\":";
  append_json_number(output, joints.k3_rad);
  output << ",\"k4_rad\":";
  append_json_number(output, joints.k4_rad);
  output.put('}');
}

constexpr std::array<std::uint32_t, 64> kSha256RoundConstants = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
    0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
    0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
    0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
    0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
    0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
    0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
    0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
    0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U};

constexpr std::array<std::uint32_t, 8> kSha256InitialState = {
    0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
    0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U};

constexpr std::uint32_t rotate_right(std::uint32_t value, unsigned amount) {
  return (value >> amount) | (value << (32U - amount));
}

void sha256_transform(std::array<std::uint32_t, 8>& state,
                      const std::uint8_t* block) {
  std::array<std::uint32_t, 64> schedule{};
  for (std::size_t index = 0; index < 16; ++index) {
    const std::size_t offset = index * 4;
    schedule[index] = (static_cast<std::uint32_t>(block[offset]) << 24U) |
                      (static_cast<std::uint32_t>(block[offset + 1]) << 16U) |
                      (static_cast<std::uint32_t>(block[offset + 2]) << 8U) |
                      static_cast<std::uint32_t>(block[offset + 3]);
  }
  for (std::size_t index = 16; index < schedule.size(); ++index) {
    const std::uint32_t lower = schedule[index - 15];
    const std::uint32_t upper = schedule[index - 2];
    const std::uint32_t sigma0 = rotate_right(lower, 7U) ^
                                 rotate_right(lower, 18U) ^ (lower >> 3U);
    const std::uint32_t sigma1 = rotate_right(upper, 17U) ^
                                 rotate_right(upper, 19U) ^ (upper >> 10U);
    schedule[index] = schedule[index - 16] + sigma0 + schedule[index - 7] + sigma1;
  }

  std::uint32_t a = state[0];
  std::uint32_t b = state[1];
  std::uint32_t c = state[2];
  std::uint32_t d = state[3];
  std::uint32_t e = state[4];
  std::uint32_t f = state[5];
  std::uint32_t g = state[6];
  std::uint32_t h = state[7];
  for (std::size_t index = 0; index < schedule.size(); ++index) {
    const std::uint32_t sigma1 = rotate_right(e, 6U) ^ rotate_right(e, 11U) ^
                                 rotate_right(e, 25U);
    const std::uint32_t choose = (e & f) ^ (~e & g);
    const std::uint32_t temporary1 = h + sigma1 + choose +
                                     kSha256RoundConstants[index] + schedule[index];
    const std::uint32_t sigma0 = rotate_right(a, 2U) ^ rotate_right(a, 13U) ^
                                 rotate_right(a, 22U);
    const std::uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
    const std::uint32_t temporary2 = sigma0 + majority;
    h = g;
    g = f;
    f = e;
    e = d + temporary1;
    d = c;
    c = b;
    b = a;
    a = temporary1 + temporary2;
  }
  state[0] += a;
  state[1] += b;
  state[2] += c;
  state[3] += d;
  state[4] += e;
  state[5] += f;
  state[6] += g;
  state[7] += h;
}

}  // namespace

MotionPlanSide parse_motion_plan_side(const std::string& value) {
  if (value == "left") return MotionPlanSide::Left;
  if (value == "right") return MotionPlanSide::Right;
  throw std::invalid_argument("motion plan side must be 'left' or 'right'");
}

const char* motion_plan_side_name(MotionPlanSide side) {
  switch (side) {
    case MotionPlanSide::Left:
      return "left";
    case MotionPlanSide::Right:
      return "right";
  }
  throw std::invalid_argument("unknown motion plan side");
}

const char* motion_plan_phase_name(MotionPlanPhase phase) {
  switch (phase) {
    case MotionPlanPhase::Lift:
      return "lift";
    case MotionPlanPhase::SideTransit:
      return "side_transit";
    case MotionPlanPhase::PreviewApproach:
      return "preview_approach";
    case MotionPlanPhase::PreviewRetract:
      return "preview_retract";
    case MotionPlanPhase::ReturnTransit:
      return "return_transit";
    case MotionPlanPhase::Lower:
      return "lower";
  }
  throw std::invalid_argument("unknown motion plan phase");
}

MotionPlanUnits::MotionPlanUnits(std::string linear, std::string angular)
    : linear_(std::move(linear)), angular_(std::move(angular)) {
  if (linear_ != kLinearUnit || angular_ != kAngularUnit) {
    throw std::invalid_argument("motion plan units must be linear='m' and angular='rad'");
  }
}

const std::string& MotionPlanUnits::linear() const noexcept { return linear_; }
const std::string& MotionPlanUnits::angular() const noexcept { return angular_; }

MotionWaypoint::MotionWaypoint(JointState joints) : joints_(joints) {
  validate_joints(joints_, "waypoint.joints");
}

const JointState& MotionWaypoint::joints() const noexcept { return joints_; }

SegmentPreflight::SegmentPreflight(bool ok, bool collision_checked,
                                   std::string reason_code,
                                   std::string collision_link,
                                   std::string collision_obstacle,
                                   double path_fraction)
    : ok_(ok),
      collision_checked_(collision_checked),
      reason_code_(std::move(reason_code)),
      collision_link_(std::move(collision_link)),
      collision_obstacle_(std::move(collision_obstacle)),
      path_fraction_(path_fraction) {
  validate_identifier(reason_code_, "preflight.reason_code");
  require_finite(path_fraction_, "preflight.path_fraction");
  if (path_fraction_ < 0.0 || path_fraction_ > 1.0) {
    throw std::invalid_argument("preflight.path_fraction must be within 0..1");
  }
  if (ok_ && !collision_checked_) {
    throw std::invalid_argument("a successful preflight must have collision_checked=true");
  }
}

bool SegmentPreflight::ok() const noexcept { return ok_; }
bool SegmentPreflight::collision_checked() const noexcept {
  return collision_checked_;
}
const std::string& SegmentPreflight::reason_code() const noexcept {
  return reason_code_;
}
const std::string& SegmentPreflight::collision_link() const noexcept {
  return collision_link_;
}
const std::string& SegmentPreflight::collision_obstacle() const noexcept {
  return collision_obstacle_;
}
double SegmentPreflight::path_fraction() const noexcept {
  return path_fraction_;
}

SyntheticRouteParameters::SyntheticRouteParameters(
    JointState storage_joints, double preview_lift_m, double side_sweep_rad,
    double elbow_preview_rad, double forearm_preview_rad,
    double wrist_preview_rad)
    : storage_joints_(storage_joints),
      preview_lift_m_(preview_lift_m),
      side_sweep_rad_(side_sweep_rad),
      elbow_preview_rad_(elbow_preview_rad),
      forearm_preview_rad_(forearm_preview_rad),
      wrist_preview_rad_(wrist_preview_rad) {
  validate_joints(storage_joints_, "parameters.storage_joints");
  require_finite(preview_lift_m_, "parameters.preview_lift_m");
  require_finite(side_sweep_rad_, "parameters.side_sweep_rad");
  require_finite(elbow_preview_rad_, "parameters.elbow_preview_rad");
  require_finite(forearm_preview_rad_, "parameters.forearm_preview_rad");
  require_finite(wrist_preview_rad_, "parameters.wrist_preview_rad");
  if (side_sweep_rad_ <= 0.0) {
    throw std::invalid_argument("parameters.side_sweep_rad must be positive");
  }
  if (preview_lift_m_ <= storage_joints_.k0_m) {
    throw std::invalid_argument("parameters.preview_lift_m must be above storage K0");
  }
}

const JointState& SyntheticRouteParameters::storage_joints() const noexcept {
  return storage_joints_;
}
double SyntheticRouteParameters::preview_lift_m() const noexcept {
  return preview_lift_m_;
}
double SyntheticRouteParameters::side_sweep_rad() const noexcept {
  return side_sweep_rad_;
}
double SyntheticRouteParameters::elbow_preview_rad() const noexcept {
  return elbow_preview_rad_;
}
double SyntheticRouteParameters::forearm_preview_rad() const noexcept {
  return forearm_preview_rad_;
}
double SyntheticRouteParameters::wrist_preview_rad() const noexcept {
  return wrist_preview_rad_;
}

MotionPlanSegment::MotionPlanSegment(std::string segment_id,
                                     MotionPlanPhase phase,
                                     MotionWaypoint start,
                                     MotionWaypoint target,
                                     SegmentPreflight preflight)
    : segment_id_(std::move(segment_id)),
      phase_(phase),
      start_(std::move(start)),
      target_(std::move(target)),
      preflight_(std::move(preflight)) {
  validate_identifier(segment_id_, "segment_id");
  static_cast<void>(motion_plan_phase_name(phase_));
}

const std::string& MotionPlanSegment::segment_id() const noexcept {
  return segment_id_;
}
MotionPlanPhase MotionPlanSegment::phase() const noexcept { return phase_; }
const MotionWaypoint& MotionPlanSegment::start() const noexcept { return start_; }
const MotionWaypoint& MotionPlanSegment::target() const noexcept { return target_; }
const SegmentPreflight& MotionPlanSegment::preflight() const noexcept {
  return preflight_;
}

MotionPlan::MotionPlan(std::string schema_version, MotionPlanSide side,
                       std::string coordinate_frame, MotionPlanUnits units,
                       bool formal_use_allowed,
                       SyntheticRouteParameters parameters,
                       std::vector<MotionPlanSegment> segments)
    : schema_version_(std::move(schema_version)),
      side_(side),
      coordinate_frame_(std::move(coordinate_frame)),
      units_(std::move(units)),
      formal_use_allowed_(formal_use_allowed),
      parameters_(std::move(parameters)),
      segments_(std::move(segments)) {
  if (schema_version_ != kSchemaVersion) {
    throw std::invalid_argument("motion plan schema_version must be b2.motion-plan.v1");
  }
  static_cast<void>(motion_plan_side_name(side_));
  if (coordinate_frame_ != kCoordinateFrame) {
    throw std::invalid_argument("motion plan coordinate_frame must be robot_base");
  }
  if (formal_use_allowed_) {
    throw std::invalid_argument("synthetic B2 motion plans cannot allow formal use");
  }
  if (segments_.empty()) {
    throw std::invalid_argument("motion plan must contain at least one segment");
  }

  std::unordered_set<std::string> segment_ids;
  for (std::size_t index = 0; index < segments_.size(); ++index) {
    const auto& segment = segments_[index];
    if (!segment_ids.insert(segment.segment_id()).second) {
      throw std::invalid_argument("motion plan contains duplicate segment_id: " +
                                  segment.segment_id());
    }
    if (index > 0 &&
        !joints_equal(segments_[index - 1].target().joints(),
                      segment.start().joints())) {
      throw std::invalid_argument("motion plan segments must form a continuous route");
    }
  }
}

const std::string& MotionPlan::schema_version() const noexcept {
  return schema_version_;
}
MotionPlanSide MotionPlan::side() const noexcept { return side_; }
const std::string& MotionPlan::coordinate_frame() const noexcept {
  return coordinate_frame_;
}
const MotionPlanUnits& MotionPlan::units() const noexcept { return units_; }
bool MotionPlan::formal_use_allowed() const noexcept {
  return formal_use_allowed_;
}
const SyntheticRouteParameters& MotionPlan::parameters() const noexcept {
  return parameters_;
}
const std::vector<MotionPlanSegment>& MotionPlan::segments() const noexcept {
  return segments_;
}
bool MotionPlan::preflight_ok() const noexcept {
  return std::all_of(segments_.begin(), segments_.end(),
                     [](const MotionPlanSegment& segment) {
                       return segment.preflight().ok() &&
                              segment.preflight().collision_checked();
                     });
}
std::optional<std::string> MotionPlan::first_rejected_segment_id() const {
  const auto rejected = std::find_if(
      segments_.begin(), segments_.end(), [](const MotionPlanSegment& segment) {
        return !segment.preflight().ok() ||
               !segment.preflight().collision_checked();
      });
  if (rejected == segments_.end()) return std::nullopt;
  return rejected->segment_id();
}

SegmentPreflight preflight_motion_segment(
    const JointState& from, const JointState& to,
    const CollisionConfig& config, const RobotGeometry& geometry) {
  try {
    validate_joints(from, "preflight.from");
    validate_joints(to, "preflight.to");
  } catch (const std::exception&) {
    return SegmentPreflight(false, false, "collision_input_invalid", "", "",
                            0.0);
  }
  if (const auto config_error = collision_config_error(config)) {
    return SegmentPreflight(false, false, *config_error, "", "", 0.0);
  }
  if (!geometry_valid(geometry)) {
    return SegmentPreflight(false, false, "collision_geometry_invalid", "", "",
                            0.0);
  }

  try {
    const CollisionCheck result =
        check_robot_motion(from, to, config, geometry);
    if (!std::isfinite(result.path_fraction) || result.path_fraction < 0.0 ||
        result.path_fraction > 1.0) {
      return SegmentPreflight(false, result.checked,
                              "collision_check_invalid_result",
                              result.link_name, result.obstacle_name, 0.0);
    }
    if (!result.checked) {
      return SegmentPreflight(false, false, "collision_not_checked",
                              result.link_name, result.obstacle_name,
                              result.path_fraction);
    }
    if (!result.ok) {
      const std::string reason_code =
          result.reason.find("sampling exceeds") != std::string::npos
              ? "collision_sampling_limit"
              : "collision_detected";
      return SegmentPreflight(false, true, reason_code, result.link_name,
                              result.obstacle_name, result.path_fraction);
    }
    return SegmentPreflight(true, true, "collision_free", result.link_name,
                            result.obstacle_name, result.path_fraction);
  } catch (const std::exception&) {
    return SegmentPreflight(false, false, "collision_check_exception", "", "",
                            0.0);
  } catch (...) {
    return SegmentPreflight(false, false, "collision_check_exception", "", "",
                            0.0);
  }
}

MotionPlan make_synthetic_motion_plan(
    MotionPlanSide side, const SyntheticRouteParameters& parameters,
    const CollisionConfig& config, const RobotGeometry& geometry) {
  static_cast<void>(motion_plan_side_name(side));

  const JointState storage = parameters.storage_joints();
  JointState lifted = storage;
  lifted.k0_m = parameters.preview_lift_m();

  JointState side_transit = lifted;
  side_transit.k1_rad = side == MotionPlanSide::Left
                            ? parameters.side_sweep_rad()
                            : -parameters.side_sweep_rad();

  JointState preview = side_transit;
  preview.k2_rad = parameters.elbow_preview_rad();
  preview.k3_rad = parameters.forearm_preview_rad();
  preview.k4_rad = parameters.wrist_preview_rad();

  std::vector<MotionPlanSegment> segments;
  segments.reserve(6);
  const auto add_segment = [&](const char* segment_id, MotionPlanPhase phase,
                               const JointState& start,
                               const JointState& target) {
    segments.emplace_back(
        segment_id, phase, MotionWaypoint(start), MotionWaypoint(target),
        preflight_motion_segment(start, target, config, geometry));
  };
  add_segment("segment-01-lift", MotionPlanPhase::Lift, storage, lifted);
  add_segment("segment-02-side-transit", MotionPlanPhase::SideTransit, lifted,
              side_transit);
  add_segment("segment-03-preview-approach",
              MotionPlanPhase::PreviewApproach, side_transit, preview);
  add_segment("segment-04-preview-retract",
              MotionPlanPhase::PreviewRetract, preview, side_transit);
  add_segment("segment-05-return-transit", MotionPlanPhase::ReturnTransit,
              side_transit, lifted);
  add_segment("segment-06-lower", MotionPlanPhase::Lower, lifted, storage);

  return MotionPlan("b2.motion-plan.v1", side, "robot_base",
                    MotionPlanUnits("m", "rad"), false, parameters,
                    std::move(segments));
}

std::string canonical_motion_plan_json_impl(const MotionPlan& plan,
                                            bool include_diagnostics) {
  std::ostringstream output;
  output.imbue(std::locale::classic());
  output << "{\"coordinate_frame\":";
  append_json_string(output, plan.coordinate_frame());
  output << ",\"formal_use_allowed\":";
  append_json_bool(output, plan.formal_use_allowed());
  output << ",\"parameters\":{";
  output << "\"elbow_preview_rad\":";
  append_json_number(output, plan.parameters().elbow_preview_rad());
  output << ",\"forearm_preview_rad\":";
  append_json_number(output, plan.parameters().forearm_preview_rad());
  output << ",\"preview_lift_m\":";
  append_json_number(output, plan.parameters().preview_lift_m());
  output << ",\"side_sweep_rad\":";
  append_json_number(output, plan.parameters().side_sweep_rad());
  output << ",\"storage_joints\":";
  append_json_joints(output, plan.parameters().storage_joints());
  output << ",\"wrist_preview_rad\":";
  append_json_number(output, plan.parameters().wrist_preview_rad());
  output << "},\"schema_version\":";
  append_json_string(output, plan.schema_version());
  output << ",\"segments\":[";
  for (std::size_t index = 0; index < plan.segments().size(); ++index) {
    if (index != 0) output.put(',');
    const auto& segment = plan.segments()[index];
    const auto& preflight = segment.preflight();
    output << "{\"phase\":";
    append_json_string(output, motion_plan_phase_name(segment.phase()));
    if (include_diagnostics) {
      output << ",\"preflight\":{";
      output << "\"collision_checked\":";
      append_json_bool(output, preflight.collision_checked());
      output << ",\"collision_link\":";
      append_json_string(output, preflight.collision_link());
      output << ",\"collision_obstacle\":";
      append_json_string(output, preflight.collision_obstacle());
      output << ",\"ok\":";
      append_json_bool(output, preflight.ok());
      output << ",\"path_fraction\":";
      append_json_number(output, preflight.path_fraction());
      output << ",\"reason_code\":";
      append_json_string(output, preflight.reason_code());
      output.put('}');
    }
    output << ",\"segment_id\":";
    append_json_string(output, segment.segment_id());
    output << ",\"start\":{\"joints\":";
    append_json_joints(output, segment.start().joints());
    output << "},\"target\":{\"joints\":";
    append_json_joints(output, segment.target().joints());
    output << "}}";
  }
  output << "],\"side\":";
  append_json_string(output, motion_plan_side_name(plan.side()));
  output << ",\"units\":{\"angular\":";
  append_json_string(output, plan.units().angular());
  output << ",\"linear\":";
  append_json_string(output, plan.units().linear());
  output << "}}";
  return output.str();
}

std::string canonical_motion_plan_json(const MotionPlan& plan) {
  return canonical_motion_plan_json_impl(plan, true);
}

std::string sha256_hex(std::string_view input) {
  std::array<std::uint32_t, 8> state = kSha256InitialState;
  std::array<std::uint8_t, 64> block{};
  std::size_t offset = 0;
  while (input.size() - offset >= block.size()) {
    for (std::size_t index = 0; index < block.size(); ++index) {
      block[index] = static_cast<std::uint8_t>(input[offset + index]);
    }
    sha256_transform(state, block.data());
    offset += block.size();
  }

  const std::size_t remaining = input.size() - offset;
  block.fill(0);
  for (std::size_t index = 0; index < remaining; ++index) {
    block[index] = static_cast<std::uint8_t>(input[offset + index]);
  }
  block[remaining] = 0x80U;
  const std::uint64_t bit_length = static_cast<std::uint64_t>(input.size()) * 8U;
  if (remaining >= 56U) {
    sha256_transform(state, block.data());
    block.fill(0);
  }
  for (std::size_t index = 0; index < 8; ++index) {
    block[56U + index] = static_cast<std::uint8_t>(bit_length >> (56U - 8U * index));
  }
  sha256_transform(state, block.data());

  std::ostringstream output;
  output.imbue(std::locale::classic());
  output << std::hex << std::setfill('0');
  for (const std::uint32_t word : state) {
    output << std::setw(8) << word;
  }
  return output.str();
}

std::string motion_plan_hash(const MotionPlan& plan) {
  // Preflight values are diagnostics and are excluded from the immutable
  // route identity hash by the frozen B2 contract.
  return "sha256:" + sha256_hex(canonical_motion_plan_json_impl(plan, false));
}

std::string motion_plan_id(const MotionPlan& plan) {
  const std::string hash = motion_plan_hash(plan);
  return "b2-" + hash.substr(std::string("sha256:").size(), 16);
}

}  // namespace therapy_robot
