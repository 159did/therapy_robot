#include "therapy_robot/collision.hpp"
#include "therapy_robot/control_safety_gate.hpp"
#include "therapy_robot/mf9025v2_driver.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cctype>
#include <cmath>
#include <csignal>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <thread>
#include <vector>

using namespace therapy_robot;

namespace {

volatile std::sig_atomic_t running = 1;
void on_signal(int) { running = 0; }

constexpr std::array<int, kAxisCount> kAxisGroup{{0, 1, 1, 2, 2}};
constexpr std::array<int, kAxisCount> kAxisSlot{{0, 0, 1, 0, 1}};
constexpr double kDegToRad = 3.14159265358979323846 / 180.0;

struct AxisRuntime {
  int direction = 1;
  int64_t offset_native = 0;
  uint32_t max_speed_native = 600;
  int communication_failures = 0;
  bool calibration_valid = false;
  bool brake_supported = false;
};

struct GroupRuntime {
  bool active = false;
  bool open = false;
  std::string port;
  std::array<uint8_t, kMaxMotorsPerGroup> motor_ids{{1, 2}};
  Mf9025v2Bus bus;
};

struct AxisMotionRecord {
  bool active = false;
  uint64_t command_seq = 0;
  int64_t start_native = 0;
  int64_t target_native = 0;
  int64_t last_native = 0;
  int64_t cumulative_abs_native = 0;
  uint64_t started_ms = 0;
  uint64_t last_checkpoint_ms = 0;
};

struct HardwareRuntime {
  std::array<GroupRuntime, kGroupCount> groups{};
  std::array<AxisRuntime, kAxisCount> axes{};
  int poll_ms = 50;
  int serial_timeout_ms = 80;
  int watchdog_ms = 1000;
  int status_every_polls = 20;
  int max_communication_failures = 3;
  std::array<int64_t, kAxisCount> limit_margin_native{{100, 100, 100, 100, 100}};
  double current_scale_a = 0.01;
  double max_current_a = 0.0;
  bool auto_zero_on_start = true;
  bool allow_zero_command = false;
  bool allow_outside_limits = false;
  bool clear_errors_on_enable = false;
  std::string offsets_file;
  std::string k0_position_file;
  bool k0_resume_valid = false;
  int64_t k0_resume_logical_native = 0;
  int64_t k0_last_persisted_native = std::numeric_limits<int64_t>::min();
  int brake_command_retries = 3;
  int brake_retry_gap_ms = 50;
  std::string motion_log_file;
  std::string motion_log_backup_file;
  std::string boot_session_id = "unknown";
  std::array<AxisMotionRecord, kAxisCount> motion{};
  // Hardware position commands are executed through a short, synchronized
  // trajectory.  The final target remains visible in MotorState while the
  // active target is advanced every polling cycle.
  bool trajectory_active = false;
  bool trajectory_recovery_path = false;
  uint64_t trajectory_started_ms = 0;
  uint64_t trajectory_duration_ms = 0;
  std::array<int64_t, kAxisCount> trajectory_start_native{};
  std::array<int64_t, kAxisCount> trajectory_target_native{};
  std::array<int64_t, kAxisCount> trajectory_last_command_native{};
  CollisionConfig collision_config{};
};

int axis_index(int group, int axis) {
  for (int i = 0; i < kAxisCount; ++i) {
    if (kAxisGroup[i] == group && kAxisSlot[i] == axis) return i;
  }
  return -1;
}

bool env_flag(const char* name, bool fallback = false) {
  const char* raw = std::getenv(name);
  if (!raw || !*raw) return fallback;
  std::string value(raw);
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (value == "1" || value == "true" || value == "yes" || value == "on") return true;
  if (value == "0" || value == "false" || value == "no" || value == "off") return false;
  return fallback;
}

int env_int(const char* name, int fallback, int minimum, int maximum) {
  const char* raw = std::getenv(name);
  if (!raw || !*raw) return fallback;
  char* end = nullptr;
  long value = std::strtol(raw, &end, 10);
  if (end == raw || *end != '\0') return fallback;
  return static_cast<int>(std::clamp<long>(value, minimum, maximum));
}

int64_t env_i64(const char* name, int64_t fallback, int64_t minimum,
                int64_t maximum) {
  const char* raw = std::getenv(name);
  if (!raw || !*raw) return fallback;
  char* end = nullptr;
  long long value = std::strtoll(raw, &end, 10);
  if (end == raw || *end != '\0') return fallback;
  return std::clamp<int64_t>(value, minimum, maximum);
}

double env_double(const char* name, double fallback, double minimum,
                  double maximum) {
  const char* raw = std::getenv(name);
  if (!raw || !*raw) return fallback;
  char* end = nullptr;
  double value = std::strtod(raw, &end);
  if (end == raw || *end != '\0' || !std::isfinite(value)) return fallback;
  return std::clamp(value, minimum, maximum);
}

std::string env_string(const char* name, const char* fallback) {
  const char* raw = std::getenv(name);
  return raw && *raw ? std::string(raw) : std::string(fallback);
}

bool load_i64_file(const std::string& path, int64_t& value) {
  if (path.empty()) return false;
  std::ifstream in(path);
  long long parsed = 0;
  if (!(in >> parsed)) return false;
  in >> std::ws;
  if (!in.eof()) return false;
  value = static_cast<int64_t>(parsed);
  return true;
}

bool persist_k0_position(HardwareRuntime& runtime, int64_t logical_native) {
  if (runtime.k0_position_file.empty()) return false;
  if (logical_native == runtime.k0_last_persisted_native) return true;
  const std::string temporary = runtime.k0_position_file + ".tmp";
  {
    std::ofstream out(temporary, std::ios::trunc);
    if (!out) return false;
    out << logical_native << '\n';
    out.flush();
    if (!out) return false;
  }
  if (std::rename(temporary.c_str(), runtime.k0_position_file.c_str()) != 0) {
    std::remove(temporary.c_str());
    return false;
  }
  runtime.k0_last_persisted_native = logical_native;
  runtime.k0_resume_valid = true;
  runtime.k0_resume_logical_native = logical_native;
  return true;
}

std::vector<int64_t> parse_integer_list(const std::string& text) {
  std::vector<int64_t> values;
  std::stringstream stream(text);
  std::string token;
  while (std::getline(stream, token, ',')) {
    if (token.empty()) continue;
    char* end = nullptr;
    long long value = std::strtoll(token.c_str(), &end, 10);
    if (end == token.c_str() || *end != '\0') {
      throw std::runtime_error("invalid integer list: " + text);
    }
    values.push_back(value);
  }
  return values;
}

std::vector<int64_t> load_required_axis_offsets_file(
    const std::string& path) {
  if (path.empty()) {
    throw std::runtime_error(
        "THERAPY_ROBOT_AXIS_OFFSETS_FILE must name a persistent offsets file");
  }

  struct stat file_status {};
  if (stat(path.c_str(), &file_status) != 0 ||
      !S_ISREG(file_status.st_mode)) {
    throw std::runtime_error(
        "required axis offsets file is missing or is not a regular file: " +
        path);
  }

  std::ifstream in(path, std::ios::binary);
  if (!in) {
    throw std::runtime_error(
        "required axis offsets file is unreadable: " + path);
  }
  const std::string content((std::istreambuf_iterator<char>(in)),
                            std::istreambuf_iterator<char>());
  if (in.bad()) {
    throw std::runtime_error(
        "required axis offsets file could not be read completely: " + path);
  }

  const auto is_space = [](unsigned char value) {
    return std::isspace(value) != 0;
  };
  std::size_t content_begin = 0;
  while (content_begin < content.size() &&
         is_space(static_cast<unsigned char>(content[content_begin]))) {
    ++content_begin;
  }
  std::size_t content_end = content.size();
  while (content_end > content_begin &&
         is_space(static_cast<unsigned char>(content[content_end - 1]))) {
    --content_end;
  }
  if (content_begin == content_end) {
    throw std::runtime_error("required axis offsets file is empty: " + path);
  }

  std::vector<int64_t> offsets;
  std::size_t token_begin = content_begin;
  while (token_begin <= content_end) {
    std::size_t token_end = content.find(',', token_begin);
    if (token_end == std::string::npos || token_end > content_end) {
      token_end = content_end;
    }

    std::size_t value_begin = token_begin;
    while (value_begin < token_end &&
           is_space(static_cast<unsigned char>(content[value_begin]))) {
      ++value_begin;
    }
    std::size_t value_end = token_end;
    while (value_end > value_begin &&
           is_space(static_cast<unsigned char>(content[value_end - 1]))) {
      --value_end;
    }
    if (value_begin == value_end) {
      throw std::runtime_error(
          "axis offsets file contains an empty value: " + path);
    }

    const std::string token =
        content.substr(value_begin, value_end - value_begin);
    errno = 0;
    char* parsed_end = nullptr;
    const long long parsed = std::strtoll(token.c_str(), &parsed_end, 10);
    if (errno == ERANGE || parsed_end == token.c_str() ||
        *parsed_end != '\0') {
      throw std::runtime_error(
          "axis offsets file contains an invalid integer: " + path);
    }
    offsets.push_back(static_cast<int64_t>(parsed));
    if (offsets.size() > kAxisCount) {
      throw std::runtime_error(
          "axis offsets file must contain exactly 5 integers: " + path);
    }

    if (token_end == content_end) break;
    token_begin = token_end + 1;
  }

  if (offsets.size() != kAxisCount) {
    throw std::runtime_error(
        "axis offsets file must contain exactly 5 integers: " + path);
  }
  return offsets;
}

bool group_is_active(int group, const std::string& active_groups) {
  std::string value = active_groups;
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  if (value == "all" || value == "*") return true;
  for (char& c : value) {
    if (c == ';' || c == ':' || c == ' ') c = ',';
  }
  std::stringstream stream(value);
  std::string token;
  while (std::getline(stream, token, ',')) {
    if (token == std::to_string(group)) return true;
  }
  return false;
}

bool axis_has_brake(int idx, const std::string& configured_axes) {
  std::string value = configured_axes;
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
  for (char& c : value) {
    if (c == ';' || c == ':' || c == ' ') c = ',';
  }
  std::stringstream stream(value);
  std::string token;
  while (std::getline(stream, token, ',')) {
    if (token == "K" + std::to_string(idx) || token == std::to_string(idx)) {
      return true;
    }
    if (idx == 0 && token == "G0-A0") return true;
    if (idx == 1 && token == "G1-A0") return true;
    if (idx == 2 && token == "G1-A1") return true;
    if (idx == 3 && token == "G2-A0") return true;
    if (idx == 4 && token == "G2-A1") return true;
  }
  return false;
}

long step_toward(long current, long target, long max_step) {
  if (current < target) return std::min(target, current + max_step);
  if (current > target) return std::max(target, current - max_step);
  return current;
}

double speed_multiplier() {
  const std::string runtime_dir =
      env_string("THERAPY_ROBOT_RUNTIME_DIR", "/tmp/therapy_robot");
  std::ifstream in(runtime_dir + "/speed_multiplier");
  double value = 0.65;
  if (in >> value && std::isfinite(value)) return std::clamp(value, 0.25, 1.0);
  return 0.65;
}

long max_step_for_axis(const SharedState& state, int idx, int poll_ms,
                       long legacy_max_step, double multiplier) {
  if (legacy_max_step > 0) {
    return std::max(1L, static_cast<long>(std::llround(legacy_max_step * multiplier)));
  }
  const double scale = std::abs(state.axis_map[idx].motor_native_to_gui_display);
  if (scale < 1e-12) return 1;
  const double base_speed_display_per_sec = idx == 0
      ? env_double("THERAPY_ROBOT_SIM_K0_SPEED_MM_S", 30.0, 0.01, 1000.0)
      : env_double("THERAPY_ROBOT_SIM_ROT_SPEED_DEG_S", 24.0, 0.01, 1000.0);
  const double step = base_speed_display_per_sec * multiplier * poll_ms / 1000.0 / scale;
  return std::max(1L, static_cast<long>(std::llround(step)));
}

double axis_si_from_native(const SharedState& state, int idx, int64_t native) {
  const double display = native * state.axis_map[idx].motor_native_to_gui_display;
  return idx == 0 ? display / 1000.0 : display * kDegToRad;
}

bool append_motion_line(const HardwareRuntime& runtime,
                        const std::string& line) {
  bool ok = true;
  for (const auto* path : {&runtime.motion_log_file,
                           &runtime.motion_log_backup_file}) {
    if (path->empty()) continue;
    std::ofstream out(*path, std::ios::app);
    if (!out) {
      ok = false;
      continue;
    }
    out << line << '\n';
    out.flush();
    if (!out) ok = false;
  }
  return ok;
}

bool write_motion_event(HardwareRuntime& runtime, const SharedState& state,
                        int idx, const char* event,
                        int64_t actual_native) {
  const auto& record = runtime.motion[idx];
  const auto& map = state.axis_map[idx];
  const double scale = map.motor_native_to_gui_display;
  std::ostringstream out;
  out << "{\"event\":\"" << event
      << "\",\"boot_session_id\":\"" << runtime.boot_session_id
      << "\",\"time_ms\":" << now_ms()
      << ",\"command_seq\":" << record.command_seq
      << ",\"axis\":\"K" << idx
      << "\",\"unit\":\"" << map.gui_display_unit
      << "\",\"start_native\":" << record.start_native
      << ",\"target_native\":" << record.target_native
      << ",\"actual_native\":" << actual_native
      << ",\"delta_native\":" << (actual_native - record.start_native)
      << ",\"cumulative_abs_native\":" << record.cumulative_abs_native
      << ",\"motor_turns_signed\":"
      << (actual_native - record.start_native) / 36000.0
      << ",\"motor_turns_travel\":"
      << record.cumulative_abs_native / 36000.0
      << ",\"start_display\":" << record.start_native * scale
      << ",\"target_display\":" << record.target_native * scale
      << ",\"actual_display\":" << actual_native * scale
      << ",\"delta_display\":"
      << (actual_native - record.start_native) * scale
      << ",\"elapsed_ms\":" << (now_ms() - record.started_ms)
      << '}';
  return append_motion_line(runtime, out.str());
}

void finish_motion_record(HardwareRuntime& runtime, SharedState& state,
                          int idx, const char* event) {
  auto& record = runtime.motion[idx];
  if (!record.active) return;
  const auto& motor =
      state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]];
  if (!write_motion_event(runtime, state, idx, event,
                          motor.actual_motor_native)) {
    set_text(state.groups[kAxisGroup[idx]].last_error,
             sizeof(state.groups[kAxisGroup[idx]].last_error),
             "motion log or backup write failed");
  }
  record.active = false;
}

