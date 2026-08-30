#include "therapy_robot/control_safety_gate.hpp"

#include "therapy_robot/shared_memory.hpp"

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <set>
#include <sstream>
#include <unordered_map>
#include <utility>

namespace therapy_robot {
namespace {

void reject(ControlSafetyDecision& decision, const char* reason) {
  decision.reasons.emplace_back(reason);
}

bool equals_any(const std::string& value,
                std::initializer_list<const char*> expected) {
  for (const char* item : expected) {
    if (value == item) return true;
  }
  return false;
}

std::string trim(std::string value) {
  const auto begin = value.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos) return {};
  const auto end = value.find_last_not_of(" \t\r\n");
  return value.substr(begin, end - begin + 1);
}

bool parse_flat_json_object(const std::string& body,
                            std::unordered_map<std::string, std::string>& values) {
  const std::string text = trim(body);
  if (text.empty()) return true;
  if (text.size() < 2 || text.front() != '{' || text.back() != '}') return false;
  std::size_t index = 1;
  while (index + 1 < text.size()) {
    while (index + 1 < text.size() &&
           (std::isspace(static_cast<unsigned char>(text[index])) ||
            text[index] == ',')) {
      ++index;
    }
    if (index + 1 == text.size()) break;
    if (text[index] != '"') return false;
    ++index;
    std::string key;
    bool escaped = false;
    for (; index < text.size(); ++index) {
      const char ch = text[index];
      if (escaped) {
        key += ch;
        escaped = false;
      } else if (ch == '\\') {
        escaped = true;
      } else if (ch == '"') {
        break;
      } else {
        key += ch;
      }
    }
    if (index >= text.size() || text[index] != '"' || key.empty()) return false;
    ++index;
    while (index < text.size() &&
           std::isspace(static_cast<unsigned char>(text[index]))) ++index;
    if (index >= text.size() || text[index] != ':') return false;
    ++index;
    while (index < text.size() &&
           std::isspace(static_cast<unsigned char>(text[index]))) ++index;
    const std::size_t value_begin = index;
    bool in_string = false;
    escaped = false;
    for (; index < text.size() - 1; ++index) {
      const char ch = text[index];
      if (in_string && escaped) {
        escaped = false;
      } else if (in_string && ch == '\\') {
        escaped = true;
      } else if (ch == '"') {
        in_string = !in_string;
      } else if (!in_string && ch == ',') {
        break;
      }
    }
    if (in_string) return false;
    const std::string value = trim(text.substr(value_begin, index - value_begin));
    if (value.empty() || !values.emplace(key, value).second) return false;
    if (index < text.size() - 1 && text[index] == ',') ++index;
  }
  return true;
}

bool is_finite_number(const std::string& value) {
  errno = 0;
  char* end = nullptr;
  const double parsed = std::strtod(value.c_str(), &end);
  return end != value.c_str() && end && *end == '\0' && errno != ERANGE &&
         std::isfinite(parsed);
}

ControlRoutePolicy entity(std::string units,
                          std::vector<std::string> allowed = {},
                          std::vector<std::string> required = {},
                          std::vector<std::string> numeric = {}) {
  return {ControlActionKind::EntityControl, true, std::move(units),
          std::move(allowed), std::move(required), std::move(numeric)};
}

ControlRoutePolicy no_body(ControlActionKind action) {
  return {action, true, "none", {}, {}, {}};
}

}  // namespace

ControlSafetyState control_safety_snapshot(const SharedState& state) {
  ControlSafetyState result;
  const auto& source = state.control_safety;
  result.execution_allowed = source.execution_allowed != 0;
  result.entity_action_authorized = source.entity_action_authorized != 0;
  result.hardware_mode = source.hardware_mode;
  result.h1_status = source.h1_status;
  result.emergency_stop = state.emergency_stop != 0 || source.emergency_stop != 0;
  result.feedback_valid = source.feedback_valid != 0;
  result.feedback_age_ms = source.feedback_age_ms;
  result.limit_state = state.control.limit_alarm ? "ALARM" : source.limit_state;
  result.collision_state = state.control.collision.alarm ? "ALARM" : source.collision_state;
  result.watchdog_state = source.watchdog_state;
  result.brake_state_known = source.brake_state_known != 0;
  result.brake_engaged = source.brake_engaged != 0;
  result.authorization_id = source.authorization_id;
  result.authorization_expiry = source.authorization_expiry;
  return result;
}

