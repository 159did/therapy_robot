#pragma once

#include "therapy_robot/kinematics.hpp"

#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace therapy_robot {

struct CollisionConfig;

enum class MotionPlanSide {
  Left,
  Right,
};

enum class MotionPlanPhase {
  Lift,
  SideTransit,
  PreviewApproach,
  PreviewRetract,
  ReturnTransit,
  Lower,
};

class MotionPlan;

MotionPlanSide parse_motion_plan_side(const std::string& value);
const char* motion_plan_side_name(MotionPlanSide side);
const char* motion_plan_phase_name(MotionPlanPhase phase);

std::string canonical_motion_plan_json(const MotionPlan& plan);
std::string sha256_hex(std::string_view input);
std::string motion_plan_hash(const MotionPlan& plan);
std::string motion_plan_id(const MotionPlan& plan);

class MotionPlanUnits final {
 public:
  MotionPlanUnits(std::string linear, std::string angular);

  MotionPlanUnits(const MotionPlanUnits&) = default;
  MotionPlanUnits(MotionPlanUnits&&) = default;
  MotionPlanUnits& operator=(const MotionPlanUnits&) = delete;
  MotionPlanUnits& operator=(MotionPlanUnits&&) = delete;

  const std::string& linear() const noexcept;
  const std::string& angular() const noexcept;

 private:
  const std::string linear_;
  const std::string angular_;
};

class MotionWaypoint final {
 public:
  explicit MotionWaypoint(JointState joints);

  MotionWaypoint(const MotionWaypoint&) = default;
  MotionWaypoint(MotionWaypoint&&) = default;
  MotionWaypoint& operator=(const MotionWaypoint&) = delete;
  MotionWaypoint& operator=(MotionWaypoint&&) = delete;

  const JointState& joints() const noexcept;

 private:
  const JointState joints_;
};

class SegmentPreflight final {
 public:
  SegmentPreflight(bool ok, bool collision_checked, std::string reason_code,
                   std::string collision_link,
                   std::string collision_obstacle, double path_fraction);

  SegmentPreflight(const SegmentPreflight&) = default;
  SegmentPreflight(SegmentPreflight&&) = default;
  SegmentPreflight& operator=(const SegmentPreflight&) = delete;
  SegmentPreflight& operator=(SegmentPreflight&&) = delete;

  bool ok() const noexcept;
  bool collision_checked() const noexcept;
  const std::string& reason_code() const noexcept;
  const std::string& collision_link() const noexcept;
  const std::string& collision_obstacle() const noexcept;
  double path_fraction() const noexcept;

 private:
  const bool ok_;
  const bool collision_checked_;
  const std::string reason_code_;
  const std::string collision_link_;
  const std::string collision_obstacle_;
  const double path_fraction_;
};

class SyntheticRouteParameters final {
 public:
  SyntheticRouteParameters(JointState storage_joints,
                           double preview_lift_m,
                           double side_sweep_rad,
                           double elbow_preview_rad,
                           double forearm_preview_rad,
                           double wrist_preview_rad);

  SyntheticRouteParameters(const SyntheticRouteParameters&) = default;
  SyntheticRouteParameters(SyntheticRouteParameters&&) = default;
  SyntheticRouteParameters& operator=(const SyntheticRouteParameters&) = delete;
  SyntheticRouteParameters& operator=(SyntheticRouteParameters&&) = delete;

  const JointState& storage_joints() const noexcept;
  double preview_lift_m() const noexcept;
  double side_sweep_rad() const noexcept;
  double elbow_preview_rad() const noexcept;
  double forearm_preview_rad() const noexcept;
  double wrist_preview_rad() const noexcept;

 private:
  const JointState storage_joints_;
  const double preview_lift_m_;
  const double side_sweep_rad_;
  const double elbow_preview_rad_;
  const double forearm_preview_rad_;
  const double wrist_preview_rad_;
};

class MotionPlanSegment final {
 public:
  MotionPlanSegment(std::string segment_id, MotionPlanPhase phase,
                    MotionWaypoint start, MotionWaypoint target,
                    SegmentPreflight preflight);

  MotionPlanSegment(const MotionPlanSegment&) = default;
  MotionPlanSegment(MotionPlanSegment&&) = default;
  MotionPlanSegment& operator=(const MotionPlanSegment&) = delete;
  MotionPlanSegment& operator=(MotionPlanSegment&&) = delete;

  const std::string& segment_id() const noexcept;
  MotionPlanPhase phase() const noexcept;
  const MotionWaypoint& start() const noexcept;
  const MotionWaypoint& target() const noexcept;
  const SegmentPreflight& preflight() const noexcept;

 private:
  const std::string segment_id_;
  const MotionPlanPhase phase_;
  const MotionWaypoint start_;
  const MotionWaypoint target_;
  const SegmentPreflight preflight_;
};

class MotionPlan final {
 public:
  MotionPlan(std::string schema_version, MotionPlanSide side,
             std::string coordinate_frame, MotionPlanUnits units,
             bool formal_use_allowed, SyntheticRouteParameters parameters,
             std::vector<MotionPlanSegment> segments);

  MotionPlan(const MotionPlan&) = default;
  MotionPlan(MotionPlan&&) = default;
  MotionPlan& operator=(const MotionPlan&) = delete;
  MotionPlan& operator=(MotionPlan&&) = delete;

  const std::string& schema_version() const noexcept;
  MotionPlanSide side() const noexcept;
  const std::string& coordinate_frame() const noexcept;
  const MotionPlanUnits& units() const noexcept;
  bool formal_use_allowed() const noexcept;
  const SyntheticRouteParameters& parameters() const noexcept;
  const std::vector<MotionPlanSegment>& segments() const noexcept;
  bool preflight_ok() const noexcept;
  std::optional<std::string> first_rejected_segment_id() const;

 private:
  const std::string schema_version_;
  const MotionPlanSide side_;
  const std::string coordinate_frame_;
  const MotionPlanUnits units_;
  const bool formal_use_allowed_;
  const SyntheticRouteParameters parameters_;
  const std::vector<MotionPlanSegment> segments_;
};

SegmentPreflight preflight_motion_segment(
    const JointState& from, const JointState& to,
    const CollisionConfig& config,
    const RobotGeometry& geometry = default_geometry());

MotionPlan make_synthetic_motion_plan(
    MotionPlanSide side, const SyntheticRouteParameters& parameters,
    const CollisionConfig& config,
    const RobotGeometry& geometry = default_geometry());

}  // namespace therapy_robot