void start_motion_record(HardwareRuntime& runtime, SharedState& state,
                         int idx, int64_t target_native) {
  finish_motion_record(runtime, state, idx, "superseded");
  const auto& motor =
      state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]];
  auto& record = runtime.motion[idx];
  record.active = true;
  record.command_seq = state.command.target_command_seq;
  record.start_native = motor.actual_motor_native;
  record.target_native = target_native;
  record.last_native = motor.actual_motor_native;
  record.cumulative_abs_native = 0;
  record.started_ms = now_ms();
  record.last_checkpoint_ms = record.started_ms;
  if (!write_motion_event(runtime, state, idx, "command_start",
                          motor.actual_motor_native)) {
    set_text(state.groups[kAxisGroup[idx]].last_error,
             sizeof(state.groups[kAxisGroup[idx]].last_error),
             "motion log or backup write failed");
  }
}

JointState joints_from_native(const SharedState& state,
                              const std::array<int64_t, kAxisCount>& native) {
  return {
      axis_si_from_native(state, 0, native[0]),
      axis_si_from_native(state, 1, native[1]),
      axis_si_from_native(state, 2, native[2]),
      axis_si_from_native(state, 3, native[3]),
      axis_si_from_native(state, 4, native[4]),
  };
}

JointState actual_joints(const SharedState& state) {
  std::array<int64_t, kAxisCount> native{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    native[idx] = state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]].actual_motor_native;
  }
  return joints_from_native(state, native);
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
           result.ok ? (result.checked ? "clear" : "disabled") :
           (rejected ? "rejected" : "collision_estop"));
  set_text(collision.link_name, sizeof(collision.link_name),
           result.link_name.c_str());
  set_text(collision.obstacle_name, sizeof(collision.obstacle_name),
           result.obstacle_name.c_str());
  set_text(collision.last_error, sizeof(collision.last_error),
           result.reason.c_str());
  if (rejected) collision.rejected_commands++;
}

CollisionConfig effective_collision_config(const SharedState& state,
                                           const CollisionConfig& base) {
  // Collision checking is never globally disabled by recovery state.  The
  // fixed recovery-home command below is the sole narrowly scoped exception.
  (void)state;
  return base;
}

int64_t clamped_target(SharedState& state, int idx, int64_t target,
                       int64_t hold_margin_native = 0) {
  const auto& map = state.axis_map[idx];
  const auto& motor =
      state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]];
  const bool holding_actual =
      target == motor.actual_motor_native &&
      target >= map.min_motor_native - hold_margin_native &&
      target <= map.max_motor_native + hold_margin_native;
  if (holding_actual) return target;
  const int64_t clamped = std::clamp(target, map.min_motor_native,
                                     map.max_motor_native);
  if (clamped != target) state.control.limit_alarm = 1;
  return clamped;
}

void set_group_error(SharedState& state, int group, const std::string& error) {
  set_text(state.groups[group].last_error,
           sizeof(state.groups[group].last_error), error.c_str());
}

void clear_group_error(SharedState& state, int group) {
  set_text(state.groups[group].last_error,
           sizeof(state.groups[group].last_error), "");
}

bool any_motor_enabled(const SharedState& state) {
  for (const auto& group : state.groups) {
    for (int slot = 0; slot < group.motor_count; ++slot) {
      if (group.motors[slot].enabled) return true;
    }
  }
  return false;
}