ControlSafetyDecision evaluate_control_safety(
    const ControlSafetyState& state, const ControlRequest& request) {
  ControlSafetyDecision decision;

  if (request.action == ControlActionKind::FailSafeStop) {
    decision.allowed = true;
    return decision;
  }

  if (request.action == ControlActionKind::GuidedWorkflowStart) {
    if (!request.input_schema_valid) reject(decision, "input_schema_invalid");
    if (!request.input_finite) reject(decision, "input_non_finite");
    if (request.has_unknown_fields) reject(decision, "unknown_input_field");
    if (request.has_missing_fields) reject(decision, "missing_input_field");
    decision.allowed = decision.reasons.empty();
    return decision;
  }
  if (request.action == ControlActionKind::GuidedWorkflowAdvance &&
      state.hardware_mode == "SIMULATION") {
    if (!request.input_schema_valid) reject(decision, "input_schema_invalid");
    if (!request.input_finite) reject(decision, "input_non_finite");
    if (request.has_unknown_fields) reject(decision, "unknown_input_field");
    if (request.has_missing_fields) reject(decision, "missing_input_field");
    decision.allowed = decision.reasons.empty();
    return decision;
  }
  if (request.action == ControlActionKind::OfflineSimulation ||
      request.action == ControlActionKind::ReadOnlyComputation) {
    if (state.hardware_mode != "SIMULATION") {
      reject(decision, "offline_action_requires_simulation_mode");
    }
    if (!request.input_schema_valid) reject(decision, "input_schema_invalid");
    if (!request.input_finite) reject(decision, "input_non_finite");
    if (request.has_unknown_fields) reject(decision, "unknown_input_field");
    if (request.has_missing_fields) reject(decision, "missing_input_field");
    decision.allowed = decision.reasons.empty();
    return decision;
  }

  if (request.action != ControlActionKind::EntityControl) {
    reject(decision, "unknown_control_action");
    return decision;
  }

  if (state.hardware_mode != "HARDWARE_CONTROL")
    reject(decision, "hardware_control_mode_not_explicit");
  // H1 is an informational, read-only snapshot. Entity control is gated by
  // current hardware mode, explicit authorization and live feedback below.
  if (!state.execution_allowed) reject(decision, "execution_not_allowed");
  if (!state.entity_action_authorized)
    reject(decision, "entity_action_not_authorized");
  if (state.emergency_stop) reject(decision, "emergency_stop_active");
  if (!state.feedback_valid) reject(decision, "feedback_invalid");
  if (state.feedback_age_ms > kControlFeedbackMaxAgeMs)
    reject(decision, "feedback_expired");
  if (state.watchdog_state != "OK") reject(decision, "watchdog_timeout");
  if (state.limit_state != "OK") reject(decision, "limit_state_abnormal");
  if (state.collision_state != "CLEAR")
    reject(decision, "collision_state_abnormal");
  if (!state.brake_state_known) reject(decision, "brake_state_unknown");
  if (state.authorization_expiry == 0 ||
      request.evaluated_at_ms >= state.authorization_expiry)
    reject(decision, "authorization_expired");
  if (request.request_id.empty()) reject(decision, "request_id_missing");
  if (request.authorization_id.empty())
    reject(decision, "authorization_id_missing");
  else if (state.authorization_id.empty() ||
           request.authorization_id != state.authorization_id)
    reject(decision, "authorization_id_mismatch");
  if (!request.input_finite) reject(decision, "input_non_finite");
  if (request.input_units.empty()) reject(decision, "input_units_missing");
  else if (request.expected_input_units.empty() ||
           request.input_units != request.expected_input_units)
    reject(decision, "input_units_wrong");
  if (!request.input_schema_valid) reject(decision, "input_schema_invalid");
  if (request.has_unknown_fields) reject(decision, "unknown_input_field");
  if (request.has_missing_fields) reject(decision, "missing_input_field");

  decision.allowed = decision.reasons.empty();
  return decision;
}

