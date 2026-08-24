#pragma once

#include <array>
#include <cstdint>

namespace therapy_robot {

constexpr const char* kDefaultSharedMemoryName = "/therapy_robot_shared_state";
constexpr int kGroupCount = 3;
constexpr int kMaxMotorsPerGroup = 2;
constexpr int kAxisCount = 5;

struct MotorState {
  int configured = 0;
  int motor_id = 0;
  int axis = 0;
  int online = 0;
  int enabled = 0;
  int fault = 0;
  int mode = 0;
  int brake_supported = 0;
  int brake_engaged = 0;
  int brake_release_requested = 0;
  int brake_state_known = 1;
  char brake_last_error[128]{};
  int64_t actual_motor_native = 0;
  int64_t target_motor_native = 0;
  int64_t active_target_motor_native = 0;
  double actual_axis_si = 0.0;
  double target_axis_si = 0.0;
  double actual_motor_native_velocity = 0.0;
  double actual_current_a = 0.0;
};

struct MotorGroupState {
  int group = 0;
  int hardware_enabled = 0;
  int motor_count = 0;
  char port[128]{};
  char last_error[256]{};
  std::array<MotorState, kMaxMotorsPerGroup> motors{};
};

struct AxisMapEntry {
  int group = 0;
  int axis = 0;
  int global_axis = 0;
  int kind = 0;
  char name[32]{};
  char gui_display_unit[16]{};
  double motor_native_to_gui_display = 1.0;
  int64_t min_motor_native = 0;
  int64_t max_motor_native = 0;
};

struct EndpointTarget {
  int valid = 0;
  uint64_t target_seq = 0;
  int status = 0;
  char last_error[256]{};
  double x_m = 0.0;
  double y_m = 0.0;
  double z_m = 0.0;
  double rx_rad = 0.0;
  double ry_rad = 0.0;
  double rz_rad = 0.0;
  double last_position_error_m = 0.0;
  double last_direction_error_rad = 0.0;
};

struct CollisionState {
  int configured = 0;
  int enabled = 0;
  int alarm = 0;
  int manual_recovery = 0;
  // Set only while the fixed K1-K4 recovery-home trajectory is executing.
  // It is deliberately separate from manual_recovery so normal commands
  // cannot inherit a collision-check bypass.
  int recovery_arm_zero_active = 0;
  uint64_t rejected_commands = 0;
  double path_fraction = 0.0;
  char status[32]{};
  char link_name[64]{};
  char obstacle_name[96]{};
  char last_error[256]{};
  char config_path[256]{};
};

struct CommandState {
  uint64_t command_seq = 0;
  int command_id = 0;
  uint64_t target_command_seq = 0;
  int target_command_id = 0;
  std::array<int64_t, kAxisCount> target_native{};
};

struct ControlState {
  uint64_t heartbeat_ms = 0;
  uint64_t active_target_seq = 0;
  int limit_alarm = 0;
  EndpointTarget endpoint_target{};
  CollisionState collision{};
};

struct SimulationState {
  int enabled = 1;
  int hardware_mode = 0;
  int mujoco_available = 0;
  double end_effector_x_m = 0.0;
  double end_effector_y_m = 0.0;
  double end_effector_z_m = 0.0;
};

// Central, fail-closed authorization context shared by every future entity
// control producer and the hardware command consumer.  No component in B8
// provisions a positive authorization; defaults therefore cannot unlock
// entity control.
struct EntityControlSafetyState {
  int execution_allowed = 0;
  int entity_action_authorized = 0;
  char hardware_mode[32]{};
  char h1_status[48]{};
  int emergency_stop = 0;
  int feedback_valid = 0;
  uint64_t feedback_age_ms = UINT64_MAX;
  char limit_state[32]{};
  char collision_state[32]{};
  char watchdog_state[32]{};
  int brake_state_known = 0;
  int brake_engaged = 1;
  char request_id[64]{};
  char authorization_id[64]{};
  uint64_t authorization_expiry = 0;
  char input_units[32]{};
  int input_schema_valid = 0;
  char last_rejection[256]{};
  uint64_t rejected_web_requests = 0;
  uint64_t rejected_motor_commands = 0;
};

struct SharedState {
  uint32_t magic = 0x54524f42;
  uint32_t version = 3;
  uint64_t core_heartbeat_ms = 0;
  uint64_t motor_heartbeat_ms = 0;
  uint64_t sim_heartbeat_ms = 0;
  uint64_t web_heartbeat_ms = 0;
  char run_mode[32]{};
  char system_state[32]{};
  int emergency_stop = 0;
  CommandState command{};
  ControlState control{};
  SimulationState simulation{};
  std::array<MotorGroupState, kGroupCount> groups{};
  std::array<AxisMapEntry, kAxisCount> axis_map{};
  EntityControlSafetyState control_safety{};
};

const char* shared_memory_name();
SharedState* open_or_create_shared_state(bool create);
void initialize_defaults(SharedState& state);
uint64_t now_ms();
void set_text(char* dst, unsigned long size, const char* src);

}