uint64_t heartbeat_age(uint64_t now, uint64_t heartbeat) {
  if (heartbeat == 0 || heartbeat > now) return std::numeric_limits<uint64_t>::max();
  return now - heartbeat;
}

void update_feedback(SharedState& state, HardwareRuntime& runtime, int idx,
                     int64_t physical_position,
                     const Mf9025v2Feedback* feedback = nullptr) {
  const int group = kAxisGroup[idx];
  const int slot = kAxisSlot[idx];
  auto& motor = state.groups[group].motors[slot];
  auto& axis = runtime.axes[idx];
  const int64_t logical = static_cast<int64_t>(axis.direction) *
                          (physical_position - axis.offset_native);
  motor.actual_motor_native = logical;
  motor.actual_axis_si = axis_si_from_native(state, idx, logical);
  motor.online = 1;
  axis.communication_failures = 0;
  if (feedback) {
    motor.actual_motor_native_velocity =
        static_cast<double>(axis.direction) * feedback->speed_native;
    motor.actual_current_a = feedback->current_native * runtime.current_scale_a;
    motor.fault = feedback->error_state != 0 ? feedback->error_state : 0;
  }
}

void note_failure(SharedState& state, HardwareRuntime& runtime, int idx,
                  const std::string& operation, const std::string& error) {
  const int group = kAxisGroup[idx];
  const int slot = kAxisSlot[idx];
  auto& axis = runtime.axes[idx];
  auto& motor = state.groups[group].motors[slot];
  axis.communication_failures++;
  if (axis.communication_failures >= runtime.max_communication_failures) {
    motor.online = 0;
    motor.fault = 1;
  }
  set_group_error(state, group, operation + " K" + std::to_string(idx) +
                                ": " + error);
}

void configure_runtime(SharedState& state, HardwareRuntime& runtime) {
  runtime.poll_ms = env_int("THERAPY_ROBOT_MOTOR_POLL_MS", 50, 10, 1000);
  runtime.serial_timeout_ms = env_int("THERAPY_ROBOT_SERIAL_TIMEOUT_MS", 80, 10, 2000);
  runtime.watchdog_ms = env_int("THERAPY_ROBOT_WATCHDOG_MS", 1000, 100, 10000);
  runtime.status_every_polls = env_int("THERAPY_ROBOT_STATUS_EVERY_POLLS", 20, 1, 1000);
  runtime.max_communication_failures =
      env_int("THERAPY_ROBOT_MAX_COMM_FAILURES", 3, 1, 100);
  const int64_t global_limit_margin =
      env_i64("THERAPY_ROBOT_LIMIT_MARGIN_NATIVE", 100, 0, 100000000);
  auto limit_margins = parse_integer_list(
      env_string("THERAPY_ROBOT_AXIS_LIMIT_MARGIN_NATIVE", ""));
  if (!limit_margins.empty() && limit_margins.size() != kAxisCount) {
    throw std::runtime_error(
        "THERAPY_ROBOT_AXIS_LIMIT_MARGIN_NATIVE must be empty or contain 5 values");
  }
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int64_t margin = limit_margins.empty()
        ? global_limit_margin : limit_margins[idx];
    if (margin < 0) {
      throw std::runtime_error("axis limit margins must be non-negative");
    }
    runtime.limit_margin_native[idx] = margin;
  }
  runtime.current_scale_a =
      env_double("THERAPY_ROBOT_CURRENT_SCALE_A", 0.01, 0.000001, 1000.0);
  runtime.max_current_a =
      env_double("THERAPY_ROBOT_MAX_CURRENT_A", 0.0, 0.0, 10000.0);
  runtime.auto_zero_on_start = env_flag("THERAPY_ROBOT_AUTO_ZERO_ON_START", true);
  runtime.allow_zero_command = env_flag("THERAPY_ROBOT_ALLOW_ZERO", false);
  runtime.allow_outside_limits = env_flag("THERAPY_ROBOT_ALLOW_OUTSIDE_LIMITS", false);
  runtime.clear_errors_on_enable = env_flag("THERAPY_ROBOT_CLEAR_ERRORS_ON_ENABLE", false);
  const char* configured_offsets_file =
      std::getenv("THERAPY_ROBOT_AXIS_OFFSETS_FILE");
  runtime.offsets_file = configured_offsets_file
      ? std::string(configured_offsets_file)
      : "/home/jetsonorin/Documents/therapy_robot/config/axis-offsets-native.txt";
  runtime.k0_position_file = env_string(
      "THERAPY_ROBOT_K0_POSITION_FILE",
      "/home/jetsonorin/Documents/therapy_robot/config/k0-last-logical-native.txt");
  runtime.motion_log_file = env_string(
      "THERAPY_ROBOT_MOTION_LOG_FILE",
      "/home/jetsonorin/Documents/therapy_robot/data/motor-motion-history.jsonl");
  runtime.motion_log_backup_file = env_string(
      "THERAPY_ROBOT_MOTION_LOG_BACKUP_FILE",
      "/home/jetsonorin/Documents/therapy_robot/data/backup/motor-motion-history.backup.jsonl");
  {
    std::ifstream boot_id("/proc/sys/kernel/random/boot_id");
    std::string value;
    if (boot_id >> value && !value.empty()) runtime.boot_session_id = value;
  }
  int64_t saved_k0 = 0;
  const bool k0_position_loaded =
      load_i64_file(runtime.k0_position_file, saved_k0);
  if (k0_position_loaded) {
    const auto& map = state.axis_map[0];
    const int64_t margin = runtime.limit_margin_native[0];
    if (saved_k0 >= map.min_motor_native - margin &&
        saved_k0 <= map.max_motor_native + margin) {
      runtime.k0_resume_valid = true;
      runtime.k0_resume_logical_native = saved_k0;
      runtime.k0_last_persisted_native = saved_k0;
    } else {
      throw std::runtime_error(
          "persisted K0 logical position is outside configured limits");
    }
  } else if (env_flag("THERAPY_ROBOT_REQUIRE_K0_POSITION_FILE", false)) {
    throw std::runtime_error(
        "required K0 logical position file is missing or invalid");
  }
  runtime.brake_command_retries =
      env_int("THERAPY_ROBOT_BRAKE_COMMAND_RETRIES", 3, 1, 10);
  runtime.brake_retry_gap_ms =
      env_int("THERAPY_ROBOT_BRAKE_RETRY_GAP_MS", 50, 0, 1000);
  runtime.collision_config = collision_config_from_environment();
  publish_collision_config(state, runtime.collision_config);

  const std::string active_groups =
      env_string("THERAPY_ROBOT_ACTIVE_GROUPS", "all");
  const char* port_names[kGroupCount] = {
      "THERAPY_ROBOT_G0_PORT", "THERAPY_ROBOT_G1_PORT", "THERAPY_ROBOT_G2_PORT"};
  const char* default_ports[kGroupCount] = {
      "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2"};
  const char* id_names[kGroupCount] = {
      "THERAPY_ROBOT_G0_MOTOR_IDS", "THERAPY_ROBOT_G1_MOTOR_IDS",
      "THERAPY_ROBOT_G2_MOTOR_IDS"};

  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    config.active = group_is_active(group, active_groups);
    config.port = env_string(port_names[group], default_ports[group]);
    auto ids = parse_integer_list(env_string(id_names[group], group == 0 ? "1" : "1,2"));
    const int required = state.groups[group].motor_count;
    if (static_cast<int>(ids.size()) != required) {
      throw std::runtime_error(std::string(id_names[group]) +
                               " must contain " + std::to_string(required) +
                               " motor IDs");
    }
    for (int slot = 0; slot < required; ++slot) {
      if (ids[slot] < 1 || ids[slot] > 255) {
        throw std::runtime_error(std::string(id_names[group]) +
                                 " contains an ID outside 1..255");
      }
      config.motor_ids[slot] = static_cast<uint8_t>(ids[slot]);
      state.groups[group].motors[slot].motor_id = ids[slot];
      state.groups[group].motors[slot].online = 0;
      state.groups[group].motors[slot].enabled = 0;
    }
    set_text(state.groups[group].port, sizeof(state.groups[group].port),
             config.port.c_str());
    state.groups[group].hardware_enabled = 0;
  }

  auto directions = parse_integer_list(
      env_string("THERAPY_ROBOT_AXIS_DIRECTIONS", "1,1,1,1,1"));
  if (directions.size() != kAxisCount) {
    throw std::runtime_error("THERAPY_ROBOT_AXIS_DIRECTIONS must contain 5 values");
  }
  for (int idx = 0; idx < kAxisCount; ++idx) {
    if (directions[idx] != -1 && directions[idx] != 1) {
      throw std::runtime_error("axis directions must be either -1 or 1");
    }
    runtime.axes[idx].direction = static_cast<int>(directions[idx]);
  }
  const std::string brake_axes =
      env_string("THERAPY_ROBOT_BRAKE_AXES", "K0");
  for (int idx = 0; idx < kAxisCount; ++idx) {
    runtime.axes[idx].brake_supported = axis_has_brake(idx, brake_axes);
    auto& motor = state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]];
    motor.brake_supported = runtime.axes[idx].brake_supported ? 1 : 0;
    motor.brake_engaged = 0;
    motor.brake_release_requested = 0;
    motor.brake_state_known = runtime.axes[idx].brake_supported ? 0 : 1;
    set_text(motor.brake_last_error, sizeof(motor.brake_last_error), "");
  }

  const char* configured_offsets_setting =
      std::getenv("THERAPY_ROBOT_AXIS_OFFSETS_NATIVE");
  const std::string offsets_setting = configured_offsets_setting
      ? std::string(configured_offsets_setting)
      : "auto";
  if (offsets_setting != "auto") {
    throw std::runtime_error(
        "THERAPY_ROBOT_AXIS_OFFSETS_NATIVE must be 'auto'; inline hardware "
        "offsets are forbidden");
  }
  const auto offsets = load_required_axis_offsets_file(runtime.offsets_file);
  runtime.auto_zero_on_start = false;
  for (int idx = 0; idx < kAxisCount; ++idx) {
    runtime.axes[idx].offset_native = offsets[idx];
    runtime.axes[idx].calibration_valid = true;
  }

  const uint32_t global_speed = static_cast<uint32_t>(
      env_i64("THERAPY_ROBOT_MAX_SPEED_NATIVE", 600, 1,
              std::numeric_limits<uint32_t>::max()));
  auto speeds = parse_integer_list(env_string(
      "THERAPY_ROBOT_AXIS_MAX_SPEED_NATIVE", ""));
  if (!speeds.empty() && speeds.size() != kAxisCount) {
    throw std::runtime_error("THERAPY_ROBOT_AXIS_MAX_SPEED_NATIVE must be empty or contain 5 values");
  }
  for (int idx = 0; idx < kAxisCount; ++idx) {
    int64_t speed = speeds.empty() ? global_speed : speeds[idx];
    runtime.axes[idx].max_speed_native = static_cast<uint32_t>(
        std::clamp<int64_t>(speed, 1, std::numeric_limits<uint32_t>::max()));
  }
}

