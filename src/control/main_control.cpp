#include "therapy_robot/collision.hpp"
#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <chrono>
#include <atomic>
#include <cmath>
#include <csignal>
#include <iostream>
#include <thread>

using namespace therapy_robot;

namespace {
volatile std::sig_atomic_t running = 1;
void on_signal(int) { running = 0; }
constexpr double kRadToDeg = 180.0 / 3.14159265358979323846;

int64_t native_from_display(double display, const AxisMapEntry& axis) {
  if (std::abs(axis.motor_native_to_gui_display) < 1e-12) return 0;
  auto native = static_cast<int64_t>(std::llround(display / axis.motor_native_to_gui_display));
  if (native < axis.min_motor_native) native = axis.min_motor_native;
  if (native > axis.max_motor_native) native = axis.max_motor_native;
  return native;
}

void apply_joints(SharedState& state, const JointState& q) {
  state.command.target_native[0] = native_from_display(q.k0_m * 1000.0, state.axis_map[0]);
  state.command.target_native[1] = native_from_display(q.k1_rad * kRadToDeg, state.axis_map[1]);
  state.command.target_native[2] = native_from_display(q.k2_rad * kRadToDeg, state.axis_map[2]);
  state.command.target_native[3] = native_from_display(q.k3_rad * kRadToDeg, state.axis_map[3]);
  state.command.target_native[4] = native_from_display(q.k4_rad * kRadToDeg, state.axis_map[4]);
  std::atomic_thread_fence(std::memory_order_release);
  state.command.target_command_seq++;
}

JointState actual_joints(const SharedState& state) {
  return {
      state.groups[0].motors[0].actual_axis_si,
      state.groups[1].motors[0].actual_axis_si,
      state.groups[1].motors[1].actual_axis_si,
      state.groups[2].motors[0].actual_axis_si,
      state.groups[2].motors[1].actual_axis_si,
  };
}

void publish_collision_config(SharedState& state,
                              const CollisionConfig& config) {
  auto& collision = state.control.collision;
  collision.configured = config.configured ? 1 : 0;
  collision.enabled = config.enabled ? 1 : 0;
  set_text(collision.config_path, sizeof(collision.config_path),
           config.source_path.c_str());
  set_text(collision.status, sizeof(collision.status),
           config.enabled ? "ready" :
           (config.configured ? "disabled" : "not_configured"));
  set_text(collision.last_error, sizeof(collision.last_error),
           config.enabled ? "ok" : "collision boundary disabled");
}

void publish_collision_result(SharedState& state,
                              const CollisionCheck& result,
                              bool rejected) {
  auto& collision = state.control.collision;
  collision.alarm = result.ok ? 0 : 1;
  collision.path_fraction = result.path_fraction;
  set_text(collision.status, sizeof(collision.status),
           result.ok ? (result.checked ? "clear" : "disabled") : "rejected");
  set_text(collision.link_name, sizeof(collision.link_name),
           result.link_name.c_str());
  set_text(collision.obstacle_name, sizeof(collision.obstacle_name),
           result.obstacle_name.c_str());
  set_text(collision.last_error, sizeof(collision.last_error),
           result.reason.c_str());
  if (rejected) collision.rejected_commands++;
}
}

int main() {
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);
  try {
    auto* state = open_or_create_shared_state(false);
    const auto collision_config = collision_config_from_environment();
    publish_collision_config(*state, collision_config);
    uint64_t last_endpoint_seq = 0;
    while (running) {
      state->control.heartbeat_ms = now_ms();
      auto& ep = state->control.endpoint_target;
      if (ep.valid == 1 && ep.target_seq != last_endpoint_seq) {
        last_endpoint_seq = ep.target_seq;
        if (std::string(state->run_mode) == "hardware_relative") {
          ep.status = 3;
          set_text(ep.last_error, sizeof(ep.last_error),
                   "calibrated axis offsets are required for endpoint motion");
          std::this_thread::sleep_for(std::chrono::milliseconds(20));
          continue;
        }
        Pose target{ep.x_m, ep.y_m, ep.z_m, ep.rx_rad, ep.ry_rad, ep.rz_rad};
        const JointState current_joints = actual_joints(*state);
        auto result = inverse_kinematics(target, current_joints);
        if (result.ok) {
          auto collision = check_endpoint_motion(current_joints, result.joints,
                                                 collision_config);
          publish_collision_result(*state, collision, !collision.ok);
          if (!collision.ok) {
            ep.status = 3;
            set_text(ep.last_error, sizeof(ep.last_error),
                     collision.reason.c_str());
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            continue;
          }
          apply_joints(*state, result.joints);
          state->control.active_target_seq = ep.target_seq;
          ep.status = 2;
          set_text(ep.last_error, sizeof(ep.last_error), "ok");
          auto achieved = forward_kinematics(result.joints);
          ep.last_position_error_m = std::hypot(std::hypot(achieved.x_m - ep.x_m, achieved.y_m - ep.y_m), achieved.z_m - ep.z_m);
          auto a = axis_from_rx_ry(ep.rx_rad, ep.ry_rad);
          auto b = axis_from_rx_ry(achieved.rx_rad, achieved.ry_rad);
          double d = std::max(-1.0, std::min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
          ep.last_direction_error_rad = std::acos(d);
        } else {
          ep.status = 3;
          set_text(ep.last_error, sizeof(ep.last_error), result.error.c_str());
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  } catch (const std::exception& e) {
    std::cerr << "main_control: " << e.what() << '\n';
    return 1;
  }
  return 0;
}
