#include "therapy_robot/control_safety_gate.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>

using namespace therapy_robot;

#ifdef NDEBUG
#undef assert
#define assert(condition)                                                       \
  do {                                                                          \
    if (!(condition)) {                                                         \
      std::cerr << "assertion failed: " #condition << '\n';                    \
      std::abort();                                                             \
    }                                                                           \
  } while (false)
#endif

namespace {

bool has_reason(const ControlSafetyDecision& decision, const char* reason) {
  return std::find(decision.reasons.begin(), decision.reasons.end(), reason) !=
         decision.reasons.end();
}

ControlSafetyState valid_state() {
  ControlSafetyState state;
  state.execution_allowed = true;
  state.entity_action_authorized = true;
  state.hardware_mode = "HARDWARE_CONTROL";
  state.h1_status = std::string("H1_ENTITY_READONLY_") + "PASS";
  state.emergency_stop = false;
  state.feedback_valid = true;
  state.feedback_age_ms = 1;
  state.limit_state = "OK";
  state.collision_state = "CLEAR";
  state.watchdog_state = "OK";
  state.brake_state_known = true;
  state.brake_engaged = true;
  state.authorization_id = "authorization-test";
  state.authorization_expiry = 2000;
  return state;
}

ControlRequest valid_request() {
  ControlRequest request;
  request.action = ControlActionKind::EntityControl;
  request.evaluated_at_ms = 1000;
  request.request_id = "request-test";
  request.authorization_id = "authorization-test";
  request.input_units = "SI";
  request.expected_input_units = "SI";
  request.input_schema_valid = true;
  request.input_finite = true;
  request.has_unknown_fields = false;
  request.has_missing_fields = false;
  return request;
}

template <typename Mutator>
void expect_rejection(const char* reason, Mutator mutate) {
  auto state = valid_state();
  auto request = valid_request();
  mutate(state, request);
  const auto decision = evaluate_control_safety(state, request);
  assert(!decision.allowed);
  assert(has_reason(decision, reason));
  assert(!decision.motor_command_generated);
  assert(!decision.motor_target_generated);
  assert(!decision.serial_payload_generated);
}

}  // namespace