bool initialize_hardware(SharedState& state, HardwareRuntime& runtime) {
  configure_runtime(state, runtime);
  set_text(state.run_mode, sizeof(state.run_mode),
           runtime.auto_zero_on_start ? "hardware_relative" : "hardware");
  set_text(state.system_state, sizeof(state.system_state), "hardware_init");
  state.simulation.hardware_mode = 1;
  state.simulation.enabled = 1;  // visualization remains active from real feedback
  state.control.limit_alarm = 0;

  bool any_online = false;
  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    auto& group_state = state.groups[group];
    if (!config.active) {
      set_group_error(state, group, "inactive by THERAPY_ROBOT_ACTIVE_GROUPS");
      continue;
    }

    std::string error;
    config.open = config.bus.open_port(config.port, runtime.serial_timeout_ms, error);
    if (!config.open) {
      set_group_error(state, group, error);
      continue;
    }
    clear_group_error(state, group);

    for (int slot = 0; slot < group_state.motor_count; ++slot) {
      const int idx = axis_index(group, slot);
      auto& motor = group_state.motors[slot];
      int64_t physical_position = 0;
      if (!config.bus.read_position(config.motor_ids[slot], physical_position, error)) {
        note_failure(state, runtime, idx, "startup position", error);
        continue;
      }
      auto& axis = runtime.axes[idx];
      if (runtime.auto_zero_on_start && !axis.calibration_valid) {
        axis.offset_native = physical_position;
        axis.calibration_valid = true;
      }
      // K0 has a normally-engaged brake and cannot be repositioned by hand.
      // Its controller loses whole motor turns after 0x80 motor-off, so rebuild
      // the session offset from the last brake-protected logical height.
      if (idx == 0 && axis.brake_supported && runtime.k0_resume_valid) {
        axis.offset_native = physical_position -
            static_cast<int64_t>(axis.direction) *
                runtime.k0_resume_logical_native;
        axis.calibration_valid = true;
      }
      update_feedback(state, runtime, idx, physical_position);
      if (axis.brake_supported) {
        bool engaged = false;
        if (!config.bus.read_brake(config.motor_ids[slot], engaged, error)) {
          motor.brake_state_known = 0;
          motor.fault = 1;
          set_text(motor.brake_last_error, sizeof(motor.brake_last_error),
                   error.c_str());
          set_group_error(state, group,
                          "startup brake K" + std::to_string(idx) + ": " + error);
          continue;
        }
        motor.brake_state_known = 1;
        motor.brake_engaged = engaged ? 1 : 0;
      }
      state.command.target_native[idx] = motor.actual_motor_native;
      motor.target_motor_native = motor.actual_motor_native;
      motor.active_target_motor_native = motor.actual_motor_native;
      motor.target_axis_si = motor.actual_axis_si;

      const auto& map = state.axis_map[idx];
      if (!runtime.allow_outside_limits &&
          (motor.actual_motor_native < map.min_motor_native - runtime.limit_margin_native[idx] ||
           motor.actual_motor_native > map.max_motor_native + runtime.limit_margin_native[idx])) {
        motor.fault = 1;
        set_group_error(state, group,
                        "K" + std::to_string(idx) +
                        " actual position is outside configured soft limits");
        continue;
      }
      any_online = true;
    }
  }

  state.command.target_command_seq++;
  set_text(state.system_state, sizeof(state.system_state),
           any_online ? "hardware_ready" : "hardware_fault");
  return any_online;
}

bool command_brake(SharedState& state, HardwareRuntime& runtime, int idx,
                   bool engage, const char* operation) {
  const int group = kAxisGroup[idx];
  const int slot = kAxisSlot[idx];
  auto& config = runtime.groups[group];
  auto& motor = state.groups[group].motors[slot];
  if (!runtime.axes[idx].brake_supported) return true;
  motor.brake_release_requested = engage ? 0 : 1;
  std::string error;
  for (int attempt = 1; attempt <= runtime.brake_command_retries; ++attempt) {
    bool engaged = motor.brake_engaged != 0;
    const bool ok = engage
        ? config.bus.engage_brake(config.motor_ids[slot], engaged, error)
        : config.bus.release_brake(config.motor_ids[slot], engaged, error);
    if (ok) {
      motor.brake_state_known = 1;
      motor.brake_engaged = engaged ? 1 : 0;
      set_text(motor.brake_last_error, sizeof(motor.brake_last_error), "");
      return true;
    }
    if (attempt < runtime.brake_command_retries &&
        runtime.brake_retry_gap_ms > 0) {
      std::this_thread::sleep_for(
          std::chrono::milliseconds(runtime.brake_retry_gap_ms));
    }
  }
  motor.brake_state_known = 0;
  motor.fault = 1;
  set_text(motor.brake_last_error, sizeof(motor.brake_last_error),
           error.c_str());
  set_group_error(state, group, std::string(operation) + " K" +
                                   std::to_string(idx) + ": " + error);
  return false;
}

void stop_all(SharedState& state, HardwareRuntime& runtime, bool disable,
              const char* reason) {
  // Stop and estop invalidate any pending interpolated trajectory.  This is
  // cleared before touching the buses so the next enable cannot resume an old
  // target accidentally.
  runtime.trajectory_active = false;
  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    auto& group_state = state.groups[group];
    if (!config.active || !config.open) continue;
    for (int slot = 0; slot < group_state.motor_count; ++slot) {
      auto& motor = group_state.motors[slot];
      if (!motor.online && !motor.enabled) continue;
      std::string error;
      const int idx = axis_index(group, slot);
      const int64_t held_logical_native = motor.actual_motor_native;
      finish_motion_record(runtime, state, idx, "stopped");
      if (idx == 0 && runtime.axes[idx].brake_supported &&
          !persist_k0_position(runtime, held_logical_native)) {
        motor.fault = 1;
        set_group_error(state, group, "persist K0 position before stop failed");
      }
      if (!config.bus.stop(config.motor_ids[slot], error)) {
        note_failure(state, runtime, idx, "stop", error);
      }
      const bool brake_safe = command_brake(state, runtime, idx, true,
                                            "engage brake");
      if (disable && brake_safe &&
          !config.bus.motor_off(config.motor_ids[slot], error)) {
        note_failure(state, runtime, idx, "motor off", error);
      }
      if (disable && brake_safe) motor.enabled = 0;
      if (disable && brake_safe && idx == 0) {
        int64_t reset_position = 0;
        if (config.bus.read_position(config.motor_ids[slot], reset_position,
                                     error)) {
          auto& axis = runtime.axes[idx];
          axis.offset_native = reset_position -
              static_cast<int64_t>(axis.direction) * held_logical_native;
          update_feedback(state, runtime, idx, reset_position);
          runtime.k0_resume_valid = true;
          runtime.k0_resume_logical_native = held_logical_native;
        } else {
          note_failure(state, runtime, idx,
                       "rebase K0 after motor off", error);
        }
      }
      motor.mode = 0;
    }
    if (disable) {
      bool any_still_enabled = false;
      for (int slot = 0; slot < group_state.motor_count; ++slot) {
        any_still_enabled = any_still_enabled ||
                            group_state.motors[slot].enabled != 0;
      }
      group_state.hardware_enabled = any_still_enabled ? 1 : 0;
    }
  }
  set_text(state.system_state, sizeof(state.system_state), reason);
}

