#include "therapy_robot/shared_memory.hpp"

#include <cstring>

namespace therapy_robot {

namespace {
void configure_axis(AxisMapEntry& entry, int group, int axis, int global_axis, int kind,
                    const char* name, const char* unit, double scale,
                    int64_t min_native, int64_t max_native) {
  entry.group = group;
  entry.axis = axis;
  entry.global_axis = global_axis;
  entry.kind = kind;
  set_text(entry.name, sizeof(entry.name), name);
  set_text(entry.gui_display_unit, sizeof(entry.gui_display_unit), unit);
  entry.motor_native_to_gui_display = scale;
  entry.min_motor_native = min_native;
  entry.max_motor_native = max_native;
}
}

void initialize_defaults(SharedState& state) {
  state = SharedState{};
  state.magic = 0x54524f42;
  state.version = 3;
  set_text(state.run_mode, sizeof(state.run_mode), "sim");
  set_text(state.system_state, sizeof(state.system_state), "idle");
  set_text(state.control.collision.status,
           sizeof(state.control.collision.status), "not_configured");
  set_text(state.control.collision.last_error,
           sizeof(state.control.collision.last_error),
           "collision boundary is not configured");

  // The MG protocol position unit is motor-rotor angle: 0.01 degree/native.
  // Convert through each actuator's internal reducer and any external drive:
  // K0 MG6012E-i8B, 72:72 belt, 20 mm lead screw:
  //   20 / (36000 * 8) = 1/14400 mm/native.
  // K1 MG6012-i36, 60:80 belt: 0.01 / 36 * 60/80 = 1/4800 deg/native.
  // K2 MG8008-i9, 60:80 belt: 0.01 / 9 * 60/80 = 1/1200 deg/native.
  // K3/K4 MG5010-i10 direct: 0.01 / 10 = 1/1000 deg/native.
  // K0 stowed zero is the lower lift reference and positive K0 is upward.
  // Stable physical upper endpoint recorded on 2026-08-09. Keep all normal
  // commands at or below this absolute logical position; the real demo uses
  // 4508640 native (313.1 mm) only after its collision preflight passes.
  configure_axis(state.axis_map[0], 0, 0, 0, 0, "K0", "mm",
                 1.0 / 14400.0, 0, 4523124);
  configure_axis(state.axis_map[1], 1, 0, 1, 1, "K1", "deg",
                 1.0 / 4800.0, -432000, 432000);
  configure_axis(state.axis_map[2], 1, 1, 2, 1, "K2", "deg",
                 1.0 / 1200.0, -108000, 108000);
  configure_axis(state.axis_map[3], 2, 0, 3, 1, "K3", "deg",
                 1.0 / 1000.0, -45000, 45000);
  configure_axis(state.axis_map[4], 2, 1, 4, 1, "K4", "deg",
                 1.0 / 1000.0, -60000, 60000);

  for (int g = 0; g < kGroupCount; ++g) {
    auto& group = state.groups[g];
    group.group = g;
    group.hardware_enabled = 0;
    group.motor_count = g == 0 ? 1 : 2;
    set_text(group.port, sizeof(group.port), g == 0 ? "sim://g0" : (g == 1 ? "sim://g1" : "sim://g2"));
    for (int a = 0; a < group.motor_count; ++a) {
      auto& motor = group.motors[a];
      motor.configured = 1;
      motor.motor_id = a + 1;
      motor.axis = a;
      motor.online = 1;
      motor.enabled = 0;
      motor.brake_supported = 0;
      motor.brake_state_known = 1;
    }
  }
  state.simulation.enabled = 1;
  state.simulation.hardware_mode = 0;
  state.simulation.mujoco_available = 0;

  // B8 entity-control gate defaults.  H1 read-only evidence is complete;
  // no default, fixture, or runtime inference may promote it to PASS.
  state.control_safety.execution_allowed = 0;
  state.control_safety.entity_action_authorized = 0;
  set_text(state.control_safety.hardware_mode,
           sizeof(state.control_safety.hardware_mode), "SIMULATION");
  set_text(state.control_safety.h1_status,
           sizeof(state.control_safety.h1_status), "H1_ENTITY_READONLY_PASS");
  state.control_safety.emergency_stop = 0;
  state.control_safety.feedback_valid = 0;
  state.control_safety.feedback_age_ms = UINT64_MAX;
  set_text(state.control_safety.limit_state,
           sizeof(state.control_safety.limit_state), "UNKNOWN");
  set_text(state.control_safety.collision_state,
           sizeof(state.control_safety.collision_state), "UNKNOWN");
  set_text(state.control_safety.watchdog_state,
           sizeof(state.control_safety.watchdog_state), "UNKNOWN");
  state.control_safety.brake_state_known = 0;
  state.control_safety.brake_engaged = 1;
  state.control_safety.authorization_expiry = 0;
  set_text(state.control_safety.input_units,
           sizeof(state.control_safety.input_units), "UNSPECIFIED");
  state.control_safety.input_schema_valid = 0;
  set_text(state.control_safety.last_rejection,
           sizeof(state.control_safety.last_rejection), "default_deny");
}

}
