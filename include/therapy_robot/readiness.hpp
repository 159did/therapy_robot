#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace therapy_robot {

struct ReadinessSourceState {
  std::uint64_t command_seq = 0;
  std::uint64_t target_command_seq = 0;
  std::uint64_t endpoint_target_seq = 0;
};

struct ReadinessInput {
  ReadinessSourceState source_state{};
  bool source_state_known = false;
  bool safety_state_known = false;
  bool configuration_known = false;

  bool emergency_stop = false;
  bool collision_configured = false;
  bool collision_enabled = false;
  bool collision_alarm = false;
  bool manual_recovery = false;

  bool axes_configured = false;
  bool axes_online = false;
  bool axes_fault_free = false;
  bool axes_enabled = false;

  bool formal_camera_extrinsics_present = false;
  bool entity_offsets_verified = false;
  bool formal_k0_parameters_present = false;
  bool nano_configuration_present = false;

  std::string software_commit;
  std::map<std::string, std::string> config_hashes;
};

struct ReadinessCheck {
  std::string id;
  std::string status;
  bool blocking = false;
  std::string reason_code;
  std::string observed;
};

struct ReadinessAttestation {
  bool ok = false;
  std::string attestation_id;
  std::uint64_t issued_at_ms = 0;
  std::uint64_t expires_at_ms = 0;
  ReadinessSourceState source_state{};
  std::string source_fingerprint;
  std::string software_commit;
  std::map<std::string, std::string> config_hashes;
  std::vector<ReadinessCheck> checks;
  std::vector<ReadinessCheck> blocking_reasons;
};

ReadinessAttestation issue_readiness_attestation(
    const ReadinessInput& input, std::uint64_t issued_at_ms,
    std::uint64_t requested_lifetime_ms = 300000);

bool verify_readiness_attestation(const ReadinessAttestation& attestation,
                                 const ReadinessInput& current,
                                 std::uint64_t now_ms,
                                 std::string* reason);

std::string readiness_attestation_json(
    const ReadinessAttestation& attestation);

}  // namespace therapy_robot
