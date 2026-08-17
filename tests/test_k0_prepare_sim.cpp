#include "therapy_robot/k0_prepare_sim.hpp"

#include <cassert>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

using namespace therapy_robot;

namespace {

K0PrepareSimConfig config() {
  return K0PrepareSimConfig(0.0, 1.0, 0.01, 0.25, 0.05, 10000, 2000,
                            500, 1000, 500);
}

std::vector<K0PrepareSimEvent> normal() {
  return {{K0PrepareEventType::RequestPrepare, 0},
          {K0PrepareEventType::OperatorConfirmed, 1, std::nullopt, 1},
          {K0PrepareEventType::BrakePrecheckPassed, 2},
          {K0PrepareEventType::FeedbackUpdated, 100, 0.50},
          {K0PrepareEventType::FeedbackUpdated, 200, 1.00},
          {K0PrepareEventType::SimulatedStopCompleted, 201},
          {K0PrepareEventType::ClockAdvanced, 701}};
}

void expect_invalid_config() {
  bool rejected_nan = false;
  try {
    static_cast<void>(K0PrepareSimConfig(
        std::numeric_limits<double>::quiet_NaN(), 1.0, 0.01, 0.25, 0.05,
        10000, 2000, 500, 1000, 500));
  } catch (const std::invalid_argument&) {
    rejected_nan = true;
  }
  assert(rejected_nan);

  bool rejected_time = false;
  try {
    static_cast<void>(K0PrepareSimConfig(0.0, 1.0, 0.01, 0.25, 0.05, 0,
                                         2000, 500, 1000, 500));
  } catch (const std::invalid_argument&) {
    rejected_time = true;
  }
  assert(rejected_time);
}

}  // namespace

int main() {
  static_assert(!std::is_copy_assignable<K0PrepareSimConfig>::value);
  static_assert(!std::is_copy_assignable<K0PrepareSimEvent>::value);
  static_assert(!std::is_copy_assignable<K0PrepareTraceEntry>::value);
  static_assert(!std::is_copy_assignable<K0PrepareSimResult>::value);

  expect_invalid_config();
  assert(std::string(k0_prepare_state_name(K0PrepareState::Storage)) ==
         "storage");
  assert(std::string(k0_prepare_state_name(K0PrepareState::FaultLocked)) ==
         "fault_locked");
  assert(std::string(k0_prepare_event_name(K0PrepareEventType::Unknown)) ==
         "unknown");

  const auto events = normal();
  const auto first = simulate_k0_prepare(config(), events);
  const auto second = simulate_k0_prepare(config(), events);
  assert(first.final_state() == K0PrepareState::StandbySimulated);
  assert(first.final_safe_state());
  assert(first.trace().size() == events.size());
  assert(k0_prepare_result_json(first) == k0_prepare_result_json(second));
  for (std::size_t index = 0; index < first.trace().size(); ++index) {
    assert(first.trace()[index].index() == index);
    if (index > 0) {
      assert(first.trace()[index - 1].at_ms() <= first.trace()[index].at_ms());
    }
  }

  const std::vector<K0PrepareEventType> hard_faults = {
      K0PrepareEventType::EmergencyStop,
      K0PrepareEventType::WatchdogTimeout,
      K0PrepareEventType::FeedbackLost,
      K0PrepareEventType::CollisionDetected,
      K0PrepareEventType::SoftLimitExceeded,
      K0PrepareEventType::Unknown};
  for (const auto event : hard_faults) {
    const auto result = simulate_k0_prepare(
        config(), {{K0PrepareEventType::RequestPrepare, 0}, {event, 1}});
    assert(result.final_state() == K0PrepareState::FaultLocked);
    assert(result.final_safe_state());
    assert(!result.execution_allowed());
    assert(!result.motor_command_written());
  }

  const auto rollback = simulate_k0_prepare(
      config(), {{K0PrepareEventType::RequestPrepare, 10},
                 {K0PrepareEventType::ClockAdvanced, 9}});
  assert(rollback.reason_code() == "clock_rollback");
  assert(rollback.final_state() == K0PrepareState::FaultLocked);

  const auto boundary = simulate_k0_prepare(
      config(), {{K0PrepareEventType::RequestPrepare, 0},
                 {K0PrepareEventType::ClockAdvanced, 10000}});
  assert(boundary.final_state() == K0PrepareState::Aborted);
  assert(boundary.reason_code() == "operator_confirmation_timeout");

  const std::string json = k0_prepare_result_json(first);
  assert(json.find("\"motor_command_written\":false") !=
         std::string::npos);
  assert(json.find("shared_memory") == std::string::npos);
  assert(json.find("write_target") == std::string::npos);
  assert(json.find("\"synthetic\":true") != std::string::npos);
  assert(json.find("\"execution_allowed\":false") != std::string::npos);
  return 0;
}
