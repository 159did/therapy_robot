#include "therapy_robot/k0_prepare_sim.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace therapy_robot {
namespace {

constexpr const char* kSchemaVersion = "b3.k0-prepare-sim.v1";

bool is_finite(double value) { return std::isfinite(value); }

void require_finite(double value, const char* field) {
  if (!is_finite(value)) {
    throw std::invalid_argument(std::string(field) + " must be finite");
  }
}

void require_positive_time(std::uint64_t value, const char* field) {
  if (value == 0) {
    throw std::invalid_argument(std::string(field) + " must be positive");
  }
}

bool is_terminal_safe_state(K0PrepareState state) {
  return state == K0PrepareState::Storage ||
         state == K0PrepareState::HoldingSimulated ||
         state == K0PrepareState::StandbySimulated ||
         state == K0PrepareState::FaultLocked ||
         state == K0PrepareState::Aborted;
}

bool confirmation_matches(const K0PrepareSimEvent& event,
                          std::uint64_t cycle) {
  return event.confirmation_cycle().has_value() &&
         event.confirmation_cycle().value() == cycle;
}

std::optional<std::uint64_t> add_time(std::uint64_t now,
                                      std::uint64_t duration) {
  if (duration > std::numeric_limits<std::uint64_t>::max() - now) {
    return std::nullopt;
  }
  return now + duration;
}

void append_json_string(std::ostringstream& output, const std::string& value) {
  output.put('"');
  for (const unsigned char character : value) {
    switch (character) {
      case '"':
        output << "\\\"";
        break;
      case '\\':
        output << "\\\\";
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
          constexpr char hex[] = "0123456789abcdef";
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

struct Machine {
  K0PrepareState state = K0PrepareState::Storage;
  K0PrepareStopIntent stop_intent = K0PrepareStopIntent::None;
  std::string reason_code = "initialized";
  std::uint64_t now_ms = 0;
  double position_normalized = 0.0;
  std::uint64_t confirmation_cycle = 0;
  std::optional<std::uint64_t> confirmation_deadline_ms;
  std::optional<std::uint64_t> brake_deadline_ms;
  std::optional<std::uint64_t> feedback_deadline_ms;
  std::optional<std::uint64_t> hold_deadline_ms;
  std::optional<std::uint64_t> last_feedback_ms;
  std::vector<K0PrepareTraceEntry> trace;
};

void fail_locked(Machine& machine, K0PrepareStopIntent intent,
                 const std::string& reason) {
  machine.state = K0PrepareState::FaultLocked;
  machine.stop_intent = intent;
  machine.reason_code = reason;
  machine.confirmation_deadline_ms.reset();
  machine.brake_deadline_ms.reset();
  machine.feedback_deadline_ms.reset();
  machine.hold_deadline_ms.reset();
}

void abort_simulation(Machine& machine, const std::string& reason) {
  machine.state = K0PrepareState::Aborted;
  machine.stop_intent = K0PrepareStopIntent::None;
  machine.reason_code = reason;
  machine.confirmation_deadline_ms.reset();
  machine.brake_deadline_ms.reset();
  machine.feedback_deadline_ms.reset();
  machine.hold_deadline_ms.reset();
}

void add_trace(Machine& machine, std::uint64_t event_time,
               K0PrepareEventType event, K0PrepareState before) {
  machine.trace.emplace_back(machine.trace.size(), event_time, event, before,
                             machine.state, machine.stop_intent,
                             machine.reason_code, machine.position_normalized,
                             machine.confirmation_cycle);
}

void process_feedback(Machine& machine, const K0PrepareSimEvent& event,
                       const K0PrepareSimConfig& config) {
  if (!event.feedback_position_normalized().has_value()) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "feedback_value_missing");
    return;
  }
  const double position = event.feedback_position_normalized().value();
  if (!is_finite(position)) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "invalid_numeric_input");
    return;
  }
  const double minimum = config.storage_position_normalized() -
                         config.position_tolerance_normalized();
  const double maximum = config.prepare_position_normalized() +
                         config.position_tolerance_normalized();
  if (position < minimum || position > maximum) {
    fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                "soft_limit_exceeded");
    return;
  }
  machine.position_normalized = position;
  machine.last_feedback_ms = machine.now_ms;
  machine.feedback_deadline_ms = add_time(
      machine.now_ms, config.feedback_timeout_ms());
  if (!machine.feedback_deadline_ms.has_value()) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "time_overflow");
    return;
  }
  if (machine.state == K0PrepareState::LiftingSimulated &&
      position + config.position_tolerance_normalized() >=
          config.prepare_position_normalized()) {
    machine.state = K0PrepareState::Stopping;
    machine.stop_intent = K0PrepareStopIntent::ControlledStopSimulated;
    machine.reason_code = "prepare_position_reached";
  } else if (machine.state == K0PrepareState::LiftingSimulated) {
    machine.reason_code = "feedback_updated";
  } else if (machine.state == K0PrepareState::Stopping) {
    machine.reason_code = "stopping_feedback_updated";
  }
}