int main() {
  SharedState shared;
  initialize_defaults(shared);
  auto default_request = valid_request();
  const auto default_decision = evaluate_control_safety(
      control_safety_snapshot(shared), default_request);
  assert(!default_decision.allowed);
  assert(has_reason(default_decision, "hardware_control_mode_not_explicit"));
  assert(std::string(shared.control_safety.h1_status) ==
         "H1_ENTITY_READONLY_PASS");
  assert(shared.control_safety.execution_allowed == 0);
  assert(shared.control_safety.entity_action_authorized == 0);

  expect_rejection("h1_status_not_pass", [](auto& state, auto&) {
    state.h1_status = "H1_STATUS_NOT_READY";
  });
  expect_rejection("hardware_control_mode_not_explicit", [](auto& state, auto&) {
    state.hardware_mode = "HARDWARE_READONLY";
  });
  expect_rejection("emergency_stop_active", [](auto& state, auto&) {
    state.emergency_stop = true;
  });
  expect_rejection("feedback_invalid", [](auto& state, auto&) {
    state.feedback_valid = false;
  });
  expect_rejection("feedback_expired", [](auto& state, auto&) {
    state.feedback_age_ms = kControlFeedbackMaxAgeMs + 1;
  });
  expect_rejection("watchdog_timeout", [](auto& state, auto&) {
    state.watchdog_state = "TIMEOUT";
  });
  expect_rejection("limit_state_abnormal", [](auto& state, auto&) {
    state.limit_state = "ALARM";
  });
  expect_rejection("collision_state_abnormal", [](auto& state, auto&) {
    state.collision_state = "COLLISION";
  });
  expect_rejection("brake_state_unknown", [](auto& state, auto&) {
    state.brake_state_known = false;
  });
  expect_rejection("execution_not_allowed", [](auto& state, auto&) {
    state.execution_allowed = false;
  });
  expect_rejection("entity_action_not_authorized", [](auto& state, auto&) {
    state.entity_action_authorized = false;
  });
  expect_rejection("authorization_expired", [](auto& state, auto& request) {
    state.authorization_expiry = request.evaluated_at_ms;
  });
  expect_rejection("request_id_missing", [](auto&, auto& request) {
    request.request_id.clear();
  });
  expect_rejection("authorization_id_missing", [](auto&, auto& request) {
    request.authorization_id.clear();
  });
  expect_rejection("input_non_finite", [](auto&, auto& request) {
    const double value = std::numeric_limits<double>::quiet_NaN();
    request.input_finite = std::isfinite(value);
  });
  expect_rejection("input_non_finite", [](auto&, auto& request) {
    const double value = std::numeric_limits<double>::infinity();
    request.input_finite = std::isfinite(value);
  });
  expect_rejection("input_units_wrong", [](auto&, auto& request) {
    request.input_units = "mm";
  });
  expect_rejection("unknown_input_field", [](auto&, auto& request) {
    request.has_unknown_fields = true;
  });
  expect_rejection("missing_input_field", [](auto&, auto& request) {
    request.has_missing_fields = true;
  });

  const auto valid = evaluate_control_safety(valid_state(), valid_request());
  assert(valid.allowed);
  assert(!valid.motor_command_generated);
  assert(!valid.motor_target_generated);
  assert(!valid.serial_payload_generated);

  ControlRequest simulation;
  simulation.action = ControlActionKind::OfflineSimulation;
  simulation.evaluated_at_ms = 1000;
  simulation.input_units = "enum";
  simulation.expected_input_units = "enum";
  simulation.input_schema_valid = true;
  simulation.input_finite = true;
  simulation.has_unknown_fields = false;
  simulation.has_missing_fields = false;
  ControlSafetyState simulation_state;
  const auto simulation_decision =
      evaluate_control_safety(simulation_state, simulation);
  assert(simulation_decision.allowed);
  assert(!simulation_decision.motor_command_generated);
  assert(!simulation_decision.motor_target_generated);
  assert(!simulation_decision.serial_payload_generated);
  simulation_state.hardware_mode = "HARDWARE_READONLY";
  assert(!evaluate_control_safety(simulation_state, simulation).allowed);

  const auto speed = classify_control_post("/api/speed");
  assert(speed.action == ControlActionKind::OfflineSimulation);
  const auto speed_body = validate_control_body(speed, "{\"multiplier\": 0.42}");
  assert(speed_body.schema_valid);
  auto speed_request = simulation;
  speed_request.input_units = "ratio";
  speed_request.expected_input_units = "ratio";
  speed_request.input_schema_valid = speed_body.schema_valid;
  speed_request.input_finite = speed_body.finite;
  speed_request.has_unknown_fields = speed_body.has_unknown_fields;
  speed_request.has_missing_fields = speed_body.has_missing_fields;
  assert(evaluate_control_safety(ControlSafetyState{}, speed_request).allowed);

  ControlRequest stop;
  stop.action = ControlActionKind::FailSafeStop;
  assert(evaluate_control_safety(ControlSafetyState{}, stop).allowed);

  const auto targets = classify_control_post("/api/command/targets");
  assert(targets.known && targets.action == ControlActionKind::EntityControl);
  auto target_body = validate_control_body(
      targets, "{\"g0a0\":0,\"g1a0\":1,\"g1a1\":2,\"g2a0\":3,\"g2a1\":4}");
  assert(target_body.schema_valid && target_body.finite);
  target_body = validate_control_body(
      targets, "{\"g0a0\":NaN,\"g1a0\":1,\"g1a1\":2,\"g2a0\":3,\"g2a1\":4}");
  assert(!target_body.schema_valid && !target_body.finite);
  target_body = validate_control_body(
      targets, "{\"g0a0\":0,\"g1a0\":1,\"g1a1\":2,\"g2a0\":3,\"g2a1\":4,\"extra\":5}");
  assert(!target_body.schema_valid && target_body.has_unknown_fields);
  target_body = validate_control_body(targets, "{\"g0a0\":0}");
  assert(!target_body.schema_valid && target_body.has_missing_fields);

  std::cout << "platform=x86_64_vm host=zzqVM nano_tested=false "
               "arm64_tested=false entity_hardware_tested=false\n";
  std::cout << "control safety gate tests passed\n";
  return 0;
}
