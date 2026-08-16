#include "therapy_robot/collision.hpp"
#include "therapy_robot/motion_plan.hpp"

#include <cassert>
#include <cmath>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <type_traits>

using namespace therapy_robot;

namespace {

SyntheticRouteParameters synthetic_parameters() {
  return SyntheticRouteParameters({0.0, 0.0, 0.0, 0.0, 0.0},
                                  0.20, 0.30, 0.10, -0.20, 0.05);
}

CollisionConfig fixture_config() {
  CollisionConfig config;
  config.configured = true;
  config.enabled = true;
  config.required = true;
  config.source_path = "test-fixture";
  config.obstacles.push_back({"far_fixture", {10.0, 10.0, 10.0},
                              {11.0, 11.0, 11.0}});
  return config;
}

void assert_rejected(const MotionPlan& plan, const std::string& reason,
                     bool checked) {
  assert(!plan.preflight_ok());
  assert(plan.first_rejected_segment_id() == "segment-01-lift");
  for (const auto& segment : plan.segments()) {
    assert(!segment.preflight().ok());
    assert(segment.preflight().collision_checked() == checked);
    assert(segment.preflight().reason_code() == reason);
  }
}

}  // namespace

int main() {
  static_assert(!std::is_copy_assignable<MotionPlan>::value);
  static_assert(!std::is_copy_assignable<MotionPlanSegment>::value);
  static_assert(!std::is_copy_assignable<SegmentPreflight>::value);
  static_assert(!std::is_copy_assignable<SyntheticRouteParameters>::value);

  const CollisionConfig config = fixture_config();
  const MotionPlan left =
      make_synthetic_motion_plan(MotionPlanSide::Left, synthetic_parameters(),
                                 config);
  const MotionPlan right =
      make_synthetic_motion_plan(MotionPlanSide::Right, synthetic_parameters(),
                                 config);
  assert(left.segments().size() == 6);
  assert(right.segments().size() == 6);
  assert(left.preflight_ok());
  assert(right.preflight_ok());
  assert(left.segments()[1].target().joints().k1_rad > 0.0);
  assert(right.segments()[1].target().joints().k1_rad < 0.0);
  assert(motion_plan_hash(left) != motion_plan_hash(right));
  assert(motion_plan_id(left) != motion_plan_id(right));
  assert(canonical_motion_plan_json(left) ==
         canonical_motion_plan_json(
             make_synthetic_motion_plan(MotionPlanSide::Left,
                                        synthetic_parameters(), config)));

  const std::string hash = motion_plan_hash(left);
  assert(hash.size() == 71);
  assert(hash.rfind("sha256:", 0) == 0);
  assert(motion_plan_id(left) == "b2-" + hash.substr(7, 16));
  for (const auto& segment : left.segments()) {
    assert(segment.preflight().ok());
    assert(segment.preflight().collision_checked());
    assert(segment.preflight().reason_code() == "collision_free");
  }

  CollisionConfig missing;
  assert_rejected(
      make_synthetic_motion_plan(MotionPlanSide::Left, synthetic_parameters(),
                                 missing),
      "collision_config_missing", false);

  CollisionConfig disabled = config;
  disabled.enabled = false;
  assert_rejected(
      make_synthetic_motion_plan(MotionPlanSide::Left, synthetic_parameters(),
                                 disabled),
      "collision_config_disabled", false);

  CollisionConfig collision = config;
  collision.obstacles.clear();
  collision.obstacles.push_back({"cabinet", {-2.0, -2.0, -2.0},
                                 {2.0, 2.0, 2.0}});
  const MotionPlan blocked = make_synthetic_motion_plan(
      MotionPlanSide::Left, synthetic_parameters(), collision);
  assert(!blocked.preflight_ok());
  assert(blocked.first_rejected_segment_id() == "segment-01-lift");
  assert(blocked.segments()[0].preflight().reason_code() ==
         "collision_detected");
  assert(blocked.segments()[0].preflight().collision_link() == "K0_lift");
  assert(blocked.segments()[0].preflight().collision_obstacle() == "cabinet");
  assert(motion_plan_hash(blocked) == motion_plan_hash(left));

  const JointState invalid{
      std::numeric_limits<double>::quiet_NaN(), 0.0, 0.0, 0.0, 0.0};
  const auto invalid_result = preflight_motion_segment(
      invalid, {0.2, 0.0, 0.0, 0.0, 0.0}, config);
  assert(!invalid_result.ok());
  assert(!invalid_result.collision_checked());
  assert(invalid_result.reason_code() == "collision_input_invalid");

  bool rejected_lower_lift = false;
  try {
    static_cast<void>(SyntheticRouteParameters(
        {0.2, 0.0, 0.0, 0.0, 0.0}, 0.1, 0.3, 0.1, -0.2, 0.05));
  } catch (const std::invalid_argument&) {
    rejected_lower_lift = true;
  }
  assert(rejected_lower_lift);

  return 0;
}