void process_clock(Machine& machine, const K0PrepareSimConfig& config) {
  if (machine.state == K0PrepareState::AwaitingOperatorConfirmation &&
      machine.confirmation_deadline_ms.has_value() &&
      machine.now_ms >= machine.confirmation_deadline_ms.value()) {
    abort_simulation(machine, "operator_confirmation_timeout");
    return;
  }
  if (machine.state == K0PrepareState::BrakePrecheck &&
      machine.brake_deadline_ms.has_value() &&
      machine.now_ms >= machine.brake_deadline_ms.value()) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "brake_precheck_timeout");
    return;
  }
  if (machine.state == K0PrepareState::LiftingSimulated) {
    if (!machine.feedback_deadline_ms.has_value() ||
        machine.now_ms >= machine.feedback_deadline_ms.value()) {
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "feedback_timeout");
      return;
    }
  }
  if (machine.state == K0PrepareState::HoldingSimulated &&
      machine.hold_deadline_ms.has_value() &&
      machine.now_ms >= machine.hold_deadline_ms.value()) {
    machine.state = K0PrepareState::StandbySimulated;
    machine.stop_intent = K0PrepareStopIntent::None;
    machine.reason_code = "standby_ready";
  }
  static_cast<void>(config);
}

void process_event(Machine& machine, const K0PrepareSimConfig& config,
                   const K0PrepareSimEvent& event) {
  if (event.at_ms() < machine.now_ms) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "clock_rollback");
    return;
  }
  machine.now_ms = event.at_ms();

  if (event.feedback_position_normalized().has_value() &&
      !is_finite(event.feedback_position_normalized().value())) {
    fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                "invalid_numeric_input");
    return;
  }

  switch (event.type()) {
    case K0PrepareEventType::EmergencyStop:
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "emergency_stop");
      return;
    case K0PrepareEventType::WatchdogTimeout:
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "watchdog_timeout");
      return;
    case K0PrepareEventType::FeedbackLost:
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "feedback_lost");
      return;
    case K0PrepareEventType::BrakePrecheckFailed:
      fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                  "brake_precheck_failed");
      return;
    case K0PrepareEventType::CollisionDetected:
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "collision_detected");
      return;
    case K0PrepareEventType::SoftLimitExceeded:
      fail_locked(machine, K0PrepareStopIntent::ImmediateStopSimulated,
                  "soft_limit_exceeded");
      return;
    case K0PrepareEventType::Unknown:
      fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                  "unknown_event");
      return;
    default:
      break;
  }

  if (machine.state == K0PrepareState::FaultLocked) {
    if (event.type() == K0PrepareEventType::FaultResetRequested &&
        event.fault_conditions_clear().has_value() &&
        event.fault_conditions_clear().value()) {
      machine.state = K0PrepareState::Storage;
      machine.stop_intent = K0PrepareStopIntent::None;
      machine.reason_code = "fault_reset_to_storage";
      machine.position_normalized = config.storage_position_normalized();
    } else {
      machine.reason_code = "fault_locked_requires_safe_reset";
    }
    return;
  }
  if (machine.state == K0PrepareState::Aborted) {
    if (event.type() == K0PrepareEventType::FaultResetRequested &&
        event.fault_conditions_clear().has_value() &&
        event.fault_conditions_clear().value()) {
      machine.state = K0PrepareState::Storage;
      machine.stop_intent = K0PrepareStopIntent::None;
      machine.reason_code = "abort_reset_to_storage";
      machine.position_normalized = config.storage_position_normalized();
    } else if (event.type() != K0PrepareEventType::StopRequested) {
      machine.reason_code = "aborted_requires_reset";
    }
    return;
  }

  if (event.type() == K0PrepareEventType::ClockAdvanced) {
    process_clock(machine, config);
    return;
  }

  switch (machine.state) {
    case K0PrepareState::Storage:
      if (event.type() == K0PrepareEventType::RequestPrepare) {
        ++machine.confirmation_cycle;
        machine.state = K0PrepareState::AwaitingOperatorConfirmation;
        machine.stop_intent = K0PrepareStopIntent::None;
        machine.reason_code = "awaiting_operator_confirmation";
        machine.confirmation_deadline_ms = add_time(
            machine.now_ms, config.confirmation_timeout_ms());
        if (!machine.confirmation_deadline_ms.has_value()) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "time_overflow");
        }
      } else if (event.type() != K0PrepareEventType::StopRequested) {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_storage_transition");
      }
      return;

    case K0PrepareState::AwaitingOperatorConfirmation:
      if (event.type() == K0PrepareEventType::OperatorConfirmed) {
        if (!confirmation_matches(event, machine.confirmation_cycle)) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "stale_confirmation_cycle");
          return;
        }
        machine.state = K0PrepareState::BrakePrecheck;
        machine.reason_code = "brake_precheck_pending";
        machine.confirmation_deadline_ms.reset();
        machine.brake_deadline_ms = add_time(
            machine.now_ms, config.brake_precheck_timeout_ms());
        if (!machine.brake_deadline_ms.has_value()) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "time_overflow");
        }
      } else if (event.type() == K0PrepareEventType::OperatorRejected) {
        if (!confirmation_matches(event, machine.confirmation_cycle)) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "stale_confirmation_cycle");
          return;
        }
        abort_simulation(machine, "operator_rejected");
      } else if (event.type() == K0PrepareEventType::StopRequested) {
        abort_simulation(machine, "operator_stop_before_lift");
      } else {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_confirmation_transition");
      }
      return;

    case K0PrepareState::BrakePrecheck:
      if (event.type() == K0PrepareEventType::BrakePrecheckPassed) {
        machine.state = K0PrepareState::LiftingSimulated;
        machine.stop_intent = K0PrepareStopIntent::None;
        machine.reason_code = "lifting_simulated_started";
        machine.brake_deadline_ms.reset();
        machine.last_feedback_ms.reset();
        machine.feedback_deadline_ms = add_time(
            machine.now_ms, config.feedback_timeout_ms());
        if (!machine.feedback_deadline_ms.has_value()) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "time_overflow");
        }
      } else if (event.type() == K0PrepareEventType::StopRequested) {
        abort_simulation(machine, "operator_stop_before_lift");
      } else {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_brake_transition");
      }
      return;

    case K0PrepareState::LiftingSimulated:
      if (event.type() == K0PrepareEventType::FeedbackUpdated) {
        process_feedback(machine, event, config);
      } else if (event.type() == K0PrepareEventType::StopRequested) {
        machine.state = K0PrepareState::Stopping;
        machine.stop_intent = K0PrepareStopIntent::ControlledStopSimulated;
        machine.reason_code = "operator_stop_requested";
      } else {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_lifting_transition");
      }
      return;

    case K0PrepareState::Stopping:
      if (event.type() == K0PrepareEventType::FeedbackUpdated) {
        process_feedback(machine, event, config);
      } else if (event.type() == K0PrepareEventType::SimulatedStopCompleted) {
        machine.state = K0PrepareState::HoldingSimulated;
        machine.stop_intent = K0PrepareStopIntent::None;
        machine.reason_code = "holding_simulated";
        machine.hold_deadline_ms = add_time(machine.now_ms,
                                            config.hold_duration_ms());
        if (!machine.hold_deadline_ms.has_value()) {
          fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                      "time_overflow");
        }
      } else if (event.type() != K0PrepareEventType::StopRequested) {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_stopping_transition");
      } else {
        machine.reason_code = "stop_already_requested";
      }
      return;

    case K0PrepareState::HoldingSimulated:
      if (event.type() == K0PrepareEventType::StopRequested) {
        abort_simulation(machine, "operator_stop_in_hold");
      } else if (event.type() != K0PrepareEventType::SimulatedStopCompleted) {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_holding_transition");
      } else {
        machine.reason_code = "holding_simulated";
      }
      return;

    case K0PrepareState::StandbySimulated:
      if (event.type() == K0PrepareEventType::StopRequested) {
        abort_simulation(machine, "operator_stop_in_standby");
      } else if (event.type() != K0PrepareEventType::ClockAdvanced) {
        fail_locked(machine, K0PrepareStopIntent::LockSimulated,
                    "illegal_standby_transition");
      }
      return;

    case K0PrepareState::FaultLocked:
    case K0PrepareState::Aborted:
      return;
  }
}

}  // namespace