void synchronize_targets_to_actual(SharedState& state) {
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& motor = state.groups[group].motors[slot];
    state.command.target_native[idx] = motor.actual_motor_native;
    motor.target_motor_native = motor.actual_motor_native;
    motor.active_target_motor_native = motor.actual_motor_native;
    motor.target_axis_si = motor.actual_axis_si;
  }
  state.command.target_command_seq++;
}

bool refresh_feedback_before_enable(SharedState& state,
                                    HardwareRuntime& runtime) {
  bool all_fresh = true;
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& config = runtime.groups[group];
    auto& motor = state.groups[group].motors[slot];
    if (!config.active) continue;
    if (!config.open) {
      all_fresh = false;
      continue;
    }
    std::string error;
    int64_t physical_position = 0;
    if (!config.bus.read_position(config.motor_ids[slot], physical_position,
                                  error)) {
      note_failure(state, runtime, idx, "pre-enable position", error);
      all_fresh = false;
      continue;
    }
    if (idx == 0 && runtime.axes[idx].brake_supported &&
        runtime.k0_resume_valid && !motor.enabled) {
      auto& axis = runtime.axes[idx];
      axis.offset_native = physical_position -
          static_cast<int64_t>(axis.direction) *
              runtime.k0_resume_logical_native;
    }
    update_feedback(state, runtime, idx, physical_position);
    if (runtime.axes[idx].brake_supported) {
      bool engaged = false;
      if (!config.bus.read_brake(config.motor_ids[slot], engaged, error)) {
        motor.brake_state_known = 0;
        set_text(motor.brake_last_error, sizeof(motor.brake_last_error),
                 error.c_str());
        set_group_error(state, group, "pre-enable brake K" +
                                         std::to_string(idx) + ": " + error);
        all_fresh = false;
        continue;
      }
      motor.brake_state_known = 1;
      motor.brake_engaged = engaged ? 1 : 0;
      set_text(motor.brake_last_error, sizeof(motor.brake_last_error), "");
    }
  }
  return all_fresh;
}

void enable_all(SharedState& state, HardwareRuntime& runtime) {
  if (state.emergency_stop) {
    set_text(state.system_state, sizeof(state.system_state), "estop_latched");
    return;
  }
  if (!refresh_feedback_before_enable(state, runtime)) {
    set_text(state.system_state, sizeof(state.system_state),
             "enable_feedback_failed");
    return;
  }
  synchronize_targets_to_actual(state);
  set_text(state.system_state, sizeof(state.system_state), "enabling");

  bool any_enabled = false;
  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    auto& group_state = state.groups[group];
    if (!config.active || !config.open) continue;
    bool all_enabled = true;
    for (int slot = 0; slot < group_state.motor_count; ++slot) {
      const int idx = axis_index(group, slot);
      auto& motor = group_state.motors[slot];
      auto& axis = runtime.axes[idx];
      if (!motor.online || !axis.calibration_valid || motor.fault) {
        all_enabled = false;
        continue;
      }
      std::string error;
      if (runtime.clear_errors_on_enable) {
        Mf9025v2Feedback feedback;
        if (!config.bus.clear_error(config.motor_ids[slot], feedback, error)) {
          note_failure(state, runtime, idx, "clear error", error);
          all_enabled = false;
          continue;
        }
        motor.fault = feedback.error_state;
      }
      // K0 is a gravity axis.  Its brake must stay engaged until the drive's
      // internal position target has been overwritten with the freshly read
      // physical position.  Otherwise motor_on can resume a stale target from
      // the previous command and the axis can move as soon as the brake opens.
      if (axis.brake_supported &&
          !command_brake(state, runtime, idx, true,
                         "engage brake before enable hold")) {
        all_enabled = false;
        continue;
      }
      if (!config.bus.motor_on(config.motor_ids[slot], error)) {
        note_failure(state, runtime, idx, "motor on", error);
        all_enabled = false;
        continue;
      }
      if (axis.brake_supported) {
        const int64_t hold_logical = motor.actual_motor_native;
        int64_t hold_physical = 0;
        if (!config.bus.read_position(config.motor_ids[slot], hold_physical,
                                      error)) {
          note_failure(state, runtime, idx,
                       "post-enable hold position read", error);
          std::string stop_error;
          config.bus.stop(config.motor_ids[slot], stop_error);
          command_brake(state, runtime, idx, true,
                        "engage brake after hold read failure");
          config.bus.motor_off(config.motor_ids[slot], stop_error);
          all_enabled = false;
          continue;
        }
        // motor_on can change the drive's 0x92 multi-turn coordinate without
        // any mechanical motion.  Rebase to the post-on reading while the
        // brake is still engaged, preserving the same logical K0 position.
        axis.offset_native = hold_physical -
            static_cast<int64_t>(axis.direction) * hold_logical;
        update_feedback(state, runtime, idx, hold_physical);
        Mf9025v2Feedback hold_feedback;
        if (!config.bus.set_position(config.motor_ids[slot], hold_physical,
                                     axis.max_speed_native, hold_feedback,
                                     error)) {
          note_failure(state, runtime, idx, "pre-release hold position", error);
          std::string stop_error;
          config.bus.stop(config.motor_ids[slot], stop_error);
          command_brake(state, runtime, idx, true,
                        "engage brake after hold failure");
          config.bus.motor_off(config.motor_ids[slot], stop_error);
          all_enabled = false;
          continue;
        }
        motor.target_motor_native = hold_logical;
        motor.active_target_motor_native = hold_logical;
        motor.target_axis_si = motor.actual_axis_si;
      }
      if (!command_brake(state, runtime, idx, false, "release brake")) {
        std::string stop_error;
        config.bus.stop(config.motor_ids[slot], stop_error);
        config.bus.motor_off(config.motor_ids[slot], stop_error);
        all_enabled = false;
        continue;
      }
      motor.enabled = 1;
      motor.mode = 1;
      any_enabled = true;
    }
    group_state.hardware_enabled = all_enabled ? 1 : 0;
  }
  set_text(state.system_state, sizeof(state.system_state),
           any_enabled ? "enabled" : "enable_failed");
}

void send_targets(SharedState& state, HardwareRuntime& runtime,
                  bool recovery_home_path = false);

void recover_arm_zero(SharedState& state, HardwareRuntime& runtime) {
  state.control.collision.manual_recovery = 1;
  state.control.collision.recovery_arm_zero_active = 1;
  state.emergency_stop = 0;
  state.control.limit_alarm = 0;
  if (!any_motor_enabled(state)) enable_all(state, runtime);
  if (!any_motor_enabled(state)) return;
  synchronize_targets_to_actual(state);
  for (int idx = 1; idx < kAxisCount; ++idx) state.command.target_native[idx] = 0;
  state.command.target_command_seq++;
  // A robot already inside a collision boundary needs this one known,
  // storage-directed trajectory to escape.  No user-selected targets use it.
  send_targets(state, runtime, true);
  set_text(state.system_state, sizeof(state.system_state), "recovery_arm_zero");
}

void zero_all_ram(SharedState& state, HardwareRuntime& runtime) {
  if (!runtime.allow_zero_command) {
    set_text(state.system_state, sizeof(state.system_state), "zero_blocked");
    for (int group = 0; group < kGroupCount; ++group) {
      set_group_error(state, group,
                      "software zero capture blocked; set THERAPY_ROBOT_ALLOW_ZERO=1 explicitly");
    }
    return;
  }
  if (any_motor_enabled(state)) {
    set_text(state.system_state, sizeof(state.system_state), "zero_requires_disabled");
    return;
  }
  std::array<int64_t, kAxisCount> physical_positions{};
  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    auto& group_state = state.groups[group];
    if (!config.active || !config.open) {
      set_text(state.system_state, sizeof(state.system_state),
               "software_zero_requires_all_axes_online");
      return;
    }
    for (int slot = 0; slot < group_state.motor_count; ++slot) {
      const int idx = axis_index(group, slot);
      auto& motor = group_state.motors[slot];
      if (!motor.online) {
        set_text(state.system_state, sizeof(state.system_state),
                 "software_zero_requires_all_axes_online");
        return;
      }
      std::string error;
      if (!config.bus.read_position(config.motor_ids[slot],
                                    physical_positions[idx], error)) {
        note_failure(state, runtime, idx, "capture software zero", error);
        set_text(state.system_state, sizeof(state.system_state),
                 "software_zero_read_failed");
        return;
      }
    }
  }

  if (runtime.offsets_file.empty()) {
    set_text(state.system_state, sizeof(state.system_state),
             "software_zero_file_not_configured");
    return;
  }
  const std::string temporary = runtime.offsets_file + ".tmp";
  {
    std::ofstream out(temporary, std::ios::trunc);
    if (!out) {
      set_text(state.system_state, sizeof(state.system_state),
               "software_zero_write_failed");
      return;
    }
    for (int idx = 0; idx < kAxisCount; ++idx) {
      if (idx) out << ',';
      out << physical_positions[idx];
    }
    out << '\n';
    out.flush();
    if (!out) {
      set_text(state.system_state, sizeof(state.system_state),
               "software_zero_write_failed");
      return;
    }
  }
  if (std::rename(temporary.c_str(), runtime.offsets_file.c_str()) != 0) {
    std::remove(temporary.c_str());
    set_text(state.system_state, sizeof(state.system_state),
             "software_zero_write_failed");
    return;
  }

  for (int idx = 0; idx < kAxisCount; ++idx) {
    runtime.axes[idx].offset_native = physical_positions[idx];
    runtime.axes[idx].calibration_valid = true;
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& motor = state.groups[group].motors[slot];
    update_feedback(state, runtime, idx, physical_positions[idx]);
    motor.target_motor_native = 0;
    motor.active_target_motor_native = 0;
    motor.target_axis_si = 0.0;
    state.command.target_native[idx] = 0;
  }
  persist_k0_position(runtime, 0);
  state.command.target_command_seq++;
  runtime.auto_zero_on_start = false;
  set_text(state.run_mode, sizeof(state.run_mode), "hardware");
  set_text(state.system_state, sizeof(state.system_state),
           "software_zero_complete");
}

