#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace therapy_robot {

enum class WorkflowCheckStatus { pass, fail, unknown };

struct WorkflowBlockingReason {
  std::string code;
  std::string source;
  std::string severity;
  std::string message;
};

struct WorkflowCheck {
  std::string id;
  WorkflowCheckStatus status = WorkflowCheckStatus::unknown;
  bool blocking = false;
  std::string reason_code;
  std::string observed;
};

struct WorkflowSourceState {
  std::uint64_t command_seq = 0;
  std::uint64_t target_command_seq = 0;
  std::uint64_t endpoint_target_seq = 0;
};

// This is a value-only snapshot.  It deliberately contains no SharedState
// pointer so workflow evaluation cannot write a command or a heartbeat.
struct WorkflowFacts {
  std::string run_mode;
  std::string system_state;
  bool emergency_stop = false;
  bool collision_configured = false;
  bool collision_enabled = false;
  bool collision_required = false;
  bool collision_alarm = false;
  bool manual_recovery = false;
  bool axes_configured = false;
  bool axes_online = false;
  bool axes_enabled = false;
  bool axes_fault_free = false;
  bool formal_camera_extrinsics_present = false;
  bool entity_offsets_verified = false;
  WorkflowSourceState source_state{};
};

struct WorkflowSummary {
  std::string status = "unknown";
  int passed = 0;
  int failed = 0;
  int unknown = 0;
};

struct WorkflowAssessment {
  std::string workflow_state = "locked";
  std::vector<std::string> allowed_actions;
  WorkflowSummary self_check_summary;
  std::vector<WorkflowCheck> checks;
  std::vector<WorkflowBlockingReason> blocking_reasons;
  bool execution_locked = true;
};

WorkflowAssessment evaluate_workflow(const WorkflowFacts& facts);
const char* workflow_check_status_name(WorkflowCheckStatus status);

}  // namespace therapy_robot
