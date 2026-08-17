#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace therapy_robot {

enum class K0PrepareState {
  Storage,
  AwaitingOperatorConfirmation,
  BrakePrecheck,
  LiftingSimulated,
  Stopping,
  HoldingSimulated,
  StandbySimulated,
  FaultLocked,
  Aborted,
};

enum class K0PrepareEventType {
  RequestPrepare,
  OperatorConfirmed,
  OperatorRejected,
  BrakePrecheckPassed,
  BrakePrecheckFailed,
  FeedbackUpdated,
  SimulatedStopCompleted,
  StopRequested,
  EmergencyStop,
  WatchdogTimeout,
  FeedbackLost,
  CollisionDetected,
  SoftLimitExceeded,
  ClockAdvanced,
  FaultResetRequested,
  Unknown,
};

enum class K0PrepareStopIntent {
  None,
  ControlledStopSimulated,
  ImmediateStopSimulated,
  LockSimulated,
};

const char* k0_prepare_state_name(K0PrepareState state) noexcept;
const char* k0_prepare_event_name(K0PrepareEventType event) noexcept;
const char* k0_prepare_stop_intent_name(K0PrepareStopIntent intent) noexcept;

class K0PrepareSimConfig final {
 public:
  K0PrepareSimConfig(
      double storage_position_normalized,
      double prepare_position_normalized,
      double position_tolerance_normalized,
      double simulated_velocity_normalized_per_second,
      double simulated_stop_distance_normalized,
      std::uint64_t confirmation_timeout_ms,
      std::uint64_t brake_precheck_timeout_ms,
      std::uint64_t feedback_timeout_ms,
      std::uint64_t watchdog_timeout_ms,
      std::uint64_t hold_duration_ms);

  K0PrepareSimConfig(const K0PrepareSimConfig&) = default;
  K0PrepareSimConfig(K0PrepareSimConfig&&) = default;
  K0PrepareSimConfig& operator=(const K0PrepareSimConfig&) = delete;
  K0PrepareSimConfig& operator=(K0PrepareSimConfig&&) = delete;

  double storage_position_normalized() const noexcept;
  double prepare_position_normalized() const noexcept;
  double position_tolerance_normalized() const noexcept;
  double simulated_velocity_normalized_per_second() const noexcept;
  double simulated_stop_distance_normalized() const noexcept;
  std::uint64_t confirmation_timeout_ms() const noexcept;
  std::uint64_t brake_precheck_timeout_ms() const noexcept;
  std::uint64_t feedback_timeout_ms() const noexcept;
  std::uint64_t watchdog_timeout_ms() const noexcept;
  std::uint64_t hold_duration_ms() const noexcept;

 private:
  const double storage_position_normalized_;
  const double prepare_position_normalized_;
  const double position_tolerance_normalized_;
  const double simulated_velocity_normalized_per_second_;
  const double simulated_stop_distance_normalized_;
  const std::uint64_t confirmation_timeout_ms_;
  const std::uint64_t brake_precheck_timeout_ms_;
  const std::uint64_t feedback_timeout_ms_;
  const std::uint64_t watchdog_timeout_ms_;
  const std::uint64_t hold_duration_ms_;
};

class K0PrepareSimEvent final {
 public:
  K0PrepareSimEvent(
      K0PrepareEventType type, std::uint64_t at_ms,
      std::optional<double> feedback_position_normalized = std::nullopt,
      std::optional<std::uint64_t> confirmation_cycle = std::nullopt,
      std::optional<bool> fault_conditions_clear = std::nullopt);

  K0PrepareSimEvent(const K0PrepareSimEvent&) = default;
  K0PrepareSimEvent(K0PrepareSimEvent&&) = default;
  K0PrepareSimEvent& operator=(const K0PrepareSimEvent&) = delete;
  K0PrepareSimEvent& operator=(K0PrepareSimEvent&&) = delete;

