#include "therapy_robot/readiness.hpp"

#include "therapy_robot/motion_plan.hpp"

#include <algorithm>
#include <limits>
#include <sstream>
#include <utility>

namespace therapy_robot {
namespace {
constexpr std::uint64_t kMaxLifetimeMs = 300000;

std::string json_escape(const std::string& value) {
  std::string result;
  for (const char c : value) {
    if (c == '"') result += "\\\"";
    else if (c == '\\') result += "\\\\";
    else if (c == '\n') result += "\\n";
    else if (c == '\r') result += "\\r";
    else if (c == '\t') result += "\\t";
    else if (static_cast<unsigned char>(c) < 0x20) result += '?';
    else result += c;
  }
  return result;
}

void append_check(std::vector<ReadinessCheck>& checks, const char* id,
                  bool known, bool pass, const char* reason,
                  const char* observed) {
  ReadinessCheck check;
  check.id = id;
  check.status = known ? (pass ? "pass" : "fail") : "unknown";
  check.blocking = true;
  check.reason_code = known && pass ? std::string{}
                                    : (known ? reason : "unknown_" + std::string(id));
  check.observed = observed;
  checks.push_back(std::move(check));
}

std::vector<ReadinessCheck> make_checks(const ReadinessInput& input) {
  std::vector<ReadinessCheck> checks;
  append_check(checks, "source_state", input.source_state_known,
               input.source_state_known, "source_state_unknown",
               input.source_state_known ? "known" : "unknown");
  append_check(checks, "safety_state", input.safety_state_known,
               input.safety_state_known, "safety_state_unknown",
               input.safety_state_known ? "known" : "unknown");
  append_check(checks, "configuration", input.configuration_known,
               input.configuration_known, "configuration_unknown",
               input.configuration_known ? "known" : "unknown");
  append_check(checks, "software_commit", input.configuration_known,
               !input.software_commit.empty() && input.software_commit != "unknown",
               "software_commit_unknown",
               !input.software_commit.empty() && input.software_commit != "unknown"
                   ? "known" : "unknown");
  append_check(checks, "emergency_stop", input.safety_state_known,
               !input.emergency_stop, "emergency_stop_latched",
               input.emergency_stop ? "latched" : "clear");
  append_check(checks, "collision_config", input.safety_state_known,
               input.collision_configured && input.collision_enabled,
               "collision_config_unavailable",
               input.collision_configured && input.collision_enabled
                   ? "configured_enabled" : "not_configured_or_disabled");
  append_check(checks, "collision_alarm", input.safety_state_known,
               !input.collision_alarm, "collision_alarm_active",
               input.collision_alarm ? "active" : "clear");
  append_check(checks, "manual_recovery", input.safety_state_known,
               !input.manual_recovery, "manual_recovery_active",
               input.manual_recovery ? "active" : "clear");
  append_check(checks, "axes_configured", input.configuration_known,
               input.axes_configured, "axes_unconfigured",
               input.axes_configured ? "all_configured" : "not_all_configured");
  append_check(checks, "axes_online", input.safety_state_known,
               input.axes_online, "axis_offline",
               input.axes_online ? "all_online" : "not_all_online");
  append_check(checks, "axes_fault_free", input.safety_state_known,
               input.axes_fault_free, "axis_fault_present",
               input.axes_fault_free ? "clear" : "fault_present");
  append_check(checks, "axes_enabled", input.safety_state_known,
               !input.axes_enabled, "axes_enabled",
               input.axes_enabled ? "one_or_more_enabled" : "all_disabled");
  append_check(checks, "formal_camera_extrinsics", input.configuration_known,
               input.formal_camera_extrinsics_present,
               "missing_formal_camera_extrinsics",
               input.formal_camera_extrinsics_present ? "present" : "missing");
  append_check(checks, "entity_offsets", input.configuration_known,
               input.entity_offsets_verified, "entity_offsets_unverified",
               input.entity_offsets_verified ? "verified" : "unverified");
  append_check(checks, "formal_k0_parameters", input.configuration_known,
               input.formal_k0_parameters_present, "missing_formal_k0_parameters",
               input.formal_k0_parameters_present ? "present" : "missing");
  append_check(checks, "nano_configuration", input.configuration_known,
               input.nano_configuration_present, "missing_nano_configuration",
               input.nano_configuration_present ? "present" : "missing");
  return checks;
}

std::string source_material(const ReadinessInput& input) {
  std::ostringstream out;
  out << "schema=b3.v1\n"
      << "source_state_known=" << input.source_state_known << '\n'
      << "safety_state_known=" << input.safety_state_known << '\n'
      << "configuration_known=" << input.configuration_known << '\n'
      << "command_seq=" << input.source_state.command_seq << '\n'
      << "target_command_seq=" << input.source_state.target_command_seq << '\n'
      << "endpoint_target_seq=" << input.source_state.endpoint_target_seq << '\n'
      << "emergency_stop=" << input.emergency_stop << '\n'
      << "collision_configured=" << input.collision_configured << '\n'
      << "collision_enabled=" << input.collision_enabled << '\n'
      << "collision_alarm=" << input.collision_alarm << '\n'
      << "manual_recovery=" << input.manual_recovery << '\n'
      << "axes_configured=" << input.axes_configured << '\n'
      << "axes_online=" << input.axes_online << '\n'
      << "axes_fault_free=" << input.axes_fault_free << '\n'
      << "axes_enabled=" << input.axes_enabled << '\n'
      << "formal_camera_extrinsics_present=" << input.formal_camera_extrinsics_present << '\n'
      << "entity_offsets_verified=" << input.entity_offsets_verified << '\n'
      << "formal_k0_parameters_present=" << input.formal_k0_parameters_present << '\n'
      << "nano_configuration_present=" << input.nano_configuration_present << '\n'
      << "software_commit=" << input.software_commit << '\n';
  for (const auto& item : input.config_hashes)
    out << "config." << item.first << '=' << item.second << '\n';
  return out.str();
}

std::string fingerprint(const ReadinessInput& input) {
  return "sha256:" + sha256_hex(source_material(input));
}

std::string id_material(const ReadinessAttestation& value) {
  std::ostringstream out;
  out << "schema=b3.v1\n" << "ok=" << value.ok << '\n'
      << "issued_at_ms=" << value.issued_at_ms << '\n'
      << "expires_at_ms=" << value.expires_at_ms << '\n'
      << "command_seq=" << value.source_state.command_seq << '\n'
      << "target_command_seq=" << value.source_state.target_command_seq << '\n'
      << "endpoint_target_seq=" << value.source_state.endpoint_target_seq << '\n'
      << "source_fingerprint=" << value.source_fingerprint << '\n'
      << "software_commit=" << value.software_commit << '\n';
  for (const auto& item : value.config_hashes)
    out << "config." << item.first << '=' << item.second << '\n';
  for (const auto& check : value.checks)
    out << "check." << check.id << '=' << check.status << ':'
        << check.reason_code << ':' << check.observed << '\n';
  return out.str();
}

std::string attestation_id(const ReadinessAttestation& value) {
  return "b3-attestation-" + sha256_hex(id_material(value));
}

void checks_json(std::ostringstream& out, const std::vector<ReadinessCheck>& checks) {
  out << '[';
  for (std::size_t index = 0; index < checks.size(); ++index) {
    if (index) out << ',';
    const auto& check = checks[index];
    out << "{\"id\":\"" << json_escape(check.id)
        << "\",\"status\":\"" << json_escape(check.status)
        << "\",\"blocking\":" << (check.blocking ? "true" : "false")
        << ",\"reason_code\":";
    if (check.reason_code.empty()) out << "null";
    else out << "\"" << json_escape(check.reason_code) << "\"";
    out << ",\"observed\":\"" << json_escape(check.observed) << "\"}";
  }
  out << ']';
}
}  // namespace

ReadinessAttestation issue_readiness_attestation(
    const ReadinessInput& input, std::uint64_t issued_at_ms,
    std::uint64_t requested_lifetime_ms) {
  ReadinessAttestation value;
  value.issued_at_ms = issued_at_ms;
  const auto lifetime = std::min(requested_lifetime_ms, kMaxLifetimeMs);
  value.expires_at_ms = issued_at_ms > std::numeric_limits<std::uint64_t>::max() - lifetime
                            ? std::numeric_limits<std::uint64_t>::max()
                            : issued_at_ms + lifetime;
  value.source_state = input.source_state;
  value.source_fingerprint = fingerprint(input);
  value.software_commit = input.software_commit;
  value.config_hashes = input.config_hashes;
  value.checks = make_checks(input);
  for (const auto& check : value.checks)
    if (check.blocking && check.status != "pass") value.blocking_reasons.push_back(check);
  value.ok = value.blocking_reasons.empty();
  value.attestation_id = attestation_id(value);
  return value;
}

bool verify_readiness_attestation(const ReadinessAttestation& value,
                                  const ReadinessInput& current,
                                  std::uint64_t now_ms, std::string* reason) {
  const auto fail = [&](const char* message) {
    if (reason) *reason = message;
    return false;
  };
  if (value.expires_at_ms < value.issued_at_ms) return fail("invalid_attestation_interval");
  if (value.expires_at_ms - value.issued_at_ms > kMaxLifetimeMs)
    return fail("attestation_lifetime_exceeds_limit");
  if (now_ms < value.issued_at_ms) return fail("clock_rollback");
  if (now_ms > value.expires_at_ms) return fail("attestation_expired");
  if (attestation_id(value) != value.attestation_id) return fail("attestation_id_mismatch");
  const auto expected = issue_readiness_attestation(
      current, value.issued_at_ms, value.expires_at_ms - value.issued_at_ms);
  if (expected.source_fingerprint != value.source_fingerprint) return fail("source_changed");
  if (expected.attestation_id != value.attestation_id) return fail("attestation_id_mismatch");
  if (!value.ok) return fail("readiness_blocked");
  return true;
}

std::string readiness_attestation_json(const ReadinessAttestation& value) {
  std::ostringstream out;
  out << "{\"schema_version\":\"b3.v1\",\"ok\":" << (value.ok ? "true" : "false")
      << ",\"motor_command_written\":false,\"execution_allowed\":false"
      << ",\"entity_action_authorized\":false,\"nano_deployment_authorized\":false"
      << ",\"authorization_scope\":\"software_precheck_only\""
      << ",\"attestation_id\":\"" << json_escape(value.attestation_id)
      << "\",\"issued_at_ms\":" << value.issued_at_ms
      << ",\"expires_at_ms\":" << value.expires_at_ms
      << ",\"source_state\":{\"command_seq\":" << value.source_state.command_seq
      << ",\"target_command_seq\":" << value.source_state.target_command_seq
      << ",\"endpoint_target_seq\":" << value.source_state.endpoint_target_seq << '}'
      << ",\"source_fingerprint\":\"" << json_escape(value.source_fingerprint)
      << "\",\"software_commit\":\"" << json_escape(value.software_commit)
      << "\",\"config_hashes\":{";
  std::size_t index = 0;
  for (const auto& item : value.config_hashes) {
    if (index++) out << ',';
    out << "\"" << json_escape(item.first) << "\":\"" << json_escape(item.second) << "\"";
  }
  out << "},\"checks\":";
  checks_json(out, value.checks);
  out << ",\"blocking_reasons\":";
  checks_json(out, value.blocking_reasons);
  out << '}';
  return out.str();
}

}  // namespace therapy_robot
