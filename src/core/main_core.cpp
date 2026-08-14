#include "therapy_robot/shared_memory.hpp"

#include <csignal>
#include <chrono>
#include <iostream>
#include <thread>

using namespace therapy_robot;

namespace {
volatile std::sig_atomic_t running = 1;
void on_signal(int) { running = 0; }
}

int main() {
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);
  try {
    SharedState* state = open_or_create_shared_state(true);
    initialize_defaults(*state);
    while (running) {
      state->core_heartbeat_ms = now_ms();
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
  } catch (const std::exception& e) {
    std::cerr << "main_core: " << e.what() << '\n';
    return 1;
  }
  return 0;
}