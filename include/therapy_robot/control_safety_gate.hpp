#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace therapy_robot {

struct SharedState;

constexpr uint64_t kControlFeedbackMaxAgeMs = 1000;

enum class ControlActionKind {
  Unknown,
  OfflineSimulation,
  ReadOnlyComputation,
  EntityControl,
  FailSafeStop,
};

struct ControlSafetyState {
  bool execution_allowed = false;
  bool entity_action_authorized = false;
  std::string hardware_mode = "SIMULATION";
  std::string h1_status = "H1_EVIDENCE_INCOMPLETE";
  bool emergency_stop = false;
  bool feedback_valid = false;
  uint64_t feedback_age_ms = UINT64_MAX;
  std::string limit_state = "UNKNOWN";
  std::string collision_state = "UNKNOWN";
  std::string watchdog_state = "UNKNOWN";
  bool brake_state_known = false;
  bool brake_engaged = true;
  std::string authorization_id;
  uint64_t authorization_expiry = 0;
};

struct ControlRequest {
  ControlActionKind action = ControlActionKind::Unknown;
  uint64_t evaluated_at_ms = 0;
  std::string request_id;
  std::string authorization_id;
  std::string input_units;
  std::string expected_input_units;
  bool input_schema_valid = false;
  bool input_finite = false;
  bool has_unknown_fields = true;
  bool has_missing_fields = true;
};

struct ControlSafetyDecision {
  bool allowed = false;
  std::vector<std::string> reasons;

  // A gate decision never creates an entity side effect.  In particular,
  // these remain false even when an offline simulation is allowed.
  bool motor_command_generated = false;
  bool motor_target_generated = false;
  bool serial_payload_generated = false;
};

struct ControlRoutePolicy {
  ControlActionKind action = ControlActionKind::Unknown;
  bool known = false;
  std::string expected_units;
  std::vector<std::string> allowed_fields;
  std::vector<std::string> required_fields;
  std::vector<std::string> numeric_fields;
};

struct ControlBodyValidation {
  bool schema_valid = false;
  bool finite = false;
  bool has_unknown_fields = true;
  bool has_missing_fields = true;
};

ControlSafetyState control_safety_snapshot(const SharedState& state);
ControlSafetyDecision evaluate_control_safety(
    const ControlSafetyState& state, const ControlRequest& request);

ControlRoutePolicy classify_control_post(const std::string& path);
ControlBodyValidation validate_control_body(
    const ControlRoutePolicy& policy, const std::string& body);

std::string control_safety_reasons_json(
    const ControlSafetyDecision& decision);

}  // namespace therapy_robot