const char* k0_prepare_state_name(K0PrepareState state) noexcept {
  switch (state) {
    case K0PrepareState::Storage:
      return "storage";
    case K0PrepareState::AwaitingOperatorConfirmation:
      return "awaiting_operator_confirmation";
    case K0PrepareState::BrakePrecheck:
      return "brake_precheck";
    case K0PrepareState::LiftingSimulated:
      return "lifting_simulated";
    case K0PrepareState::Stopping:
      return "stopping";
    case K0PrepareState::HoldingSimulated:
      return "holding_simulated";
    case K0PrepareState::StandbySimulated:
      return "standby_simulated";
    case K0PrepareState::FaultLocked:
      return "fault_locked";
    case K0PrepareState::Aborted:
      return "aborted";
  }
  return "unknown";
}

const char* k0_prepare_event_name(K0PrepareEventType event) noexcept {
  switch (event) {
    case K0PrepareEventType::RequestPrepare:
      return "request_prepare";
    case K0PrepareEventType::OperatorConfirmed:
      return "operator_confirmed";
    case K0PrepareEventType::OperatorRejected:
      return "operator_rejected";
    case K0PrepareEventType::BrakePrecheckPassed:
      return "brake_precheck_passed";
    case K0PrepareEventType::BrakePrecheckFailed:
      return "brake_precheck_failed";
    case K0PrepareEventType::FeedbackUpdated:
      return "feedback_updated";
    case K0PrepareEventType::SimulatedStopCompleted:
      return "simulated_stop_completed";
    case K0PrepareEventType::StopRequested:
      return "stop_requested";
    case K0PrepareEventType::EmergencyStop:
      return "emergency_stop";
    case K0PrepareEventType::WatchdogTimeout:
      return "watchdog_timeout";
    case K0PrepareEventType::FeedbackLost:
      return "feedback_lost";
    case K0PrepareEventType::CollisionDetected:
      return "collision_detected";
    case K0PrepareEventType::SoftLimitExceeded:
      return "soft_limit_exceeded";
    case K0PrepareEventType::ClockAdvanced:
      return "clock_advanced";
    case K0PrepareEventType::FaultResetRequested:
      return "fault_reset_requested";
    case K0PrepareEventType::Unknown:
      return "unknown";
  }
  return "unknown";
}