// Reconcile the software coordinate frame with a physically confirmed pose.
// This is deliberately software-only: every drive must be disabled and no
// position, enable, brake, or stop command is sent to the motor bus.
void reconcile_confirmed_pose(SharedState& state, HardwareRuntime& runtime) {
  if (any_motor_enabled(state)) {
    set_text(state.system_state, sizeof(state.system_state),
             "pose_reconcile_requires_disabled");
    return;
  }
  std::array<int64_t, kAxisCount> physical{};
  for (int group = 0; group < kGroupCount; ++group) {
    auto& config = runtime.groups[group];
    auto& group_state = state.groups[group];
    if (!config.active || !config.open) {
      set_text(state.system_state, sizeof(state.system_state),
               "pose_reconcile_requires_all_axes_online");
      return;
    }
    for (int slot = 0; slot < group_state.motor_count; ++slot) {
      const int idx = axis_index(group, slot);
      if (idx < 0 || !group_state.motors[slot].online) {
        set_text(state.system_state, sizeof(state.system_state),
                 "pose_reconcile_requires_all_axes_online");
        return;
      }
      std::string error;
      if (!config.bus.read_position(config.motor_ids[slot], physical[idx], error)) {
        note_failure(state, runtime, idx, "reconcile pose", error);
        set_text(state.system_state, sizeof(state.system_state),
                 "pose_reconcile_read_failed");
        return;
      }
    }
  }
  if (runtime.offsets_file.empty()) {
    set_text(state.system_state, sizeof(state.system_state),
             "pose_reconcile_file_not_configured");
    return;
  }
  std::array<int64_t, kAxisCount> offsets{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const auto& axis_map = state.axis_map[idx];
    const int64_t desired = state.command.target_native[idx];
    if (desired < axis_map.min_motor_native || desired > axis_map.max_motor_native) {
      set_text(state.system_state, sizeof(state.system_state),
               "pose_reconcile_value_outside_limits");
      return;
    }
    offsets[idx] = physical[idx] - static_cast<int64_t>(runtime.axes[idx].direction) * desired;
  }
  const std::string temporary = runtime.offsets_file + ".tmp";
  {
    std::ofstream out(temporary, std::ios::trunc);
    if (!out) {
      set_text(state.system_state, sizeof(state.system_state), "pose_reconcile_write_failed");
      return;
    }
    for (int idx = 0; idx < kAxisCount; ++idx) {
      if (idx) out << ',';
      out << offsets[idx];
    }
    out << '\n';
    out.flush();
    if (!out || std::rename(temporary.c_str(), runtime.offsets_file.c_str()) != 0) {
      std::remove(temporary.c_str());
      set_text(state.system_state, sizeof(state.system_state), "pose_reconcile_write_failed");
      return;
    }
  }
  for (int idx = 0; idx < kAxisCount; ++idx) {
    runtime.axes[idx].offset_native = offsets[idx];
    runtime.axes[idx].calibration_valid = true;
    update_feedback(state, runtime, idx, physical[idx]);
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& motor = state.groups[group].motors[slot];
    motor.target_motor_native = state.command.target_native[idx];
    motor.active_target_motor_native = state.command.target_native[idx];
    motor.target_axis_si = axis_si_from_native(state, idx, state.command.target_native[idx]);
  }
  persist_k0_position(runtime, state.command.target_native[0]);
  state.command.target_command_seq++;
  state.emergency_stop = 0;
  state.control.limit_alarm = 0;
  state.control.collision.alarm = 0;
  state.control.collision.manual_recovery = 0;
  state.control.collision.recovery_arm_zero_active = 0;
  set_text(state.run_mode, sizeof(state.run_mode), "hardware");
  set_text(state.system_state, sizeof(state.system_state), "pose_reconciled");
}

void send_trajectory_point(SharedState& state, HardwareRuntime& runtime,
                           const std::array<int64_t, kAxisCount>& point) {
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& config = runtime.groups[group];
    auto& motor = state.groups[group].motors[slot];
    auto& axis = runtime.axes[idx];
    if (!config.active || !config.open || !motor.online || !motor.enabled ||
        motor.fault || !axis.calibration_valid) {
      continue;
    }

    const bool resuming = motor.mode != 1;
    if (resuming && !command_brake(state, runtime, idx, false,
                                   "release brake")) {
      continue;
    }
    if (resuming) motor.mode = 1;

    // The K0 drive already performs continuous position control for a final
    // target.  Streaming cubic-smoothstep waypoints made its small starting
    // increments arrive only after the serial polling cycle, so the lift
    // repeatedly reached a waypoint and paused before the next one.  Send K0
    // its final target once; keep software interpolation for K1-K4.
    const int64_t logical_point = idx == 0 && runtime.trajectory_active
        ? runtime.trajectory_target_native[idx]
        : point[idx];
    if (!resuming && logical_point == motor.active_target_motor_native) {
      continue;
    }
    const int64_t physical_point = axis.offset_native +
        static_cast<int64_t>(axis.direction) * logical_point;
    const uint32_t command_speed = static_cast<uint32_t>(std::clamp<double>(
        std::ceil(axis.max_speed_native * speed_multiplier()), 1.0,
        std::numeric_limits<uint32_t>::max()));
    Mf9025v2Feedback feedback;
    std::string error;
    if (!config.bus.set_position(config.motor_ids[slot], physical_point,
                                 command_speed, feedback, error)) {
      note_failure(state, runtime, idx, "set trajectory point", error);
      if (!motor.online) {
        std::string stop_error;
        config.bus.stop(config.motor_ids[slot], stop_error);
        config.bus.motor_off(config.motor_ids[slot], stop_error);
        motor.enabled = 0;
      }
      continue;
    }
    motor.active_target_motor_native = logical_point;
    motor.actual_motor_native_velocity =
        static_cast<double>(axis.direction) * feedback.speed_native;
    motor.actual_current_a = feedback.current_native * runtime.current_scale_a;
  }
}

