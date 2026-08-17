#include "therapy_robot/readiness.hpp"

#include <cassert>
#include <iostream>

using namespace therapy_robot;

namespace {
ReadinessInput ready_input() {
  ReadinessInput input;
  input.source_state = {11, 22, 33};
  input.source_state_known = true;
  input.safety_state_known = true;
  input.configuration_known = true;
  input.collision_configured = true;
  input.collision_enabled = true;
  input.axes_configured = true;
  input.axes_online = true;
  input.axes_fault_free = true;
  input.axes_enabled = false;
  input.formal_camera_extrinsics_present = true;
  input.entity_offsets_verified = true;
  input.formal_k0_parameters_present = true;
  input.nano_configuration_present = true;
  input.software_commit = "ad971a0";
  input.config_hashes["collision_config"] = "sha256:collision";
  input.config_hashes["formal_camera_extrinsics"] = "sha256:camera";
  input.config_hashes["entity_offsets"] = "sha256:offsets";
  input.config_hashes["formal_k0_parameters"] = "sha256:k0";
  input.config_hashes["nano_configuration"] = "sha256:nano";
  return input;
}
}  // namespace

int main() {
  const auto input = ready_input();
  const auto first = issue_readiness_attestation(input, 1000, 900000);
  const auto second = issue_readiness_attestation(input, 1000, 300000);
  assert(first.ok);
  assert(first.expires_at_ms - first.issued_at_ms == 300000);
  assert(first.attestation_id == second.attestation_id);
  assert(verify_readiness_attestation(first, input, 1000, nullptr));
  assert(verify_readiness_attestation(first, input, first.expires_at_ms, nullptr));

  std::string reason;
  assert(!verify_readiness_attestation(first, input, 999, &reason));
  assert(reason == "clock_rollback");
  assert(!verify_readiness_attestation(first, input, first.expires_at_ms + 1, &reason));
  assert(reason == "attestation_expired");

  auto changed = input;
  changed.source_state.command_seq++;
  assert(!verify_readiness_attestation(first, changed, 2000, &reason));
  assert(reason == "source_changed");

  auto tampered = first;
  tampered.checks.front().observed = "tampered";
  assert(!verify_readiness_attestation(tampered, input, 2000, &reason));
  assert(reason == "attestation_id_mismatch");

  auto blocked = input;
  blocked.formal_camera_extrinsics_present = false;
  const auto blocked_attestation = issue_readiness_attestation(blocked, 1000);
  assert(!blocked_attestation.ok);
  assert(!blocked_attestation.blocking_reasons.empty());
  const auto json = readiness_attestation_json(blocked_attestation);
  assert(json.find("\"schema_version\":\"b3.v1\"") != std::string::npos);
  assert(json.find("\"motor_command_written\":false") != std::string::npos);
  assert(json.find("\"execution_allowed\":false") != std::string::npos);
  assert(json.find("missing_formal_camera_extrinsics") != std::string::npos);
  std::cout << "PASS: readiness facts, fingerprint, expiry and JSON are deterministic\n";
  return 0;
}