  K0PrepareEventType type() const noexcept;
  std::uint64_t at_ms() const noexcept;
  const std::optional<double>& feedback_position_normalized() const noexcept;
  const std::optional<std::uint64_t>& confirmation_cycle() const noexcept;
  const std::optional<bool>& fault_conditions_clear() const noexcept;

 private:
  const K0PrepareEventType type_;
  const std::uint64_t at_ms_;
  const std::optional<double> feedback_position_normalized_;
  const std::optional<std::uint64_t> confirmation_cycle_;
  const std::optional<bool> fault_conditions_clear_;
};

class K0PrepareTraceEntry final {
 public:
  K0PrepareTraceEntry(
      std::size_t index, std::uint64_t at_ms, K0PrepareEventType event,
      K0PrepareState state_before, K0PrepareState state_after,
      K0PrepareStopIntent stop_intent, std::string reason_code,
      double position_normalized, std::uint64_t confirmation_cycle);

  K0PrepareTraceEntry(const K0PrepareTraceEntry&) = default;
  K0PrepareTraceEntry(K0PrepareTraceEntry&&) = default;
  K0PrepareTraceEntry& operator=(const K0PrepareTraceEntry&) = delete;
  K0PrepareTraceEntry& operator=(K0PrepareTraceEntry&&) = delete;

  std::size_t index() const noexcept;
  std::uint64_t at_ms() const noexcept;
  K0PrepareEventType event() const noexcept;
  K0PrepareState state_before() const noexcept;
  K0PrepareState state_after() const noexcept;
  K0PrepareStopIntent stop_intent() const noexcept;
  const std::string& reason_code() const noexcept;
  double position_normalized() const noexcept;
  std::uint64_t confirmation_cycle() const noexcept;

 private:
  const std::size_t index_;
  const std::uint64_t at_ms_;
  const K0PrepareEventType event_;
  const K0PrepareState state_before_;
  const K0PrepareState state_after_;
  const K0PrepareStopIntent stop_intent_;
  const std::string reason_code_;
  const double position_normalized_;
  const std::uint64_t confirmation_cycle_;
};

class K0PrepareSimResult final {
 public:
  K0PrepareSimResult(K0PrepareSimConfig config, K0PrepareState final_state,
                     double final_position_normalized,
                     std::uint64_t confirmation_cycle,
                     K0PrepareStopIntent stop_intent,
                     std::string reason_code,
                     std::vector<K0PrepareTraceEntry> trace);

  K0PrepareSimResult(const K0PrepareSimResult&) = default;
  K0PrepareSimResult(K0PrepareSimResult&&) = default;
  K0PrepareSimResult& operator=(const K0PrepareSimResult&) = delete;
  K0PrepareSimResult& operator=(K0PrepareSimResult&&) = delete;

  const char* schema_version() const noexcept;
  bool synthetic() const noexcept;
  bool formal_use_allowed() const noexcept;
  bool motor_command_written() const noexcept;
  bool execution_allowed() const noexcept;
  bool entity_action_authorized() const noexcept;
  bool nano_deployment_authorized() const noexcept;
  const K0PrepareSimConfig& config() const noexcept;
  K0PrepareState final_state() const noexcept;
  bool final_safe_state() const noexcept;
  double final_position_normalized() const noexcept;
  std::uint64_t confirmation_cycle() const noexcept;
  K0PrepareStopIntent stop_intent() const noexcept;
  const std::string& reason_code() const noexcept;
  const std::vector<K0PrepareTraceEntry>& trace() const noexcept;

 private:
  const K0PrepareSimConfig config_;
  const K0PrepareState final_state_;
  const double final_position_normalized_;
  const std::uint64_t confirmation_cycle_;
  const K0PrepareStopIntent stop_intent_;
  const std::string reason_code_;
  const std::vector<K0PrepareTraceEntry> trace_;
};

K0PrepareSimResult simulate_k0_prepare(
    const K0PrepareSimConfig& config,
    const std::vector<K0PrepareSimEvent>& events);

std::string k0_prepare_result_json(const K0PrepareSimResult& result);

}  // namespace therapy_robot