const char* k0_prepare_stop_intent_name(K0PrepareStopIntent intent) noexcept {
  switch (intent) {
    case K0PrepareStopIntent::None:
      return "none";
    case K0PrepareStopIntent::ControlledStopSimulated:
      return "controlled_stop_simulated";
    case K0PrepareStopIntent::ImmediateStopSimulated:
      return "immediate_stop_simulated";
    case K0PrepareStopIntent::LockSimulated:
      return "lock_simulated";
  }
  return "lock_simulated";
}

K0PrepareSimConfig::K0PrepareSimConfig(
    double storage_position_normalized, double prepare_position_normalized,
    double position_tolerance_normalized,
    double simulated_velocity_normalized_per_second,
    double simulated_stop_distance_normalized,
    std::uint64_t confirmation_timeout_ms,
    std::uint64_t brake_precheck_timeout_ms, std::uint64_t feedback_timeout_ms,
    std::uint64_t watchdog_timeout_ms, std::uint64_t hold_duration_ms)
    : storage_position_normalized_(storage_position_normalized),
      prepare_position_normalized_(prepare_position_normalized),
      position_tolerance_normalized_(position_tolerance_normalized),
      simulated_velocity_normalized_per_second_(
          simulated_velocity_normalized_per_second),
      simulated_stop_distance_normalized_(simulated_stop_distance_normalized),
      confirmation_timeout_ms_(confirmation_timeout_ms),
      brake_precheck_timeout_ms_(brake_precheck_timeout_ms),
      feedback_timeout_ms_(feedback_timeout_ms),
      watchdog_timeout_ms_(watchdog_timeout_ms),
      hold_duration_ms_(hold_duration_ms) {
  require_finite(storage_position_normalized_, "storage_position_normalized");
  require_finite(prepare_position_normalized_, "prepare_position_normalized");
  require_finite(position_tolerance_normalized_,
                 "position_tolerance_normalized");
  require_finite(simulated_velocity_normalized_per_second_,
                 "simulated_velocity_normalized_per_second");
  require_finite(simulated_stop_distance_normalized_,
                 "simulated_stop_distance_normalized");
  if (storage_position_normalized_ < 0.0 ||
      prepare_position_normalized_ <= storage_position_normalized_ ||
      prepare_position_normalized_ > 1.0 ||
      position_tolerance_normalized_ <= 0.0 ||
      position_tolerance_normalized_ >=
          prepare_position_normalized_ - storage_position_normalized_ ||
      simulated_velocity_normalized_per_second_ <= 0.0 ||
      simulated_stop_distance_normalized_ <= 0.0) {
    throw std::invalid_argument("invalid synthetic K0 prepare parameters");
  }
  require_positive_time(confirmation_timeout_ms_, "confirmation_timeout_ms");
  require_positive_time(brake_precheck_timeout_ms_,
                        "brake_precheck_timeout_ms");
  require_positive_time(feedback_timeout_ms_, "feedback_timeout_ms");
  require_positive_time(watchdog_timeout_ms_, "watchdog_timeout_ms");
  require_positive_time(hold_duration_ms_, "hold_duration_ms");
}

