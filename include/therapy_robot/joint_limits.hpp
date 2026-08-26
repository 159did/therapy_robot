#pragma once

#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <array>
#include <cstdint>
#include <string>

namespace therapy_robot {

// Converts an SI joint state through the configured actuator mapping and
// rejects values that would exceed the active soft limits. This is pure data
// validation; it does not write shared memory or issue a motor command.
bool native_targets_from_joints(const SharedState& state,
                                const JointState& joints,
                                std::array<int64_t, kAxisCount>& requested,
                                std::string& reason);

}  // namespace therapy_robot
