#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <chrono>
#include <cmath>
#include <csignal>
#include <iostream>
#include <thread>

using namespace therapy_robot;

namespace {
volatile std::sig_atomic_t running = 1;
void on_signal(int) { running = 0; }
constexpr double kDegToRad = 3.14159265358979323846 / 180.0;

double display_from_native(const SharedState& state, int idx, int group, int axis) {
  const auto& m = state.groups[group].motors[axis];
  return m.actual_motor_native * state.axis_map[idx].motor_native_to_gui_display;
}
}

int main() {
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);
  try {
    auto* state = open_or_create_shared_state(false);
    while (running) {
      state->sim_heartbeat_ms = now_ms();
      JointState q;
      q.k0_m = display_from_native(*state, 0, 0, 0) / 1000.0;
      q.k1_rad = display_from_native(*state, 1, 1, 0) * kDegToRad;
      q.k2_rad = display_from_native(*state, 2, 1, 1) * kDegToRad;
      q.k3_rad = display_from_native(*state, 3, 2, 0) * kDegToRad;
      q.k4_rad = display_from_native(*state, 4, 2, 1) * kDegToRad;
      auto pose = forward_kinematics(q);
      state->simulation.enabled = 1;
      state->simulation.end_effector_x_m = pose.x_m;
      state->simulation.end_effector_y_m = pose.y_m;
      state->simulation.end_effector_z_m = pose.z_m;
      std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
  } catch (const std::exception& e) {
    std::cerr << "main_sim: " << e.what() << '\n';
    return 1;
  }
  return 0;
}