double K0PrepareSimConfig::storage_position_normalized() const noexcept {
  return storage_position_normalized_;
}
double K0PrepareSimConfig::prepare_position_normalized() const noexcept {
  return prepare_position_normalized_;
}
double K0PrepareSimConfig::position_tolerance_normalized() const noexcept {
  return position_tolerance_normalized_;
}
double K0PrepareSimConfig::simulated_velocity_normalized_per_second() const
    noexcept {
  return simulated_velocity_normalized_per_second_;
}
double K0PrepareSimConfig::simulated_stop_distance_normalized() const noexcept {
  return simulated_stop_distance_normalized_;
}
std::uint64_t K0PrepareSimConfig::confirmation_timeout_ms() const noexcept {
  return confirmation_timeout_ms_;
}
std::uint64_t K0PrepareSimConfig::brake_precheck_timeout_ms() const noexcept {
  return brake_precheck_timeout_ms_;
}
std::uint64_t K0PrepareSimConfig::feedback_timeout_ms() const noexcept {
  return feedback_timeout_ms_;
}
std::uint64_t K0PrepareSimConfig::watchdog_timeout_ms() const noexcept {
  return watchdog_timeout_ms_;
}
std::uint64_t K0PrepareSimConfig::hold_duration_ms() const noexcept {
  return hold_duration_ms_;
}

K0PrepareSimEvent::K0PrepareSimEvent(
    K0PrepareEventType type, std::uint64_t at_ms,
    std::optional<double> feedback_position_normalized,
    std::optional<std::uint64_t> confirmation_cycle,
    std::optional<bool> fault_conditions_clear)
    : type_(type),
      at_ms_(at_ms),
      feedback_position_normalized_(feedback_position_normalized),
      confirmation_cycle_(confirmation_cycle),
      fault_conditions_clear_(fault_conditions_clear) {}

K0PrepareEventType K0PrepareSimEvent::type() const noexcept { return type_; }
std::uint64_t K0PrepareSimEvent::at_ms() const noexcept { return at_ms_; }
const std::optional<double>&
K0PrepareSimEvent::feedback_position_normalized() const noexcept {
  return feedback_position_normalized_;
}
const std::optional<std::uint64_t>&
K0PrepareSimEvent::confirmation_cycle() const noexcept {
  return confirmation_cycle_;
}
const std::optional<bool>&
K0PrepareSimEvent::fault_conditions_clear() const noexcept {
  return fault_conditions_clear_;
}