void send_targets(SharedState& state, HardwareRuntime& runtime,
                  bool recovery_home_path) {
  state.control.limit_alarm = 0;
  // Recovery point-jogging is an explicit, single-axis escape path requested
  // by the web UI after the operator has disabled all motors and entered the
  // recovery mode.  It may bypass the current collision path only under that
  // latched recovery state; normal targets never inherit this bypass.
  const bool recovery_jog_path = state.control.collision.manual_recovery &&
                                 state.command.target_command_id == 7;
  const bool continuous_jog_path = state.command.target_command_id == 3;
  std::array<int64_t, kAxisCount> logical_targets{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    logical_targets[idx] = clamped_target(
        state, idx, state.command.target_native[idx],
        runtime.limit_margin_native[idx]);
    state.command.target_native[idx] = logical_targets[idx];
  }

  const int64_t current_k0 = state.groups[kAxisGroup[0]].motors[kAxisSlot[0]].actual_motor_native;
  if (state.control.collision.manual_recovery && logical_targets[0] < current_k0) {
    state.control.limit_alarm = 1;
    set_text(state.system_state, sizeof(state.system_state),
             "recovery_k0_down_blocked");
    synchronize_targets_to_actual(state);
    return;
  }

  if (!recovery_home_path && !recovery_jog_path) {
    const auto current_joints = actual_joints(state);
    const auto target_joints = joints_from_native(state, logical_targets);
    const auto config = effective_collision_config(state, runtime.collision_config);
    const auto collision = state.command.target_command_id == 2
        ? check_endpoint_motion(current_joints, target_joints, config)
        : check_robot_motion(current_joints, target_joints, config);
    publish_collision_result(state, collision, !collision.ok);
    if (!collision.ok) {
      state.control.limit_alarm = 1;
      stop_all(state, runtime, false, "collision_rejected");
      synchronize_targets_to_actual(state);
      return;
    }
  }

  const auto current_native = [&]() {
    std::array<int64_t, kAxisCount> values{};
    for (int idx = 0; idx < kAxisCount; ++idx) {
      values[idx] = state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]].actual_motor_native;
    }
    return values;
  }();

  uint64_t duration_ms = 200;
  bool has_motion = false;
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int64_t delta = logical_targets[idx] - current_native[idx];
    if (delta == 0) continue;
    has_motion = true;
    const double effective_speed =
        std::max(1.0, runtime.axes[idx].max_speed_native * speed_multiplier());
    const double seconds = static_cast<double>(std::llabs(delta)) /
                           effective_speed;
    // Cubic smoothstep peaks at 1.5x its average speed.  Reserve that
    // headroom so the generated path never asks a motor to exceed its limit.
    duration_ms = std::max<uint64_t>(
        duration_ms, static_cast<uint64_t>(std::ceil(seconds * 1500.0)));
  }
  runtime.trajectory_active = has_motion;
  runtime.trajectory_recovery_path = recovery_home_path || recovery_jog_path;
  runtime.trajectory_started_ms = now_ms();
  runtime.trajectory_duration_ms = duration_ms;
  runtime.trajectory_start_native = current_native;
  runtime.trajectory_target_native = logical_targets;

  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& motor = state.groups[group].motors[slot];
    motor.target_motor_native = logical_targets[idx];
    motor.target_axis_si = axis_si_from_native(state, idx, logical_targets[idx]);
    if (has_motion && motor.online && motor.enabled &&
        runtime.axes[idx].calibration_valid) {
      start_motion_record(runtime, state, idx, logical_targets[idx]);
    }
  }

  if (!has_motion) {
    runtime.trajectory_active = false;
    return;
  }

  if (continuous_jog_path) {
    // The drive owns the constant-speed move and stops at the already checked
    // soft-limit target.  Streaming cubic waypoints here turns a continuous
    // jog into a very long ease-in/ease-out trajectory and delays stop-at-limit
    // behavior by the software trajectory duration.
    runtime.trajectory_active = false;
    runtime.trajectory_last_command_native = logical_targets;
    send_trajectory_point(state, runtime, logical_targets);
    return;
  }

  runtime.trajectory_last_command_native = current_native;
  send_trajectory_point(state, runtime, current_native);
}

void advance_trajectory(SharedState& state, HardwareRuntime& runtime) {
  if (!runtime.trajectory_active || state.emergency_stop) return;
  const uint64_t elapsed = now_ms() - runtime.trajectory_started_ms;
  const double u = runtime.trajectory_duration_ms == 0
      ? 1.0
      : std::min(1.0, static_cast<double>(elapsed) /
                            runtime.trajectory_duration_ms);
  // Cubic smoothstep gives zero velocity at the start and end while keeping
  // the trajectory monotonic for every joint.
  const double smooth = u * u * (3.0 - 2.0 * u);
  std::array<int64_t, kAxisCount> point{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const double start = static_cast<double>(runtime.trajectory_start_native[idx]);
    const double target = static_cast<double>(runtime.trajectory_target_native[idx]);
    point[idx] = static_cast<int64_t>(std::llround(start + (target - start) * smooth));
  }

  if (!runtime.trajectory_recovery_path) {
    const auto collision = check_robot_motion(
        actual_joints(state), joints_from_native(state, point),
        effective_collision_config(state, runtime.collision_config));
    if (!collision.ok) {
      publish_collision_result(state, collision, true);
      state.control.limit_alarm = 1;
      stop_all(state, runtime, false, "collision_rejected");
      synchronize_targets_to_actual(state);
      return;
    }
  }

  send_trajectory_point(state, runtime, point);
  runtime.trajectory_last_command_native = point;
  if (u >= 1.0) runtime.trajectory_active = false;
}

bool recovery_home_reached(const SharedState& state) {
  // The tolerance is below half the smallest displayed joint increment and
  // avoids waiting indefinitely for encoder-level holding jitter.
  constexpr int64_t kRecoveryToleranceNative = 250;
  for (int idx = 1; idx < kAxisCount; ++idx) {
    const auto& motor = state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]];
    if (std::llabs(motor.actual_motor_native) > kRecoveryToleranceNative ||
        std::llabs(motor.target_motor_native) > kRecoveryToleranceNative) {
      return false;
    }
  }
  return true;
}

void complete_recovery_home_if_ready(SharedState& state,
                                     HardwareRuntime& runtime) {
  auto& recovery = state.control.collision;
  if (!recovery.recovery_arm_zero_active || !recovery_home_reached(state)) {
    return;
  }

  // The only unlock decision uses the unmodified, full enclosure and tool
  // model.  A recovery command is therefore not a persistent bypass.
  const auto collision = check_robot_configuration(
      actual_joints(state), runtime.collision_config);
  recovery.recovery_arm_zero_active = 0;
  if (collision.ok) {
    recovery.manual_recovery = 0;
    state.control.limit_alarm = 0;
    publish_collision_result(state, collision, false);
    set_text(state.system_state, sizeof(state.system_state), "enabled");
    return;
  }

  publish_collision_result(state, collision, false);
  state.control.limit_alarm = 1;
  set_text(state.system_state, sizeof(state.system_state),
           "recovery_zero_still_colliding");
  // Do not hold torque against a boundary if the supposed storage pose is
  // still invalid.  Keep recovery flagged so Cartesian motion remains locked.
  stop_all(state, runtime, true, "recovery_zero_still_colliding");
}

void poll_feedback(SharedState& state, HardwareRuntime& runtime, int poll_count) {
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const int group = kAxisGroup[idx];
    const int slot = kAxisSlot[idx];
    auto& config = runtime.groups[group];
    auto& motor = state.groups[group].motors[slot];
    if (!config.active || !config.open) continue;

    std::string error;
    int64_t physical_position = 0;
    if (!config.bus.read_position(config.motor_ids[slot], physical_position, error)) {
      note_failure(state, runtime, idx, "read position", error);
      continue;
    }
    if (idx == 0 && runtime.axes[idx].brake_supported &&
        runtime.k0_resume_valid && !motor.enabled) {
      auto& axis = runtime.axes[idx];
      axis.offset_native = physical_position -
          static_cast<int64_t>(axis.direction) *
              runtime.k0_resume_logical_native;
    }
    update_feedback(state, runtime, idx, physical_position);
    auto& motion = runtime.motion[idx];
    if (motion.active) {
      motion.cumulative_abs_native +=
          std::llabs(motor.actual_motor_native - motion.last_native);
      motion.last_native = motor.actual_motor_native;
      const uint64_t sample_time = now_ms();
      const bool reached =
          std::llabs(motor.actual_motor_native - motion.target_native) <= 10;
      if (reached) {
        finish_motion_record(runtime, state, idx, "target_reached");
      } else if (sample_time - motion.last_checkpoint_ms >= 250) {
        if (!write_motion_event(runtime, state, idx, "progress",
                                motor.actual_motor_native)) {
          set_group_error(state, group,
                          "motion log or backup write failed");
        }
        motion.last_checkpoint_ms = sample_time;
      }
    }
    if (idx == 0 && motor.enabled &&
        std::llabs(motor.actual_motor_native -
                   motor.active_target_motor_native) <= 10) {
      if (!persist_k0_position(runtime, motor.actual_motor_native)) {
        motor.fault = 1;
        state.emergency_stop = 1;
        set_group_error(state, group, "persist settled K0 position failed");
      }
    }

    if (poll_count % runtime.status_every_polls == 0) {
      Mf9025v2Feedback feedback;
      if (!config.bus.read_status(config.motor_ids[slot], feedback, error) ||
          !config.bus.read_state(config.motor_ids[slot], feedback, error)) {
        note_failure(state, runtime, idx, "read status", error);
        continue;
      }
      update_feedback(state, runtime, idx, physical_position, &feedback);
      if (feedback.error_state != 0) {
        motor.fault = feedback.error_state;
        state.emergency_stop = 1;
        set_group_error(state, group,
                        "motor fault K" + std::to_string(idx) +
                        " error_state=" + std::to_string(feedback.error_state));
      }
      if (runtime.max_current_a > 0.0 &&
          std::abs(motor.actual_current_a) > runtime.max_current_a) {
        motor.fault = 1;
        state.emergency_stop = 1;
        set_group_error(state, group,
                        "over-current K" + std::to_string(idx));
      }
    }

    const auto& map = state.axis_map[idx];
    if (!runtime.allow_outside_limits &&
        (motor.actual_motor_native < map.min_motor_native - runtime.limit_margin_native[idx] ||
         motor.actual_motor_native > map.max_motor_native + runtime.limit_margin_native[idx])) {
      motor.fault = 1;
      state.control.limit_alarm = 1;
      state.emergency_stop = 1;
      set_group_error(state, group,
                      "soft-limit violation K" + std::to_string(idx));
    }
  }
}