ControlRoutePolicy classify_control_post(const std::string& path) {
  if (path == "/api/motion_test/simulate")
    return {ControlActionKind::OfflineSimulation, true, "enum",
            {"side"}, {"side"}, {}};
  if (path == "/api/speed")
    return {ControlActionKind::OfflineSimulation, true, "ratio",
            {"multiplier"}, {"multiplier"}, {"multiplier"}};
  if (path == "/api/workflow/start")
    return {ControlActionKind::GuidedWorkflowStart, true, "enum",
            {"side"}, {"side"}, {}};
  if (path == "/api/workflow/back")
    return {ControlActionKind::GuidedWorkflowStart, true, "enum",
            {"side"}, {"side"}, {}};
  if (path == "/api/workflow/advance")
    return {ControlActionKind::GuidedWorkflowAdvance, true, "workflow",
            {"side", "index"}, {"side", "index"}, {"index"}};
  if (path == "/api/ik/check") {
    const std::vector<std::string> pose =
        {"x_m", "y_m", "z_m", "rx_rad", "ry_rad", "rz_rad"};
    return {ControlActionKind::ReadOnlyComputation, true, "SI", pose, pose, pose};
  }
  if (equals_any(path, {"/api/command/emergency_stop",
                        "/api/command/stop_all",
                        "/api/motion_test/sequence/stop",
                        "/api/acupoint_sequence/stop"})) {
    return no_body(ControlActionKind::FailSafeStop);
  }
  if (equals_any(path, {"/api/command/return_arm_zero",
                        "/api/command/return_z_zero",
                        "/api/motion_test/sequence/start",
                        "/api/acupoint_sequence/start",
                        "/api/command/enable_all",
                        "/api/command/recover_arm_zero",
                        "/api/command/disable_all",
                        "/api/command/set_zero",
                        "/api/command/reset_emergency_stop",
                        "/api/command/clear_faults",
                        "/api/command/enable_limit_stop_recovery",
                        "/api/command/disable_limit_stop_recovery"})) {
    return entity("none");
  }
  if (path == "/api/command/targets") {
    const std::vector<std::string> keys =
        {"g0a0", "g1a0", "g1a1", "g2a0", "g2a1"};
    return entity("motor_native", keys, keys, keys);
  }
  if (path == "/api/command/jog_axis" ||
      path == "/api/command/recovery_jog_axis") {
    return entity("display", {"axis", "delta_display"},
                  {"axis", "delta_display"}, {"axis", "delta_display"});
  }
  if (path == "/api/command/jog_axis_continuous") {
    return entity("enum", {"axis", "direction"}, {"axis", "direction"},
                  {"axis", "direction"});
  }
  if (path == "/api/command/endpoint_jog") {
    return entity("mm", {"axis", "delta_mm"}, {"axis", "delta_mm"},
                  {"delta_mm"});
  }
  if (path == "/api/command/endpoint_target") {
    const std::vector<std::string> pose =
        {"x_m", "y_m", "z_m", "rx_rad", "ry_rad", "rz_rad"};
    return entity("SI", pose, pose, pose);
  }
  if (path == "/api/mode/switch")
    return entity("enum", {"mode"}, {"mode"}, {});
  if (path == "/api/motion_test/point") {
    return entity("workflow", {"side", "index", "name"}, {"side"},
                  {"index"});
  }
  if (path == "/api/reconcile/apply") {
    const std::vector<std::string> joints =
        {"k0_mm", "k1_deg", "k2_deg", "k3_deg", "k4_deg"};
    return entity("display", joints, joints, joints);
  }
  return {ControlActionKind::Unknown, false, {}, {}, {}, {}};
}

ControlBodyValidation validate_control_body(
    const ControlRoutePolicy& policy, const std::string& body) {
  ControlBodyValidation result;
  if (!policy.known) return result;

  std::unordered_map<std::string, std::string> values;
  if (!parse_flat_json_object(body, values)) return result;

  const std::set<std::string> allowed(policy.allowed_fields.begin(),
                                      policy.allowed_fields.end());
  result.has_unknown_fields = false;
  for (const auto& item : values) {
    if (!allowed.count(item.first)) result.has_unknown_fields = true;
  }
  result.has_missing_fields = false;
  for (const auto& required : policy.required_fields) {
    if (!values.count(required)) result.has_missing_fields = true;
  }
  result.finite = true;
  for (const auto& numeric : policy.numeric_fields) {
    const auto found = values.find(numeric);
    if (found != values.end() && !is_finite_number(found->second)) {
      result.finite = false;
    }
  }
  result.schema_valid = !result.has_unknown_fields &&
                        !result.has_missing_fields && result.finite;
  return result;
}

std::string control_safety_reasons_json(
    const ControlSafetyDecision& decision) {
  std::ostringstream out;
  out << '[';
  for (std::size_t index = 0; index < decision.reasons.size(); ++index) {
    if (index) out << ',';
    out << '"' << decision.reasons[index] << '"';
  }
  out << ']';
  return out.str();
}

}  // namespace therapy_robot