K0PrepareTraceEntry::K0PrepareTraceEntry(
    std::size_t index, std::uint64_t at_ms, K0PrepareEventType event,
    K0PrepareState state_before, K0PrepareState state_after,
    K0PrepareStopIntent stop_intent, std::string reason_code,
    double position_normalized, std::uint64_t confirmation_cycle)
    : index_(index),
      at_ms_(at_ms),
      event_(event),
      state_before_(state_before),
      state_after_(state_after),
      stop_intent_(stop_intent),
      reason_code_(std::move(reason_code)),
      position_normalized_(position_normalized),
      confirmation_cycle_(confirmation_cycle) {}

std::size_t K0PrepareTraceEntry::index() const noexcept { return index_; }
std::uint64_t K0PrepareTraceEntry::at_ms() const noexcept { return at_ms_; }
K0PrepareEventType K0PrepareTraceEntry::event() const noexcept { return event_; }
K0PrepareState K0PrepareTraceEntry::state_before() const noexcept {
  return state_before_;
}
K0PrepareState K0PrepareTraceEntry::state_after() const noexcept {
  return state_after_;
}
K0PrepareStopIntent K0PrepareTraceEntry::stop_intent() const noexcept {
  return stop_intent_;
}
const std::string& K0PrepareTraceEntry::reason_code() const noexcept {
  return reason_code_;
}
double K0PrepareTraceEntry::position_normalized() const noexcept {
  return position_normalized_;
}
std::uint64_t K0PrepareTraceEntry::confirmation_cycle() const noexcept {
  return confirmation_cycle_;
}

K0PrepareSimResult::K0PrepareSimResult(
    K0PrepareSimConfig config, K0PrepareState final_state,
    double final_position_normalized, std::uint64_t confirmation_cycle,
    K0PrepareStopIntent stop_intent, std::string reason_code,
    std::vector<K0PrepareTraceEntry> trace)
    : config_(std::move(config)),
      final_state_(final_state),
      final_position_normalized_(final_position_normalized),
      confirmation_cycle_(confirmation_cycle),
      stop_intent_(stop_intent),
      reason_code_(std::move(reason_code)),
      trace_(std::move(trace)) {
  require_finite(final_position_normalized_, "final_position_normalized");
}

const char* K0PrepareSimResult::schema_version() const noexcept {
  return kSchemaVersion;
}
bool K0PrepareSimResult::synthetic() const noexcept { return true; }
bool K0PrepareSimResult::formal_use_allowed() const noexcept { return false; }
bool K0PrepareSimResult::motor_command_written() const noexcept { return false; }
bool K0PrepareSimResult::execution_allowed() const noexcept { return false; }
bool K0PrepareSimResult::entity_action_authorized() const noexcept {
  return false;
}
bool K0PrepareSimResult::nano_deployment_authorized() const noexcept {
  return false;
}
const K0PrepareSimConfig& K0PrepareSimResult::config() const noexcept {
  return config_;
}
K0PrepareState K0PrepareSimResult::final_state() const noexcept {
  return final_state_;
}
bool K0PrepareSimResult::final_safe_state() const noexcept {
  return is_terminal_safe_state(final_state_);
}
double K0PrepareSimResult::final_position_normalized() const noexcept {
  return final_position_normalized_;
}
std::uint64_t K0PrepareSimResult::confirmation_cycle() const noexcept {
  return confirmation_cycle_;
}
K0PrepareStopIntent K0PrepareSimResult::stop_intent() const noexcept {
  return stop_intent_;
}
const std::string& K0PrepareSimResult::reason_code() const noexcept {
  return reason_code_;
}
const std::vector<K0PrepareTraceEntry>& K0PrepareSimResult::trace() const noexcept {
  return trace_;
}