int simulate_motor(SharedState& state) {
  long legacy_max_step = 0;
  if (const char* env = std::getenv("THERAPY_ROBOT_SIM_MAX_SPEED_NATIVE")) {
    legacy_max_step = std::max(1L, std::atol(env));
  }
  const int poll_ms = env_int("THERAPY_ROBOT_SIM_POLL_MS", 10, 1, 1000);
  const auto collision_config = collision_config_from_environment();
  publish_collision_config(state, collision_config);
  set_text(state.run_mode, sizeof(state.run_mode), "sim");
  set_text(state.system_state, sizeof(state.system_state), "sim_ready");
  state.simulation.hardware_mode = 0;
  state.simulation.enabled = 1;

  uint64_t last_target_seq = state.command.target_command_seq;
  std::array<int64_t, kAxisCount> accepted_targets{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    accepted_targets[idx] =
        state.groups[kAxisGroup[idx]].motors[kAxisSlot[idx]].actual_motor_native;
    state.command.target_native[idx] = accepted_targets[idx];
  }

  while (running) {
    state.motor_heartbeat_ms = now_ms();
    if (state.command.target_command_seq != last_target_seq) {
      last_target_seq = state.command.target_command_seq;
      std::array<int64_t, kAxisCount> requested{};
      state.control.limit_alarm = 0;
      for (int idx = 0; idx < kAxisCount; ++idx) {
        requested[idx] = clamped_target(state, idx, state.command.target_native[idx]);
      }
      const auto collision = check_robot_motion(
          actual_joints(state), joints_from_native(state, requested),
          collision_config);
      publish_collision_result(state, collision, !collision.ok);
      if (collision.ok && !state.emergency_stop) {
        accepted_targets = requested;
        state.command.target_native = requested;
      } else {
        state.control.limit_alarm = 1;
        set_text(state.system_state, sizeof(state.system_state),
                 collision.ok ? "estop_latched" : "collision_rejected");
        for (int idx = 0; idx < kAxisCount; ++idx) {
          accepted_targets[idx] = state.groups[kAxisGroup[idx]]
                                      .motors[kAxisSlot[idx]]
                                      .actual_motor_native;
          state.command.target_native[idx] = accepted_targets[idx];
        }
      }
    }

    const double multiplier = speed_multiplier();
    for (auto& group : state.groups) {
      for (int slot = 0; slot < group.motor_count; ++slot) {
        auto& motor = group.motors[slot];
        const int idx = axis_index(group.group, slot);
        if (idx < 0) continue;
        motor.target_motor_native = accepted_targets[idx];
        motor.active_target_motor_native = motor.target_motor_native;
        const auto before = motor.actual_motor_native;
        const long max_step = max_step_for_axis(
            state, idx, poll_ms, legacy_max_step, multiplier);
        motor.actual_motor_native = step_toward(
            motor.actual_motor_native, motor.active_target_motor_native, max_step);
        motor.actual_motor_native_velocity =
            (motor.actual_motor_native - before) * 1000.0 / poll_ms;
        motor.target_axis_si =
            axis_si_from_native(state, idx, motor.target_motor_native);
        motor.actual_axis_si =
            axis_si_from_native(state, idx, motor.actual_motor_native);
      }
    }
    if (collision_config.enabled) {
      const auto actual_collision = check_robot_configuration(
          actual_joints(state), collision_config);
      if (!actual_collision.ok) {
        publish_collision_result(state, actual_collision, false);
        state.emergency_stop = 1;
        state.control.limit_alarm = 1;
        set_text(state.system_state, sizeof(state.system_state),
                 "collision_estop");
        for (int idx = 0; idx < kAxisCount; ++idx) {
          accepted_targets[idx] = state.groups[kAxisGroup[idx]]
                                      .motors[kAxisSlot[idx]]
                                      .actual_motor_native;
          state.command.target_native[idx] = accepted_targets[idx];
        }
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(poll_ms));
  }
  return 0;
}

ControlSafetyDecision evaluate_queued_entity_control(
    const SharedState& state) {
  ControlRequest request;
  request.action = ControlActionKind::EntityControl;
  request.evaluated_at_ms = now_ms();
  request.request_id = state.control_safety.request_id;
  request.authorization_id = state.control_safety.authorization_id;
  request.input_units = state.control_safety.input_units;
  request.expected_input_units = state.control_safety.input_units;
  request.input_schema_valid = state.control_safety.input_schema_valid != 0;
  request.input_finite = state.control_safety.input_schema_valid != 0;
  request.has_unknown_fields = false;
  request.has_missing_fields = false;
  return evaluate_control_safety(control_safety_snapshot(state), request);
}

void publish_motor_gate_rejection(SharedState& state,
                                  const ControlSafetyDecision& decision) {
  state.control_safety.rejected_motor_commands++;
  const std::string reason = decision.reasons.empty()
                                 ? "motor_control_gate_rejected"
                                 : decision.reasons.front();
  set_text(state.control_safety.last_rejection,
           sizeof(state.control_safety.last_rejection), reason.c_str());
  set_text(state.system_state, sizeof(state.system_state),
           "control_gate_rejected");
}

int run_hardware(SharedState& state) {
  HardwareRuntime runtime;
  initialize_hardware(state, runtime);
  uint64_t last_command_seq = state.command.command_seq;
  uint64_t last_target_seq = state.command.target_command_seq;
  bool safety_stop_sent = false;
  int poll_count = 0;

  while (running) {
    const uint64_t now = now_ms();
    state.motor_heartbeat_ms = now;

    if (any_motor_enabled(state) &&
        (heartbeat_age(now, state.core_heartbeat_ms) >
             static_cast<uint64_t>(runtime.watchdog_ms) ||
         heartbeat_age(now, state.control.heartbeat_ms) >
             static_cast<uint64_t>(runtime.watchdog_ms))) {
      state.emergency_stop = 1;
      set_text(state.system_state, sizeof(state.system_state), "watchdog_estop");
    }

    if (state.emergency_stop) {
      if (!safety_stop_sent) {
        stop_all(state, runtime, true, "estop_latched");
        safety_stop_sent = true;
      }
    } else {
      safety_stop_sent = false;
    }

    if (state.command.command_seq != last_command_seq) {
      last_command_seq = state.command.command_seq;
      const bool fail_safe_stop = state.command.command_id == 4;
      ControlRequest stop_request;
      stop_request.action = ControlActionKind::FailSafeStop;
      const auto gate = fail_safe_stop
                            ? evaluate_control_safety(
                                  control_safety_snapshot(state),
                                  stop_request)
                            : evaluate_queued_entity_control(state);
      if (!gate.allowed) {
        publish_motor_gate_rejection(state, gate);
      } else {
        switch (state.command.command_id) {
          case 2:
            enable_all(state, runtime);
            last_target_seq = state.command.target_command_seq;
            break;
          case 3:
            stop_all(state, runtime, true, "disabled");
            break;
          case 4:
            stop_all(state, runtime, false, "stopped");
            break;
          case 5:
            zero_all_ram(state, runtime);
            last_target_seq = state.command.target_command_seq;
            break;
          case 6:
            recover_arm_zero(state, runtime);
            last_target_seq = state.command.target_command_seq;
            break;
          case 8:
            reconcile_confirmed_pose(state, runtime);
            last_target_seq = state.command.target_command_seq;
            break;
          default:
            state.control_safety.rejected_motor_commands++;
            set_text(state.control_safety.last_rejection,
                     sizeof(state.control_safety.last_rejection),
                     "unknown_motor_command_id");
            break;
        }
      }
    }

    if (!state.emergency_stop &&
        state.command.target_command_seq != last_target_seq) {
      last_target_seq = state.command.target_command_seq;
      const auto gate = evaluate_queued_entity_control(state);
      if (gate.allowed) {
        send_targets(state, runtime);
      } else {
        publish_motor_gate_rejection(state, gate);
      }
    }

    poll_feedback(state, runtime, poll_count++);
    advance_trajectory(state, runtime);
    complete_recovery_home_if_ready(state, runtime);
    if (!state.emergency_stop && runtime.collision_config.enabled &&
        !state.control.collision.recovery_arm_zero_active &&
        !state.control.collision.manual_recovery) {
      const auto actual_collision = check_robot_configuration(
          actual_joints(state), effective_collision_config(state, runtime.collision_config));
      if (!actual_collision.ok) {
        publish_collision_result(state, actual_collision, false);
        state.emergency_stop = 1;
        state.control.limit_alarm = 1;
        if (!safety_stop_sent) {
          stop_all(state, runtime, true, "collision_estop");
          safety_stop_sent = true;
        }
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(runtime.poll_ms));
  }

  stop_all(state, runtime, true, "shutdown");
  return 0;
}

}  // namespace

int main() {
  std::signal(SIGINT, on_signal);
  std::signal(SIGTERM, on_signal);
  try {
    auto* state = open_or_create_shared_state(false);
    if (!env_flag("THERAPY_ROBOT_HARDWARE", false)) {
      return simulate_motor(*state);
    }
    return run_hardware(*state);
  } catch (const std::exception& error) {
    std::cerr << "main_motor: " << error.what() << '\n';
    return 1;
  }
}
