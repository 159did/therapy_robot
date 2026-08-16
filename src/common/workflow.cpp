#include "therapy_robot/workflow.hpp"

#include <algorithm>

namespace therapy_robot {
namespace {

void add_check(WorkflowAssessment& result, const char* id,
               WorkflowCheckStatus status, bool blocking,
               const char* reason_code, const char* observed) {
  WorkflowCheck check;
  check.id = id;
  check.status = status;
  check.blocking = blocking;
  check.reason_code = reason_code ? reason_code : "";
  check.observed = observed ? observed : "";
  result.checks.push_back(check);
  if (status == WorkflowCheckStatus::pass) {
    ++result.self_check_summary.passed;
  } else if (status == WorkflowCheckStatus::fail) {
    ++result.self_check_summary.failed;
  } else {
    ++result.self_check_summary.unknown;
  }
  if (blocking && status != WorkflowCheckStatus::pass) {
    result.blocking_reasons.push_back({
        check.reason_code.empty() ? id : check.reason_code,
        id,
        status == WorkflowCheckStatus::unknown ? "blocking" : "blocking",
        check.observed});
  }
}

bool has_blocking_failure(const WorkflowAssessment& result) {
  return !result.blocking_reasons.empty();
}

}  // namespace

const char* workflow_check_status_name(WorkflowCheckStatus status) {
  switch (status) {
    case WorkflowCheckStatus::pass: return "pass";
    case WorkflowCheckStatus::fail: return "fail";
    case WorkflowCheckStatus::unknown: return "unknown";
  }
  return "unknown";
}

WorkflowAssessment evaluate_workflow(const WorkflowFacts& facts) {
  WorkflowAssessment result;
  result.allowed_actions = {"view_state", "view_self_check", "refresh_state",
                            "preview_motion_plan"};

  const bool mode_known = facts.run_mode == "sim" || facts.run_mode == "hardware";
  const bool state_known = !facts.system_state.empty();
  add_check(result, "shared_state_integrity",
            mode_known && state_known ? WorkflowCheckStatus::pass
                                      : WorkflowCheckStatus::unknown,
            true, "shared_state_unknown",
            mode_known && state_known ? "run_mode_and_system_state_present"
                                      : "run_mode_or_system_state_unknown");
  add_check(result, "emergency_stop",
            facts.emergency_stop ? WorkflowCheckStatus::fail
                                 : WorkflowCheckStatus::pass,
            true, "emergency_stop_latched",
            facts.emergency_stop ? "latched" : "clear");
  add_check(result, "axis_configuration",
            facts.axes_configured ? WorkflowCheckStatus::pass
                                  : WorkflowCheckStatus::fail,
            true, "axis_configuration_missing",
            facts.axes_configured ? "all_axes_configured" : "one_or_more_axes_unconfigured");
  add_check(result, "axis_online",
            facts.axes_online ? WorkflowCheckStatus::pass
                              : WorkflowCheckStatus::fail,
            true, "axis_offline",
            facts.axes_online ? "all_axes_online" : "one_or_more_axes_offline");
  add_check(result, "axis_faults",
            facts.axes_fault_free ? WorkflowCheckStatus::pass
                                  : WorkflowCheckStatus::fail,
            true, "axis_fault_present",
            facts.axes_fault_free ? "no_axis_fault" : "one_or_more_axis_faults");
  add_check(result, "collision_config",
            facts.collision_configured && facts.collision_enabled
                ? WorkflowCheckStatus::pass
                : WorkflowCheckStatus::fail,
            true, "collision_config_unavailable",
            facts.collision_configured && facts.collision_enabled
                ? "configured_enabled_required" : "missing_or_disabled_collision_boundary");
  add_check(result, "collision_alarm",
            facts.collision_alarm ? WorkflowCheckStatus::fail
                                  : WorkflowCheckStatus::pass,
            true, "collision_alarm_active",
            facts.collision_alarm ? "alarm" : "clear");
  add_check(result, "manual_recovery",
            facts.manual_recovery ? WorkflowCheckStatus::fail
                                  : WorkflowCheckStatus::pass,
            true, "manual_recovery_active",
            facts.manual_recovery ? "recovery_mode" : "normal_mode");
  add_check(result, "formal_camera_extrinsics",
            facts.formal_camera_extrinsics_present ? WorkflowCheckStatus::pass
                                                   : WorkflowCheckStatus::fail,
            true, "missing_formal_camera_extrinsics",
            facts.formal_camera_extrinsics_present ? "formal_extrinsics_present"
                                                   : "formal_extrinsics_missing");
  add_check(result, "entity_offsets",
            facts.entity_offsets_verified ? WorkflowCheckStatus::pass
                                          : WorkflowCheckStatus::fail,
            true, "entity_offsets_unverified",
            facts.entity_offsets_verified ? "verified" : "not_verified");
  // This check documents the B2 hard boundary.  It is a fact of this build,
  // not a user-configurable readiness flag.
  add_check(result, "automatic_execution_lock", WorkflowCheckStatus::pass,
            false, nullptr, "execution_allowed_false");
  add_check(result, "motor_command_boundary", WorkflowCheckStatus::pass, false,
            nullptr, "read_only_workflow_api");

  const bool hardware_fault = facts.emergency_stop || facts.collision_alarm ||
                              !facts.axes_fault_free;
  const bool offline = !mode_known || !state_known || !facts.axes_configured ||
                       !facts.axes_online;
  const bool storage = !facts.axes_enabled &&
                       (facts.system_state == "idle" || facts.system_state == "storage" ||
                        facts.system_state == "hardware_ready");
  if (offline) {
    result.workflow_state = "offline";
  } else if (hardware_fault) {
    result.workflow_state = "fault";
  } else if (facts.manual_recovery) {
    result.workflow_state = "locked";
  } else if (storage) {
    result.workflow_state = "storage";
  } else if (!facts.formal_camera_extrinsics_present) {
    result.workflow_state = "vision_blocked";
  } else if (has_blocking_failure(result)) {
    result.workflow_state = "preview_blocked";
  } else {
    result.workflow_state = "ready_for_preview";
  }
  result.self_check_summary.status = has_blocking_failure(result) ? "blocked" : "pass";
  result.execution_locked = true;
  return result;
}

}  // namespace therapy_robot