K0PrepareSimResult simulate_k0_prepare(
    const K0PrepareSimConfig& config,
    const std::vector<K0PrepareSimEvent>& events) {
  Machine machine;
  machine.position_normalized = config.storage_position_normalized();
  for (const auto& event : events) {
    const K0PrepareState before = machine.state;
    process_event(machine, config, event);
    add_trace(machine, event.at_ms(), event.type(), before);
  }
  return K0PrepareSimResult(config, machine.state, machine.position_normalized,
                            machine.confirmation_cycle, machine.stop_intent,
                            machine.reason_code, std::move(machine.trace));
}

std::string k0_prepare_result_json(const K0PrepareSimResult& result) {
  std::ostringstream output;
  output.imbue(std::locale::classic());
  output << "{\"entity_action_authorized\":";
  append_json_bool(output, result.entity_action_authorized());
  output << ",\"execution_allowed\":";
  append_json_bool(output, result.execution_allowed());
  output << ",\"confirmation_cycle\":" << result.confirmation_cycle();
  output << ",\"final_position_normalized\":";
  append_json_number(output, result.final_position_normalized());
  output << ",\"final_safe_state\":";
  append_json_bool(output, result.final_safe_state());
  output << ",\"final_state\":";
  append_json_string(output, k0_prepare_state_name(result.final_state()));
  output << ",\"formal_use_allowed\":";
  append_json_bool(output, result.formal_use_allowed());
  output << ",\"motor_command_written\":";
  append_json_bool(output, result.motor_command_written());
  output << ",\"nano_deployment_authorized\":";
  append_json_bool(output, result.nano_deployment_authorized());
  output << ",\"parameters\":{";
  output << "\"brake_precheck_timeout_ms\":"
         << result.config().brake_precheck_timeout_ms();
  output << ",\"confirmation_timeout_ms\":"
         << result.config().confirmation_timeout_ms();
  output << ",\"feedback_timeout_ms\":"
         << result.config().feedback_timeout_ms();
  output << ",\"hold_duration_ms\":"
         << result.config().hold_duration_ms();
  output << ",\"position_tolerance_normalized\":";
  append_json_number(output, result.config().position_tolerance_normalized());
  output << ",\"prepare_position_normalized\":";
  append_json_number(output, result.config().prepare_position_normalized());
  output << ",\"simulated_stop_distance_normalized\":";
  append_json_number(output,
                    result.config().simulated_stop_distance_normalized());
  output << ",\"simulated_velocity_normalized_per_second\":";
  append_json_number(
      output, result.config().simulated_velocity_normalized_per_second());
  output << ",\"storage_position_normalized\":";
  append_json_number(output, result.config().storage_position_normalized());
  output << ",\"watchdog_timeout_ms\":"
         << result.config().watchdog_timeout_ms() << "},\"reason_code\":";
  append_json_string(output, result.reason_code());
  output << ",\"schema_version\":";
  append_json_string(output, result.schema_version());
  output << ",\"stop_intent\":";
  append_json_string(output,
                    k0_prepare_stop_intent_name(result.stop_intent()));
  output << ",\"synthetic\":";
  append_json_bool(output, result.synthetic());
  output << ",\"units\":{\"position\":\"normalized\",\"time\":\"milliseconds\",\"velocity\":\"normalized_per_second\"}";
  output << ",\"trace\":[";
  for (std::size_t index = 0; index < result.trace().size(); ++index) {
    if (index != 0) output.put(',');
    const auto& entry = result.trace()[index];
    output << "{\"at_ms\":" << entry.at_ms()
           << ",\"confirmation_cycle\":" << entry.confirmation_cycle()
           << ",\"event\":";
    append_json_string(output, k0_prepare_event_name(entry.event()));
    output << ",\"index\":" << entry.index()
           << ",\"position_normalized\":";
    append_json_number(output, entry.position_normalized());
    output << ",\"reason_code\":";
    append_json_string(output, entry.reason_code());
    output << ",\"state_after\":";
    append_json_string(output, k0_prepare_state_name(entry.state_after()));
    output << ",\"state_before\":";
    append_json_string(output, k0_prepare_state_name(entry.state_before()));
    output << ",\"stop_intent\":";
    append_json_string(output,
                       k0_prepare_stop_intent_name(entry.stop_intent()));
    output.put('}');
  }
  output << "]}";
  return output.str();
}

}  // namespace therapy_robot
