#include "therapy_robot/workflow.hpp"

#include <algorithm>
#include <cassert>
#include <iostream>
#include <string>

using namespace therapy_robot;

namespace {

WorkflowFacts ready_facts() {
  WorkflowFacts facts;
  facts.run_mode = "sim";
  facts.system_state = "standby";
  facts.collision_configured = true;
  facts.collision_enabled = true;
  facts.axes_configured = true;
  facts.axes_online = true;
  facts.axes_enabled = true;
  facts.axes_fault_free = true;
  facts.formal_camera_extrinsics_present = true;
  facts.entity_offsets_verified = true;
  facts.source_state = {11, 22, 33};
  return facts;
}

bool has_reason(const WorkflowAssessment& result, const std::string& code) {
  return std::any_of(result.blocking_reasons.begin(),
                     result.blocking_reasons.end(),
                     [&](const WorkflowBlockingReason& reason) {
                       return reason.code == code;
                     });
}

void assert_actions_are_read_only(const WorkflowAssessment& result) {
  const std::vector<std::string> allowed{
      "view_state", "view_self_check", "refresh_state", "preview_motion_plan"};
  for (const auto& action : result.allowed_actions) {
    assert(std::find(allowed.begin(), allowed.end(), action) != allowed.end());
  }
}

}  // namespace

int main() {
  {
    const auto facts = ready_facts();
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "ready_for_preview");
    assert(result.self_check_summary.status == "pass");
    assert(result.self_check_summary.failed == 0);
    assert(result.self_check_summary.unknown == 0);
    assert(result.execution_locked);
    assert(result.blocking_reasons.empty());
    assert_actions_are_read_only(result);
    assert(facts.source_state.command_seq == 11);
    assert(facts.source_state.target_command_seq == 22);
    assert(facts.source_state.endpoint_target_seq == 33);
  }
  {
    auto facts = ready_facts();
    facts.axes_enabled = false;
    facts.system_state = "idle";
    facts.formal_camera_extrinsics_present = false;
    facts.entity_offsets_verified = false;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "storage");
    assert(result.self_check_summary.status == "blocked");
    assert(has_reason(result, "missing_formal_camera_extrinsics"));
    assert(has_reason(result, "entity_offsets_unverified"));
    assert(result.execution_locked);
  }
  {
    auto facts = ready_facts();
    facts.emergency_stop = true;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "fault");
    assert(has_reason(result, "emergency_stop_latched"));
  }
  {
    auto facts = ready_facts();
    facts.axes_online = false;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "offline");
    assert(has_reason(result, "axis_offline"));
  }
  {
    auto facts = ready_facts();
    facts.manual_recovery = true;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "locked");
    assert(has_reason(result, "manual_recovery_active"));
  }
  {
    auto facts = ready_facts();
    facts.formal_camera_extrinsics_present = false;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "vision_blocked");
    assert(has_reason(result, "missing_formal_camera_extrinsics"));
  }
  {
    auto facts = ready_facts();
    facts.entity_offsets_verified = false;
    const auto result = evaluate_workflow(facts);
    assert(result.workflow_state == "preview_blocked");
    assert(has_reason(result, "entity_offsets_unverified"));
  }
  std::cout << "PASS: B2 workflow model is read-only and fail-closed\n";
  return 0;
}
