#include "therapy_robot/collision.hpp"
#include "therapy_robot/control_safety_gate.hpp"
#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/motion_plan.hpp"
#include "therapy_robot/readiness.hpp"
#include "therapy_robot/shared_memory.hpp"
#include "therapy_robot/workflow.hpp"
#include "httplib.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#if __has_include(<filesystem>) && (!defined(__GNUC__) || __GNUC__ >= 8)
#include <filesystem>
namespace fs = std::filesystem;
#else
#include <experimental/filesystem>
namespace fs = std::experimental::filesystem;
#endif
#include <fstream>
#include <iostream>
#include <signal.h>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/types.h>
#include <utility>
#include <vector>

using namespace therapy_robot;

namespace {
std::string root_dir() {
  if (const char* env = std::getenv("THERAPY_ROBOT_ROOT")) return env;
  return fs::current_path().string();
}

bool is_safe_runtime_path_character(char value) {
  return (value >= 'a' && value <= 'z') ||
         (value >= 'A' && value <= 'Z') ||
         (value >= '0' && value <= '9') || value == '/' || value == '_' ||
         value == '-' || value == '.';
}

const std::string& runtime_dir() {
  static const std::string value = [] {
    const char* configured = std::getenv("THERAPY_ROBOT_RUNTIME_DIR");
    const std::string candidate = configured ? configured : "/tmp/therapy_robot";
    if (candidate.size() < 2 || candidate.size() > 4095 || candidate[0] != '/' ||
        candidate.back() == '/') {
      throw std::invalid_argument(
          "invalid THERAPY_ROBOT_RUNTIME_DIR: expected a non-root absolute path");
    }
    std::size_t component_start = 1;
    for (std::size_t index = 1; index <= candidate.size(); ++index) {
      if (index < candidate.size() &&
          !is_safe_runtime_path_character(candidate[index])) {
        throw std::invalid_argument(
            "invalid THERAPY_ROBOT_RUNTIME_DIR: path contains unsafe characters");
      }
      if (index == candidate.size() || candidate[index] == '/') {
        const std::string component =
            candidate.substr(component_start, index - component_start);
        if (component.empty() || component == "." || component == "..") {
          throw std::invalid_argument(
              "invalid THERAPY_ROBOT_RUNTIME_DIR: empty, '.' and '..' components are forbidden");
        }
        component_start = index + 1;
      }
    }
    return candidate;
  }();
  return value;
}

std::string runtime_file(const char* filename) {
  return (fs::path(runtime_dir()) / filename).string();
}

int configured_port(const char* variable, int fallback) {
  const char* configured = std::getenv(variable);
  if (!configured) return fallback;
  if (*configured == '\0') {
    throw std::invalid_argument(std::string("invalid ") + variable + ": empty value");
  }
  errno = 0;
  char* end = nullptr;
  const long value = std::strtol(configured, &end, 10);
  if (errno != 0 || !end || *end != '\0' || value < 1 || value > 65535) {
    throw std::invalid_argument(std::string("invalid ") + variable +
                                ": expected an integer from 1 to 65535");
  }
  return static_cast<int>(value);
}

int current_web_port() {
#ifdef THERAPY_ROBOT_WEB_SIM
  return configured_port("THERAPY_ROBOT_SIM_WEB_PORT", 8081);
#else
  return configured_port("THERAPY_ROBOT_WEB_PORT", 8080);
#endif
}

std::string read_file(const fs::path& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) return {};
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

std::string escape_json(const char* s) {
  std::string out;
  for (const char* p = s ? s : ""; *p; ++p) {
    if (*p == '"') out += "\\\"";
    else if (*p == '\\') out += "\\\\";
    else if (*p == '\n') out += "\\n";
    else out += *p;
  }
  return out;
}

std::string escape_json_string(const std::string& value) {
  return escape_json(value.c_str());
}

WorkflowFacts workflow_facts_snapshot(const SharedState& state,
                                      const CollisionConfig& collision_config) {
  WorkflowFacts facts;
  facts.run_mode = state.run_mode;
  facts.system_state = state.system_state;
  facts.emergency_stop = state.emergency_stop != 0;
  facts.collision_configured = collision_config.configured ||
                               state.control.collision.configured != 0;
  facts.collision_enabled = collision_config.enabled ||
                            state.control.collision.enabled != 0;
  facts.collision_required = collision_config.required;
  facts.collision_alarm = state.control.collision.alarm != 0;
  facts.manual_recovery = state.control.collision.manual_recovery != 0;
  facts.axes_configured = true;
  facts.axes_online = true;
  facts.axes_fault_free = true;
  facts.axes_enabled = false;
  for (int index = 0; index < kAxisCount; ++index) {
    const auto& axis = state.axis_map[index];
    if (axis.group < 0 || axis.group >= kGroupCount || axis.axis < 0 ||
        axis.axis >= kMaxMotorsPerGroup) {
      facts.axes_configured = false;
      facts.axes_online = false;
      facts.axes_fault_free = false;
      continue;
    }
    const auto& motor = state.groups[axis.group].motors[axis.axis];
    facts.axes_configured = facts.axes_configured && motor.configured != 0;
    facts.axes_online = facts.axes_online && motor.online != 0;
    facts.axes_fault_free = facts.axes_fault_free && motor.fault == 0;
    facts.axes_enabled = facts.axes_enabled || motor.enabled != 0;
  }
  const fs::path root = root_dir();
  // Only an explicitly named production artifact counts.  Example/sample
  // files are intentionally ignored so fixtures cannot unlock this gate.
  facts.formal_camera_extrinsics_present =
      fs::exists(root / "calibration/camera_to_base.json") ||
      fs::exists(root / "calibration/camera_to_base_formal.json");
  facts.entity_offsets_verified =
      fs::exists(root / "calibration/entity-axis-offsets-verified.json") ||
      fs::exists(root / "calibration/axis-offsets-native-verified.json");
  facts.source_state.command_seq = state.command.command_seq;
  facts.source_state.target_command_seq = state.command.target_command_seq;
  facts.source_state.endpoint_target_seq = state.control.endpoint_target.target_seq;
  return facts;
}

std::string hash_file_or_missing(const fs::path& path) {
  if (!fs::exists(path)) return "missing";
  return "sha256:" + sha256_hex(read_file(path));
}

fs::path first_existing_path(const fs::path& first, const fs::path& second) {
  return fs::exists(first) ? first : second;
}

std::string trimmed_line(std::string value) {
  while (!value.empty() && (value.back() == '\n' || value.back() == '\r' ||
                            value.back() == ' ' || value.back() == '\t')) {
    value.pop_back();
  }
  return value;
}

bool is_commit_hash(const std::string& value) {
  return value.size() == 40 &&
         std::all_of(value.begin(), value.end(), [](unsigned char c) {
           return std::isxdigit(c) != 0;
         });
}

std::string repository_commit(const fs::path& root) {
  fs::path git_dir = root / ".git";
  if (fs::is_regular_file(git_dir)) {
    const std::string marker = "gitdir: ";
    const auto pointer = trimmed_line(read_file(git_dir));
    if (pointer.rfind(marker, 0) != 0) return "unknown";
    git_dir = fs::path(pointer.substr(marker.size()));
    if (git_dir.is_relative()) git_dir = root / git_dir;
  }
  const auto head = trimmed_line(read_file(git_dir / "HEAD"));
  if (is_commit_hash(head)) return head;
  const std::string ref_marker = "ref: ";
  if (head.rfind(ref_marker, 0) != 0) return "unknown";
  const auto ref = head.substr(ref_marker.size());
  auto commit = trimmed_line(read_file(git_dir / ref));
  if (!is_commit_hash(commit)) {
    const auto common_pointer = trimmed_line(read_file(git_dir / "commondir"));
    if (!common_pointer.empty()) {
      fs::path common_dir = common_pointer;
      if (common_dir.is_relative()) common_dir = git_dir / common_dir;
      commit = trimmed_line(read_file(common_dir / ref));
    }
  }
  return is_commit_hash(commit) ? commit : "unknown";
}

ReadinessInput readiness_input_snapshot(const SharedState& state,
                                        const CollisionConfig& collision_config) {
  const auto facts = workflow_facts_snapshot(state, collision_config);
  ReadinessInput input;
  input.source_state = {facts.source_state.command_seq,
                        facts.source_state.target_command_seq,
                        facts.source_state.endpoint_target_seq};
  input.source_state_known = state.magic == 0x54524f42 && state.version == 3;
  input.safety_state_known = input.source_state_known;
  input.configuration_known = input.source_state_known;
  input.emergency_stop = facts.emergency_stop;
  input.collision_configured = facts.collision_configured;
  input.collision_enabled = facts.collision_enabled;
  input.collision_alarm = facts.collision_alarm;
  input.manual_recovery = facts.manual_recovery;
  input.axes_configured = facts.axes_configured;
  input.axes_online = facts.axes_online;
  input.axes_fault_free = facts.axes_fault_free;
  input.axes_enabled = facts.axes_enabled;
  input.formal_camera_extrinsics_present = facts.formal_camera_extrinsics_present;
  input.entity_offsets_verified = facts.entity_offsets_verified;
  const fs::path root = root_dir();
  const auto camera_path = first_existing_path(
      root / "calibration/camera_to_base.json",
      root / "calibration/camera_to_base_formal.json");
  const auto offsets_path = first_existing_path(
      root / "calibration/entity-axis-offsets-verified.json",
      root / "calibration/axis-offsets-native-verified.json");
  const auto k0_path = first_existing_path(
      root / "calibration/k0-parameters.json",
      root / "calibration/k0_formal_parameters.json");
  input.formal_k0_parameters_present =
      fs::exists(k0_path);
  input.nano_configuration_present = fs::exists(root / "config/jetson-hardware.env");
  input.software_commit = std::getenv("THERAPY_ROBOT_SOFTWARE_COMMIT")
                              ? std::getenv("THERAPY_ROBOT_SOFTWARE_COMMIT")
                              : repository_commit(root);
  input.config_hashes["collision_config"] =
      hash_file_or_missing(collision_config.source_path.empty()
                               ? root / "config/enclosure-collision.csv"
                               : fs::path(collision_config.source_path));
  input.config_hashes["formal_camera_extrinsics"] =
      hash_file_or_missing(camera_path);
  input.config_hashes["entity_offsets"] =
      hash_file_or_missing(offsets_path);
  input.config_hashes["formal_k0_parameters"] =
      hash_file_or_missing(k0_path);
  input.config_hashes["nano_configuration"] =
      hash_file_or_missing(root / "config/jetson-hardware.env");
  return input;
}

std::string workflow_blocking_reasons_json(
    const std::vector<WorkflowBlockingReason>& reasons) {
  std::ostringstream out;
  out << '[';
  for (std::size_t index = 0; index < reasons.size(); ++index) {
    if (index) out << ',';
    const auto& reason = reasons[index];
    out << "{\"code\":\"" << escape_json_string(reason.code)
        << "\",\"source\":\"" << escape_json_string(reason.source)
        << "\",\"severity\":\"" << escape_json_string(reason.severity)
        << "\",\"message\":\"" << escape_json_string(reason.message)
        << "\"}";
  }
  out << ']';
  return out.str();
}

std::string workflow_common_json(const WorkflowAssessment& assessment,
                                 const WorkflowSourceState& source,
                                 bool ok, const char* error_code = nullptr) {
  std::ostringstream out;
  out << "{\"schema_version\":\"b2.v1\",\"ok\":" << (ok ? "true" : "false")
      << ",\"motor_command_written\":false,\"source_state\":{";
  out << "\"command_seq\":" << source.command_seq
      << ",\"target_command_seq\":" << source.target_command_seq
      << ",\"endpoint_target_seq\":" << source.endpoint_target_seq << "},";
  out << "\"blocking_reasons\":"
      << workflow_blocking_reasons_json(assessment.blocking_reasons);
  if (error_code) out << ",\"error_code\":\"" << escape_json(error_code) << "\"";
  return out.str();
}

void append_workflow_summary(std::ostringstream& out,
                             const WorkflowSummary& summary) {
  out << "{\"status\":\"" << escape_json(summary.status.c_str())
      << "\",\"passed\":" << summary.passed
      << ",\"failed\":" << summary.failed
      << ",\"unknown\":" << summary.unknown << '}';
}

std::string workflow_state_json(const WorkflowFacts& facts,
                                const WorkflowAssessment& assessment) {
  std::ostringstream out;
  out << workflow_common_json(assessment, facts.source_state, true);
  out << ",\"workflow_state\":\"" << escape_json(assessment.workflow_state.c_str())
      << "\",\"allowed_actions\":[";
  for (std::size_t index = 0; index < assessment.allowed_actions.size(); ++index) {
    if (index) out << ',';
    out << "\"" << escape_json(assessment.allowed_actions[index].c_str()) << "\"";
  }
  out << "],\"self_check_summary\":";
  append_workflow_summary(out, assessment.self_check_summary);
  out << ",\"plan_id\":null,\"plan_hash\":null,\"execution_locked\":true}";
  return out.str();
}

std::string workflow_self_check_json(const WorkflowFacts& facts,
                                     const WorkflowAssessment& assessment) {
  std::ostringstream out;
  out << workflow_common_json(assessment, facts.source_state, true)
      << ",\"self_check_summary\":";
  append_workflow_summary(out, assessment.self_check_summary);
  out << ",\"checks\":[";
  for (std::size_t index = 0; index < assessment.checks.size(); ++index) {
    if (index) out << ',';
    const auto& check = assessment.checks[index];
    out << "{\"id\":\"" << escape_json(check.id.c_str())
        << "\",\"status\":\"" << workflow_check_status_name(check.status)
        << "\",\"blocking\":" << (check.blocking ? "true" : "false")
        << ",\"reason_code\":";
    if (check.reason_code.empty()) {
      out << "null";
    } else {
      out << "\"" << escape_json(check.reason_code.c_str()) << "\"";
    }
    out << ",\"observed\":\"" << escape_json(check.observed.c_str()) << "\"}";
  }
  out << "]}";
  return out.str();
}

void add_motion_plan_blocker(WorkflowAssessment& assessment,
                             std::string code, std::string source,
                             std::string message) {
  assessment.blocking_reasons.push_back(
      {std::move(code), std::move(source), "blocking", std::move(message)});
}

std::string motion_plan_error_json(const WorkflowFacts& facts,
                                   WorkflowAssessment assessment,
                                   const char* error_code) {
  add_motion_plan_blocker(assessment, error_code, "motion_plan.side",
                          "exactly one side value, left or right, is required");
  return workflow_common_json(assessment, facts.source_state, false,
                              error_code) + "}";
}

std::string motion_plan_preview_json(const WorkflowFacts& facts,
                                     WorkflowAssessment assessment,
                                     const MotionPlan& plan) {
  add_motion_plan_blocker(assessment, "synthetic_motion_plan_only",
                          "motion_plan.parameters",
                          "B2 route parameters are synthetic and not approved for formal use");
  for (const auto& segment : plan.segments()) {
    if (segment.preflight().ok() && segment.preflight().collision_checked()) {
      continue;
    }
    std::ostringstream message;
    message << segment.preflight().reason_code();
    if (!segment.preflight().collision_link().empty()) {
      message << "; link=" << segment.preflight().collision_link();
    }
    if (!segment.preflight().collision_obstacle().empty()) {
      message << "; obstacle=" << segment.preflight().collision_obstacle();
    }
    add_motion_plan_blocker(assessment, "motion_plan_preflight_failed",
                            segment.segment_id(), message.str());
  }

  std::ostringstream out;
  out << workflow_common_json(assessment, facts.source_state, true)
      << ",\"plan_id\":\"" << motion_plan_id(plan)
      << "\",\"plan_hash\":\"" << motion_plan_hash(plan)
      << "\",\"preview_valid\":false,\"execution_allowed\":false,\"plan\":"
      << canonical_motion_plan_json(plan) << '}';
  return out.str();
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

std::array<int64_t, kAxisCount> actual_native_positions(
    const SharedState& state) {
  std::array<int64_t, kAxisCount> positions{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const auto& axis = state.axis_map[idx];
    positions[idx] = state.groups[axis.group].motors[axis.axis].actual_motor_native;
  }
  return positions;
}

bool all_axes_ready(const SharedState& state, std::string& reason) {
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const auto& axis = state.axis_map[idx];
    const auto& motor = state.groups[axis.group].motors[axis.axis];
    if (!motor.configured) {
      reason = "K" + std::to_string(idx) + " is not configured";
      return false;
    }
    if (!motor.online) {
      reason = "K" + std::to_string(idx) + " is offline";
      return false;
    }
    if (!motor.enabled) {
      reason = "K" + std::to_string(idx) + " is not enabled";
      return false;
    }
    if (motor.fault) {
      reason = "K" + std::to_string(idx) + " has a fault";
      return false;
    }
  }
  return true;
}

bool all_motors_disabled(const SharedState& state, std::string& reason) {
  if (state.command.command_id == 2) {
    reason = "enable command is pending; send disable_all first";
    return false;
  }
  for (int group = 0; group < kGroupCount; ++group) {
    for (int slot = 0; slot < state.groups[group].motor_count; ++slot) {
      if (state.groups[group].motors[slot].enabled) {
        reason = "K" + std::to_string(state.groups[group].motors[slot].axis) + " is still enabled";
        return false;
      }
    }
  }
  return true;
}

JointState joints_from_native_targets(
    const SharedState& state,
    const std::array<int64_t, kAxisCount>& requested) {
  std::array<double, kAxisCount> value{};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const auto& axis = state.axis_map[idx];
    const auto native = std::clamp(requested[idx], axis.min_motor_native,
                                   axis.max_motor_native);
    const double display = native * axis.motor_native_to_gui_display;
    value[idx] = idx == 0 ? display / 1000.0
                          : display * 3.14159265358979323846 / 180.0;
  }
  return {value[0], value[1], value[2], value[3], value[4]};
}

bool native_targets_from_joints(
    const SharedState& state, const JointState& joints,
    std::array<int64_t, kAxisCount>& requested, std::string& reason) {
  constexpr double kRadToDeg = 180.0 / 3.14159265358979323846;
  const std::array<double, kAxisCount> display{{
      joints.k0_m * 1000.0,
      joints.k1_rad * kRadToDeg,
      joints.k2_rad * kRadToDeg,
      joints.k3_rad * kRadToDeg,
      joints.k4_rad * kRadToDeg,
  }};
  for (int idx = 0; idx < kAxisCount; ++idx) {
    const auto& axis = state.axis_map[idx];
    if (!std::isfinite(axis.motor_native_to_gui_display) ||
        std::abs(axis.motor_native_to_gui_display) < 1e-12) {
      reason = "K" + std::to_string(idx) + " conversion scale is invalid";
      return false;
    }
    requested[idx] = static_cast<int64_t>(std::llround(
        display[idx] / axis.motor_native_to_gui_display));
    if (requested[idx] < axis.min_motor_native ||
        requested[idx] > axis.max_motor_native) {
      reason = "IK target exceeds K" + std::to_string(idx) + " soft limit";
      return false;
    }
  }
  return true;
}

std::string json_state(const SharedState& s) {
  std::ostringstream o;
  o << "{";
  o << "\"run_mode\":\"" << escape_json(s.run_mode) << "\",";
  o << "\"system_state\":\"" << escape_json(s.system_state) << "\",";
  o << "\"emergency_stop\":" << s.emergency_stop << ',';
  o << "\"core_heartbeat_ms\":" << s.core_heartbeat_ms << ',';
  o << "\"motor_heartbeat_ms\":" << s.motor_heartbeat_ms << ',';
  o << "\"sim_heartbeat_ms\":" << s.sim_heartbeat_ms << ',';
  o << "\"web_heartbeat_ms\":" << s.web_heartbeat_ms << ',';
  o << "\"heartbeats\":{";
  o << "\"core\":" << s.core_heartbeat_ms << ",\"control\":" << s.control.heartbeat_ms << ",\"motor\":" << s.motor_heartbeat_ms << ",\"web\":" << s.web_heartbeat_ms << ",\"sim\":" << s.sim_heartbeat_ms << "},";
  o << "\"command\":{";
  o << "\"command_seq\":" << s.command.command_seq << ",\"command_id\":" << s.command.command_id << ",\"target_command_seq\":" << s.command.target_command_seq << ",\"target_command_id\":" << s.command.target_command_id << "},";
  const auto& ep = s.control.endpoint_target;
  const auto& collision = s.control.collision;
  o << "\"control\":{";
  o << "\"heartbeat_ms\":" << s.control.heartbeat_ms << ",\"active_target_seq\":" << s.control.active_target_seq << ",\"limit_alarm\":" << s.control.limit_alarm << ",";
  o << "\"collision\":{";
  o << "\"configured\":" << collision.configured << ",\"enabled\":" << collision.enabled << ",\"alarm\":" << collision.alarm << ",\"manual_recovery\":" << collision.manual_recovery << ",\"recovery_arm_zero_active\":" << collision.recovery_arm_zero_active << ",";
  o << "\"rejected_commands\":" << collision.rejected_commands << ",\"path_fraction\":" << collision.path_fraction << ",";
  o << "\"status\":\"" << escape_json(collision.status) << "\",\"link_name\":\"" << escape_json(collision.link_name) << "\",";
  o << "\"obstacle_name\":\"" << escape_json(collision.obstacle_name) << "\",\"last_error\":\"" << escape_json(collision.last_error) << "\",";
  o << "\"config_path\":\"" << escape_json(collision.config_path) << "\"},";
  o << "\"endpoint_target\":{";
  o << "\"valid\":" << ep.valid << ",\"target_seq\":" << ep.target_seq << ",\"status\":" << ep.status << ",\"last_error\":\"" << escape_json(ep.last_error) << "\",";
  o << "\"x_m\":" << ep.x_m << ",\"y_m\":" << ep.y_m << ",\"z_m\":" << ep.z_m << ",\"rx_rad\":" << ep.rx_rad << ",\"ry_rad\":" << ep.ry_rad << ",\"rz_rad\":" << ep.rz_rad << ",";
  o << "\"last_position_error_m\":" << ep.last_position_error_m << ",\"last_direction_error_rad\":" << ep.last_direction_error_rad << "}},";
  o << "\"simulation\":{";
  o << "\"enabled\":" << s.simulation.enabled << ",\"hardware_mode\":" << s.simulation.hardware_mode << ",\"mujoco_available\":" << s.simulation.mujoco_available << ",";
  o << "\"end_effector_x_m\":" << s.simulation.end_effector_x_m << ",\"end_effector_y_m\":" << s.simulation.end_effector_y_m << ",\"end_effector_z_m\":" << s.simulation.end_effector_z_m << "},";
  o << "\"axis_map\":[";
  for (int i = 0; i < kAxisCount; ++i) {
    const auto& a = s.axis_map[i];
    if (i) o << ',';
    o << "{\"group\":" << a.group << ",\"axis\":" << a.axis << ",\"global_axis\":" << a.global_axis << ",\"kind\":" << a.kind;
    o << ",\"name\":\"" << escape_json(a.name) << "\",\"gui_display_unit\":\"" << escape_json(a.gui_display_unit) << "\",";
    o << "\"motor_native_to_gui_display\":" << a.motor_native_to_gui_display << ",\"min_motor_native\":" << a.min_motor_native << ",\"max_motor_native\":" << a.max_motor_native << "}";
  }
  o << "],\"groups\":[";
  for (int g = 0; g < kGroupCount; ++g) {
    const auto& group = s.groups[g];
    if (g) o << ',';
    o << "{\"group\":" << group.group << ",\"hardware_enabled\":" << group.hardware_enabled << ",\"motor_count\":" << group.motor_count << ",";
    o << "\"port\":\"" << escape_json(group.port) << "\",\"last_error\":\"" << escape_json(group.last_error) << "\",\"motors\":[";
    for (int a = 0; a < kMaxMotorsPerGroup; ++a) {
      const auto& m = group.motors[a];
      if (a) o << ',';
      o << "{\"configured\":" << m.configured << ",\"motor_id\":" << m.motor_id << ",\"axis\":" << m.axis << ",\"online\":" << m.online << ",\"enabled\":" << m.enabled;
      o << ",\"fault\":" << m.fault << ",\"mode\":" << m.mode << ",\"brake_supported\":" << m.brake_supported << ",\"brake_engaged\":" << m.brake_engaged;
      o << ",\"brake_release_requested\":" << m.brake_release_requested << ",\"brake_state_known\":" << m.brake_state_known << ",\"brake_last_error\":\"" << escape_json(m.brake_last_error) << "\",";
      o << "\"actual_motor_native\":" << m.actual_motor_native << ",\"target_motor_native\":" << m.target_motor_native << ",\"active_target_motor_native\":" << m.active_target_motor_native;
      o << ",\"actual_axis_si\":" << m.actual_axis_si << ",\"target_axis_si\":" << m.target_axis_si << ",\"actual_motor_native_velocity\":" << m.actual_motor_native_velocity << ",\"actual_current_a\":" << m.actual_current_a << "}";
    }
    o << "]}";
  }
  o << "]}";
  return o.str();
}

CollisionConfig effective_collision_config(const SharedState& state,
                                           const CollisionConfig& base) {
  (void)state;
  return base;
}

double extract_number(const std::string& body, const std::string& key, double fallback = 0.0) {
  auto p = body.find("\"" + key + "\"");
  if (p == std::string::npos) return fallback;
  p = body.find(':', p);
  if (p == std::string::npos) return fallback;
  char* end = nullptr;
  double v = std::strtod(body.c_str() + p + 1, &end);
  return end ? v : fallback;
}

std::string extract_string(const std::string& body, const std::string& key) {
  auto p = body.find("\"" + key + "\"");
  if (p == std::string::npos) return {};
  p = body.find(':', p);
  if (p == std::string::npos) return {};
  p = body.find('"', p);
  if (p == std::string::npos) return {};
  std::string value;
  for (++p; p < body.size(); ++p) {
    if (body[p] == '"') break;
    if (body[p] == '\\' && p + 1 < body.size()) ++p;
    value += body[p];
  }
  return value;
}

void write_speed_multiplier(double value) {
  fs::create_directories(runtime_dir());
  std::ofstream out(runtime_file("speed_multiplier"), std::ios::trunc);
  out << value << '\n';
}

std::string tail_text(const std::string& text, std::size_t max_chars) {
  if (text.size() <= max_chars) return text;
  return text.substr(text.size() - max_chars);
}

bool ends_with(const std::string& value, const std::string& suffix) {
  return value.size() >= suffix.size() && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

struct MotionTestPoint {
  int index;
  const char* name;
  const char* description;
  double x_mm;
  double y_mm;
  double z_mm;
};

bool process_running(int pid);

std::vector<MotionTestPoint> motion_test_points(const std::string& side) {
  const double x = side == "left" ? -575.0 : 575.0;
  std::vector<MotionTestPoint> points;
  points.reserve(30);
  auto add = [&](const char* name, const char* description,
                 double px, double py, double pz) {
    points.push_back({static_cast<int>(points.size() + 1), name, description,
                      px, py, pz});
  };

  // Offline-simulated back coverage route.  Its 125 x 250 mm working footprint
  // was checked with the enclosure model, full link envelopes, and sixty
  // synchronized joint-interpolation samples per segment.  The arm leaves the
  // enclosure only in the high plane, then descends through one exterior
  // corridor; it returns through that corridor before lifting again.
  const double sign = side == "left" ? -1.0 : 1.0;
  add("High ready", "K0=313.1 mm, about 1 mm below the recorded stable maximum", 0.0, 232.0, 790.0);
  add("High deploy 1", "High-plane move only", sign * 450.0, 250.0, 790.0);
  add("High deploy 2", "High-plane exterior deployment", sign * 575.0, 250.0, 790.0);
  add("Descent 1", "Exterior staged descent", x, 250.0, 755.0);
  add("Descent 2", "Exterior staged descent", x, 250.0, 720.0);
  add("Descent 3", "Exterior staged descent", x, 250.0, 685.0);
  add("Work corridor", "Reach the exterior work height", x, 250.0, 650.0);
  add("Upper outer", "Upper back strip", sign * 575.0, 300.0, 650.0);
  add("Upper inner", "Upper back strip", sign * 550.0, 300.0, 650.0);
  add("Upper return", "Return to the safe exterior corridor", sign * 550.0, 250.0, 650.0);
  add("Middle inner", "Middle back strip", sign * 500.0, 250.0, 650.0);
  add("Middle forward", "Middle back strip", sign * 500.0, 200.0, 650.0);
  add("Middle outer", "Middle back strip", sign * 600.0, 200.0, 650.0);
  add("Lower forward", "Lower back strip", sign * 600.0, 150.0, 650.0);
  add("Lower inner", "Lower back strip", sign * 500.0, 150.0, 650.0);
  add("Lower middle", "Lower back strip", sign * 500.0, 100.0, 650.0);
  add("Lower outer", "Lower back strip", sign * 625.0, 100.0, 650.0);
  add("Lower front", "Lower back strip", sign * 625.0, 50.0, 650.0);
  add("Exit inner", "Return through the exterior corridor", sign * 500.0, 50.0, 650.0);
  add("Exit middle", "Return through the exterior corridor", sign * 500.0, 250.0, 650.0);
  add("Exit outer", "Return through the exterior corridor", x, 250.0, 650.0);
  add("Lift 1", "Exterior staged lift", x, 250.0, 685.0);
  add("Lift 2", "Exterior staged lift", x, 250.0, 720.0);
  add("Lift 3", "Exterior staged lift", x, 250.0, 755.0);
  add("High exit", "Lift clear before crossing the enclosure projection", x, 250.0, 790.0);
  add("High return", "High-plane return to the enclosure center", 0.0, 232.0, 790.0);
  return points;

#if 0

  // Deployment and lowering are deliberately separate. The arm must first
  // clear the enclosure at full height before any downward command is issued.
  add("高位准备", "K0=313.1mm，比已记录稳定最高点低约1mm", 0.0, 232.0, 790.0);
  add("高位转出1", "只在保险高位向机箱侧前方转出", 450.0 * (side == "left" ? -1.0 : 1.0), 250.0, 790.0);
  add("高位转出2", "只在保险高位继续向外转出", x, 250.0, 790.0);
  add(side_name, "在保险高位转到下降起点", x, 250.0, 790.0);
  add("下降1", "侧方垂直下降，保持X/Y不变", x, 250.0, 755.0);
  add("下降2", "侧方垂直下降，保持X/Y不变", x, 250.0, 720.0);
  add("下降3", "侧方垂直下降，保持X/Y不变", x, 250.0, 685.0);
  add("工作高度", "到达Y向直线测试高度", x, 250.0, 650.0);
  for (double y : {275.0, 300.0}) {
    add("Y向前进", "固定X/Z，沿患者脊柱方向前进", x, y, 650.0);
  }
  for (double y : {275.0, 250.0}) {
    add("Y向返回", "固定X/Z，沿原路径返回", x, y, 650.0);
  }
  add("抬升1", "侧方垂直抬升，保持X/Y不变", x, 250.0, 685.0);
  add("抬升2", "侧方垂直抬升，保持X/Y不变", x, 250.0, 720.0);
  add("抬升3", "侧方垂直抬升，保持X/Y不变", x, 250.0, 755.0);
  add("高位退出", "完全抬升后准备收回", x, 250.0, 790.0);
  add("高位返回", "只在保险高位收回机箱中心", 0.0, 232.0, 790.0);
#endif
  return points;
}

struct MotionPathPointCheck {
  bool ok = false;
  std::string reason;
  JointState joints{};
  CollisionCheck collision{};
};

std::vector<MotionPathPointCheck> check_motion_test_path(
    const SharedState& state, const CollisionConfig& collision_config,
    const std::vector<MotionTestPoint>& points) {
  std::vector<MotionPathPointCheck> checks;
  checks.reserve(points.size());
  JointState previous = actual_joints(state);
  for (std::size_t point_index = 0; point_index < points.size(); ++point_index) {
    const auto& point = points[point_index];
    MotionPathPointCheck check;
    Pose target;
    target.x_m = point.x_mm / 1000.0;
    target.y_m = point.y_mm / 1000.0;
    target.z_m = point.z_mm / 1000.0;
    const auto ik = inverse_kinematics(target, previous);
    check.joints = ik.joints;
    check.reason = ik.ok ? "ok" : ik.error;
    std::array<int64_t, kAxisCount> requested{};
    if (ik.ok && !native_targets_from_joints(state, ik.joints, requested,
                                              check.reason)) {
      check.ok = false;
    } else if (ik.ok) {
      check.collision = check_endpoint_motion(
          previous, ik.joints,
          effective_collision_config(state, collision_config));
      check.ok = check.collision.ok;
      if (!check.ok) check.reason = check.collision.reason;
      // Once deployed, the complete forearm envelope must remain outside the
      // enclosure's vertical projection until it has been raised again.  This
      // prevents a collision that endpoint-only checking cannot detect while
      // lowering beside the cabinet.
      if (check.ok && point.z_mm < 785.0 && point_index >= 1 && point_index + 1 < points.size()) {
        constexpr double kEnclosureHalfWidthM = 0.1805;
        constexpr double kAdditionalClearanceM = 0.030;
        const auto links = robot_link_points(ik.joints);
        const double start_x = links.forearm_start.x_m;
        const double end_x = links.forearm_end.x_m;
        const bool crosses_center = start_x * end_x <= 0.0;
        const double surface_clearance = std::min(std::abs(start_x), std::abs(end_x)) -
            collision_config.envelope.forearm_radius_m -
            collision_config.safety_margin_m - kEnclosureHalfWidthM;
        if (crosses_center || surface_clearance < kAdditionalClearanceM) {
          check.ok = false;
          std::ostringstream error;
          error << "forearm enters enclosure vertical projection; clearance="
                << surface_clearance * 1000.0 << " mm, required >= 30 mm";
          check.reason = error.str();
        }
        // The motor process follows synchronized joint interpolation, so
        // verify that same swept path, not only the Cartesian waypoints.
        // The high-plane deployment move (point 1) may cross the enclosure
        // projection; every later move must remain completely outside it.
        if (check.ok && point.z_mm < 785.0 && point_index >= 2) {
          for (int sample_index = 1; sample_index <= 60; ++sample_index) {
            const double t = static_cast<double>(sample_index) / 60.0;
            JointState swept;
            swept.k0_m = previous.k0_m + (ik.joints.k0_m - previous.k0_m) * t;
            swept.k1_rad = previous.k1_rad + (ik.joints.k1_rad - previous.k1_rad) * t;
            swept.k2_rad = previous.k2_rad + (ik.joints.k2_rad - previous.k2_rad) * t;
            swept.k3_rad = previous.k3_rad + (ik.joints.k3_rad - previous.k3_rad) * t;
            swept.k4_rad = previous.k4_rad + (ik.joints.k4_rad - previous.k4_rad) * t;
            const auto swept_links = robot_link_points(swept);
            const double swept_start_x = swept_links.forearm_start.x_m;
            const double swept_end_x = swept_links.forearm_end.x_m;
            const bool swept_crosses_center = swept_start_x * swept_end_x <= 0.0;
            const double swept_clearance =
                std::min(std::abs(swept_start_x), std::abs(swept_end_x)) -
                collision_config.envelope.forearm_radius_m -
                collision_config.safety_margin_m - kEnclosureHalfWidthM;
            if (swept_crosses_center || swept_clearance < kAdditionalClearanceM) {
              check.ok = false;
              std::ostringstream error;
              error << "forearm swept path enters enclosure vertical projection at "
                    << t * 100.0 << "%; clearance=" << swept_clearance * 1000.0
                    << " mm, required >= 30 mm";
              check.reason = error.str();
              break;
            }
          }
        }
      }
    }
    checks.push_back(check);
    if (!check.ok) break;
    previous = ik.joints;
  }
  return checks;
}

int read_motion_test_sequence_pid() {
  std::ifstream in(runtime_file("motion_test_sequence.pid"));
  int pid = 0;
  in >> pid;
  return pid;
}

bool motion_test_sequence_running() {
  return process_running(read_motion_test_sequence_pid());
}

int read_acupoint_sequence_pid() {
  std::ifstream in(runtime_file("acupoint_sequence.pid"));
  int pid = 0;
  in >> pid;
  return pid;
}

bool process_running(int pid) {
  return pid > 0 && kill(pid, 0) == 0;
}

bool acupoint_sequence_running() {
  return process_running(read_acupoint_sequence_pid());
}

std::string shell_quote(const std::string& value) {
  std::string out = "'";
  for (char c : value) {
    if (c == '\'') out += "'\\''";
    else out += c;
  }
  out += "'";
  return out;
}

fs::path latest_analysis_result() {
  const auto data_root = fs::path(root_dir()) / "data";
  fs::path latest;
  fs::file_time_type latest_time{};
  std::error_code error;
  if (!fs::exists(data_root, error)) return {};
  for (fs::recursive_directory_iterator it(data_root, error), end; it != end && !error; it.increment(error)) {
    if (!fs::is_regular_file(it->path(), error) || it->path().filename() != "analysis_result.json") continue;
    const auto modified = fs::last_write_time(it->path(), error);
    if (error) break;
    if (latest.empty() || modified > latest_time) {
      latest = it->path();
      latest_time = modified;
    }
  }
  return latest;
}

void serve_file(httplib::Response& res, const std::string& path) {
  auto content = read_file(path);
  if (content.empty()) {
    res.status = 404;
    res.set_content("not found", "text/plain");
    return;
  }
  std::string type = "text/plain";
  if (ends_with(path, ".html")) type = "text/html; charset=utf-8";
  else if (ends_with(path, ".js")) type = "application/javascript";
  else if (ends_with(path, ".css")) type = "text/css";
  else if (ends_with(path, ".png")) type = "image/png";
  else if (ends_with(path, ".jpg") || ends_with(path, ".jpeg")) type = "image/jpeg";
  res.set_content(content, type);
}
}

int main() {
  try {
    auto* state = open_or_create_shared_state(false);
    const auto collision_config = collision_config_from_environment();
    fs::create_directories(runtime_dir());
    const int port = current_web_port();
    std::string web = root_dir() + "/web";
    httplib::Server server;
    server.set_pre_request_handler(
        [state](const httplib::Request& req, httplib::Response& res) {
          if (req.method != "POST" || req.path.rfind("/api/", 0) != 0) {
            return httplib::Server::HandlerResponse::Unhandled;
          }

          const auto policy = classify_control_post(req.path);
          const auto body = validate_control_body(policy, req.body);
          ControlRequest request;
          request.action = policy.action;
          request.evaluated_at_ms = now_ms();
          request.input_schema_valid = body.schema_valid;
          request.input_finite = body.finite;
          request.has_unknown_fields = body.has_unknown_fields;
          request.has_missing_fields = body.has_missing_fields;
          request.expected_input_units = policy.expected_units;

          if (policy.action == ControlActionKind::EntityControl) {
            request.request_id = req.get_header_value("X-Request-ID");
            request.authorization_id =
                req.get_header_value("X-Authorization-ID");
            request.input_units = req.get_header_value("X-Input-Units");
          } else {
            // Offline/read-only computations use their fixed route schema and
            // never consume entity-authorization headers.
            request.input_units = policy.expected_units;
          }

#ifdef THERAPY_ROBOT_WEB_SIM
          ControlSafetyState safety_state = control_safety_snapshot(*state);
#else
          ControlSafetyState safety_state = control_safety_snapshot(*state);
          // The control web binary can still serve an isolated, explicitly
          // simulated shared state.  This inference can only constrain an
          // offline action; it never promotes entity-control authorization.
          if (std::string(state->run_mode) == "sim" &&
              state->simulation.hardware_mode == 0) {
            safety_state.hardware_mode = "SIMULATION";
          }
#endif

          const auto decision = evaluate_control_safety(
              safety_state, request);
          if (!decision.allowed) {
            state->control_safety.rejected_web_requests++;
            const std::string reason = decision.reasons.empty()
                                           ? "control_request_rejected"
                                           : decision.reasons.front();
            set_text(state->control_safety.last_rejection,
                     sizeof(state->control_safety.last_rejection),
                     reason.c_str());
            res.status = policy.known ? 403 : 404;
            std::ostringstream out;
            out << "{\"ok\":false,\"error\":\"control_safety_gate_rejected\",";
            out << "\"reasons\":" << control_safety_reasons_json(decision) << ',';
            out << "\"execution_allowed\":false,";
            out << "\"entity_action_authorized\":false,";
            out << "\"motor_command_generated\":false,";
            out << "\"motor_target_generated\":false,";
            out << "\"serial_payload_generated\":false}";
            res.set_content(out.str(), "application/json");
            return httplib::Server::HandlerResponse::Handled;
          }

          if (policy.action == ControlActionKind::EntityControl) {
            // Publish only metadata already accepted by the gate.  Trusted
            // authorization id/expiry state is never provisioned from HTTP.
            set_text(state->control_safety.request_id,
                     sizeof(state->control_safety.request_id),
                     request.request_id.c_str());
            set_text(state->control_safety.input_units,
                     sizeof(state->control_safety.input_units),
                     request.input_units.c_str());
            state->control_safety.input_schema_valid = 1;
          }
          return httplib::Server::HandlerResponse::Unhandled;
        });
    server.Get("/api/acupoints/latest", [](const httplib::Request&, httplib::Response& res) {
      const auto result_path = latest_analysis_result();
      const auto content = result_path.empty() ? std::string{} : read_file(result_path);
      if (content.empty()) {
        res.status = 404;
        res.set_content("{\"ok\":false,\"error\":\"analysis_result.json not found\"}", "application/json");
        return;
      }
      res.set_content(content, "application/json");
    });
    server.Get("/api/acupoints/latest/image", [](const httplib::Request&, httplib::Response& res) {
      const auto result_path = latest_analysis_result();
      if (result_path.empty()) {
        res.status = 404;
        res.set_content("not found", "text/plain");
        return;
      }
      const auto image_path = result_path.parent_path() / "rgb.png";
      serve_file(res, image_path.string());
    });
    server.Get("/api/readiness/attestation", [state, collision_config](const httplib::Request&, httplib::Response& res) {
      // This route takes a value snapshot only.  It deliberately does not
      // update the web heartbeat or any command/target field.
      const SharedState snapshot = *state;
      const auto input = readiness_input_snapshot(snapshot, collision_config);
      const auto attestation = issue_readiness_attestation(input, now_ms());
      res.set_content(readiness_attestation_json(attestation), "application/json");
    });
    server.Get("/api/workflow/state", [state, collision_config](const httplib::Request&, httplib::Response& res) {
      const SharedState snapshot = *state;
      const auto facts = workflow_facts_snapshot(snapshot, collision_config);
      const auto assessment = evaluate_workflow(facts);
      res.set_content(workflow_state_json(facts, assessment), "application/json");
    });
    server.Get("/api/workflow/self_check", [state, collision_config](const httplib::Request&, httplib::Response& res) {
      const SharedState snapshot = *state;
      const auto facts = workflow_facts_snapshot(snapshot, collision_config);
      const auto assessment = evaluate_workflow(facts);
      res.set_content(workflow_self_check_json(facts, assessment), "application/json");
    });
    server.Get("/api/motion_plan/preview", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      const SharedState snapshot = *state;
      const auto facts = workflow_facts_snapshot(snapshot, collision_config);
      auto assessment = evaluate_workflow(facts);
      if (req.params.count("side") != 1) {
        res.status = 400;
        res.set_content(
            motion_plan_error_json(facts, std::move(assessment),
                                   "invalid_motion_plan_side"),
            "application/json");
        return;
      }
      try {
        const auto side = parse_motion_plan_side(req.get_param_value("side"));
        const SyntheticRouteParameters parameters(
            {0.0, 0.0, 0.0, 0.0, 0.0}, 0.20, 0.30, 0.10, -0.20, 0.05);
        const auto plan = make_synthetic_motion_plan(
            side, parameters,
            effective_collision_config(snapshot, collision_config));
        res.set_content(
            motion_plan_preview_json(facts, std::move(assessment), plan),
            "application/json");
      } catch (const std::invalid_argument&) {
        res.status = 400;
        res.set_content(
            motion_plan_error_json(facts, std::move(assessment),
                                   "invalid_motion_plan_side"),
            "application/json");
      } catch (const std::exception&) {
        res.status = 500;
        add_motion_plan_blocker(assessment, "motion_plan_preview_failed",
                                "motion_plan.preview", "preview generation failed");
        res.set_content(
            workflow_common_json(assessment, facts.source_state, false,
                                 "motion_plan_preview_failed") + "}",
            "application/json");
      } catch (...) {
        res.status = 500;
        add_motion_plan_blocker(assessment, "motion_plan_preview_failed",
                                "motion_plan.preview", "preview generation failed");
        res.set_content(
            workflow_common_json(assessment, facts.source_state, false,
                                 "motion_plan_preview_failed") + "}",
            "application/json");
      }
    });
    server.Get("/api/state", [state](const httplib::Request&, httplib::Response& res) {
      state->web_heartbeat_ms = now_ms();
      res.set_content(json_state(*state), "application/json");
    });
    server.Post("/api/command/return_arm_zero", [state, collision_config](const httplib::Request&, httplib::Response& res) {
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(readiness_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const JointState current = actual_joints(*state);
      JointState target = current;
      target.k1_rad = 0.0;
      target.k2_rad = 0.0;
      target.k3_rad = 0.0;
      target.k4_rad = 0.0;
      std::array<int64_t, kAxisCount> requested{};
      std::string conversion_error;
      if (!native_targets_from_joints(*state, target, requested,
                                      conversion_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(conversion_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const auto collision = check_robot_motion(current, target,
                                                effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }
      state->command.target_native = requested;
      state->command.target_command_id = 2;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      res.set_content("{\"ok\":true,\"command\":\"return_arm_zero\",\"kept_k0\":true,\"targets\":[0,0,0,0]}", "application/json");
    });
    server.Post("/api/command/return_z_zero", [state, collision_config](const httplib::Request&, httplib::Response& res) {
      if (state->control.collision.manual_recovery) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"K0 return-to-zero is locked during limit-stop recovery\"}", "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(readiness_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const JointState current = actual_joints(*state);
      JointState target = current;
      // Keep a 3 mm stopping clearance above the lower soft-limit boundary.
      // A direct 0 mm target at full K0 speed can cross the boundary before
      // the next feedback cycle and latch a soft-limit emergency stop.
      target.k0_m = 0.003;
      std::array<int64_t, kAxisCount> requested{};
      std::string conversion_error;
      if (!native_targets_from_joints(*state, target, requested,
                                      conversion_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(conversion_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const auto collision = check_robot_motion(current, target,
                                                effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }
      state->command.target_native = requested;
      state->command.target_command_id = 2;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      res.set_content("{\"ok\":true,\"command\":\"return_z_zero\",\"target_k0_mm\":3,\"safe_clearance_mm\":3}", "application/json");
    });
    server.Post("/api/command/targets", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      const char* keys[] = {"g0a0", "g1a0", "g1a1", "g2a0", "g2a1"};
      std::array<int64_t, kAxisCount> requested{};
      for (int i = 0; i < kAxisCount; ++i) {
        requested[i] = static_cast<int64_t>(std::llround(
            extract_number(req.body, keys[i], state->command.target_native[i])));
      }
      const auto collision = check_robot_motion(
          actual_joints(*state), joints_from_native_targets(*state, requested),
          effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }
      state->command.target_native = requested;
      state->command.target_command_id = 1;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      res.set_content("{\"ok\":true,\"command\":\"targets\"}", "application/json");
    });
    server.Post("/api/command/jog_axis", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      const int axis_index = static_cast<int>(std::llround(extract_number(req.body, "axis", -1.0)));
      const double delta_display = extract_number(req.body, "delta_display", 0.0);
      if (axis_index < 0 || axis_index >= kAxisCount) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"axis must be an integer from 0 to 4\"}", "application/json");
        return;
      }
      if (!std::isfinite(delta_display) || std::abs(delta_display) < 1e-12) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"delta_display must be a non-zero finite value\"}", "application/json");
        return;
      }
      const double max_step = axis_index == 0 ? 100.0 : 10.0;
      if (std::abs(delta_display) > max_step) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"single jog step exceeds the per-axis limit (K0 100 mm, K1-K4 10 deg)\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(readiness_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const auto& axis = state->axis_map[axis_index];
      if (!std::isfinite(axis.motor_native_to_gui_display) ||
          std::abs(axis.motor_native_to_gui_display) < 1e-12) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"axis conversion scale is invalid\"}", "application/json");
        return;
      }
      auto requested = actual_native_positions(*state);
      const int64_t start_native = requested[axis_index];
      const int64_t delta_native = static_cast<int64_t>(std::llround(
          delta_display / axis.motor_native_to_gui_display));
      if (delta_native == 0) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"jog step is smaller than one native count\"}", "application/json");
        return;
      }
      const int64_t target_native = start_native + delta_native;
      if (target_native < axis.min_motor_native ||
          target_native > axis.max_motor_native) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"jog target exceeds the configured soft limit\"}", "application/json");
        return;
      }
      requested[axis_index] = target_native;
      const auto collision = check_robot_motion(
          actual_joints(*state), joints_from_native_targets(*state, requested),
          effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }
      state->command.target_native = requested;
      state->command.target_command_id = 1;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      std::ostringstream out;
      out << "{\"ok\":true,\"command\":\"jog_axis\",\"axis\":" << axis_index
          << ",\"name\":\"K" << axis_index << "\",\"unit\":\""
          << escape_json(axis.gui_display_unit) << "\",\"delta_display\":"
          << delta_display << ",\"start_native\":" << start_native
          << ",\"target_native\":" << target_native
          << ",\"start_display\":"
          << start_native * axis.motor_native_to_gui_display
          << ",\"target_display\":"
          << target_native * axis.motor_native_to_gui_display << "}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/command/recovery_jog_axis", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      // This is the only user-selectable motion path while recovery mode is
      // active.  It is intentionally narrower than normal jog: one axis,
      // small increments, and no Cartesian or multi-axis target.
      if (!state->control.collision.manual_recovery) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"请先全部下电并进入限位/碰撞恢复模式\"}", "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"急停仍处于锁存状态，请先复位急停\"}", "application/json");
        return;
      }
      const int axis_index = static_cast<int>(std::llround(extract_number(req.body, "axis", -1.0)));
      const double delta_display = extract_number(req.body, "delta_display", 0.0);
      if (axis_index < 0 || axis_index >= kAxisCount ||
          !std::isfinite(delta_display) || std::abs(delta_display) < 1e-12) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"恢复点动需要有效的 K0-K4 和非零步长\"}", "application/json");
        return;
      }
      const double max_step = axis_index == 0 ? 5.0 : 2.0;
      if (std::abs(delta_display) > max_step) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"恢复点动步长过大（K0最多5mm，K1-K4最多2deg）\"}", "application/json");
        return;
      }
      // In recovery mode the known safe direction for the gravity axis is up.
      // Downward K0 motion could deepen a lower-limit or enclosure collision.
      if (axis_index == 0 && delta_display < 0.0) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"恢复模式禁止K0下降，只允许向上小步脱离限位\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"恢复点动前必须重新使能且全部轴在线：" +
                        escape_json(readiness_error.c_str()) + "\"}", "application/json");
        return;
      }
      const auto& axis = state->axis_map[axis_index];
      if (!std::isfinite(axis.motor_native_to_gui_display) ||
          std::abs(axis.motor_native_to_gui_display) < 1e-12) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"轴换算参数无效\"}", "application/json");
        return;
      }
      auto requested = actual_native_positions(*state);
      const int64_t start_native = requested[axis_index];
      const int64_t delta_native = static_cast<int64_t>(std::llround(
          delta_display / axis.motor_native_to_gui_display));
      if (delta_native == 0) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"恢复点动步长小于一个编码器单位\"}", "application/json");
        return;
      }
      const int64_t target_native = start_native + delta_native;
      if (target_native < axis.min_motor_native ||
          target_native > axis.max_motor_native) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"恢复点动仍超出该轴软限位\"}", "application/json");
        return;
      }
      requested[axis_index] = target_native;
      const auto current_joints = actual_joints(*state);
      const auto target_joints = joints_from_native_targets(*state, requested);
      const auto current_collision = check_robot_configuration(
          current_joints, effective_collision_config(*state, collision_config));
      const auto target_collision = check_robot_configuration(
          target_joints, effective_collision_config(*state, collision_config));
      if (!target_collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"恢复目标姿态仍在碰撞边界内，请换方向或减小步长\"}", "application/json");
        return;
      }
      const bool collision_path_override = !current_collision.ok;
      if (!collision_path_override) {
        const auto path = check_robot_motion(
            current_joints, target_joints,
            effective_collision_config(*state, collision_config));
        if (!path.ok) {
          res.status = 409;
          res.set_content("{\"ok\":false,\"error\":\"恢复路径会进入碰撞边界，请换方向或减小步长\"}", "application/json");
          return;
        }
      }
      state->command.target_native = requested;
      // 7 is consumed only by main_motor while manual_recovery is latched;
      // it marks this target as the deliberately constrained escape path.
      state->command.target_command_id = 7;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      std::ostringstream out;
      out << "{\"ok\":true,\"command\":\"recovery_jog_axis\",\"axis\":"
          << axis_index << ",\"delta_display\":" << delta_display
          << ",\"start_display\":" << start_native * axis.motor_native_to_gui_display
          << ",\"target_display\":" << target_native * axis.motor_native_to_gui_display
          << ",\"collision_path_override\":"
          << (collision_path_override ? "true" : "false") << "}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/command/jog_axis_continuous", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      const int axis_index = static_cast<int>(std::llround(
          extract_number(req.body, "axis", -1.0)));
      const int direction = static_cast<int>(std::llround(
          extract_number(req.body, "direction", 0.0)));
      if (axis_index < 0 || axis_index >= kAxisCount) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"axis must be an integer from 0 to 4\"}", "application/json");
        return;
      }
      if (direction != -1 && direction != 1) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"direction must be -1 or 1\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(readiness_error.c_str()) + "\"}",
                        "application/json");
        return;
      }

      auto requested = actual_native_positions(*state);
      const int64_t start_native = requested[axis_index];
      const auto& axis = state->axis_map[axis_index];
      // K0 has no verified physical upper endpoint at present.  Continuous
      // upward motion therefore receives a bounded 50 mm segment instead of
      // an invented absolute upper limit or an enormous sentinel target.
      const int64_t target_native = axis_index == 0 && direction > 0
          ? start_native + 100 * 14400
          : (direction > 0 ? axis.max_motor_native : axis.min_motor_native);
      if (start_native == target_native) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"selected axis is already at the requested soft limit\"}",
                        "application/json");
        return;
      }
      requested[axis_index] = target_native;
      const auto collision = check_robot_motion(
          actual_joints(*state), joints_from_native_targets(*state, requested),
          effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }

      state->command.target_native = requested;
      // Continuous jog is a single-axis drive command, not a coordinated
      // waypoint trajectory.  main_motor consumes command id 3 only after the
      // soft-limit and collision checks above have accepted the full path.
      state->command.target_command_id = 3;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      std::ostringstream out;
      out << "{\"ok\":true,\"command\":\"jog_axis_continuous\",\"axis\":"
          << axis_index << ",\"name\":\"K" << axis_index
          << "\",\"direction\":" << direction
          << ",\"unit\":\"" << escape_json(axis.gui_display_unit)
          << "\",\"start_native\":" << start_native
          << ",\"target_native\":" << target_native
          << ",\"start_display\":"
          << start_native * axis.motor_native_to_gui_display
          << ",\"soft_limit_display\":"
          << target_native * axis.motor_native_to_gui_display
          << ",\"stop_endpoint\":\"/api/command/stop_all\"}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/command/endpoint_jog", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      if (state->control.collision.manual_recovery) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"endpoint motion is locked until K1-K4 recovery-home completes and the full enclosure/tool collision check is clear\"}", "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      if (std::string(state->run_mode) == "hardware_relative") {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"末端增量已锁定：请先把实体机械臂放到收纳零位并执行软件零位捕获，使仿真与实机一致\"}", "application/json");
        return;
      }
      std::string readiness_error;
      if (!all_axes_ready(*state, readiness_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(readiness_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const std::string axis = extract_string(req.body, "axis");
      const double delta_mm = extract_number(req.body, "delta_mm", 0.0);
      if ((axis != "x" && axis != "y" && axis != "z") ||
          !std::isfinite(delta_mm) || std::abs(delta_mm) < 1e-12 ||
          std::abs(delta_mm) > 50.0) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"axis must be x/y/z and delta_mm must be within +/-50\"}", "application/json");
        return;
      }

      const JointState current_joints = actual_joints(*state);
      const Pose current = forward_kinematics(current_joints);
      Pose target = current;
      const double delta_m = delta_mm / 1000.0;
      if (axis == "x") target.x_m += delta_m;
      if (axis == "y") target.y_m += delta_m;
      if (axis == "z") target.z_m += delta_m;

      const auto ik = inverse_kinematics(target, current_joints);
      if (!ik.ok) {
        std::ostringstream message;
        message << "末端 " << static_cast<char>(std::toupper(axis[0]))
                << (delta_mm > 0.0 ? "+" : "") << delta_mm << " mm 不可达：";
        if (axis == "z") {
          message << "K0只保留0 mm收纳下限，向上最高点尚未重新标定；"
                  << "当前目标仍未通过IK，请检查目标数值和姿态";
        } else {
          message << "当前姿态接近水平工作空间或关节边界；请尝试反方向、减小步长，或调整 K2";
        }
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(message.str().c_str()) +
                        "\",\"ik_reason\":\"" +
                        escape_json(ik.error.c_str()) + "\"}",
                        "application/json");
        return;
      }

      std::array<int64_t, kAxisCount> requested{};
      std::string conversion_error;
      if (!native_targets_from_joints(*state, ik.joints, requested,
                                      conversion_error)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(conversion_error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      const auto collision = check_endpoint_motion(current_joints, ik.joints,
                                                   effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }

      state->command.target_native = requested;
      state->command.target_command_id = 2;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.target_command_seq++;
      std::ostringstream out;
      out << "{\"ok\":true,\"command\":\"endpoint_jog\",\"axis\":\""
          << axis << "\",\"delta_mm\":" << delta_mm
          << ",\"target_pose\":{\"x\":" << target.x_m * 1000.0
          << ",\"y\":" << target.y_m * 1000.0
          << ",\"z\":" << target.z_m * 1000.0
          << ",\"rx\":" << target.rx_rad * 180.0 / 3.14159265358979323846
          << ",\"ry\":" << target.ry_rad * 180.0 / 3.14159265358979323846
          << ",\"rz\":0}}";
      res.set_content(out.str(), "application/json");
    });
    server.Get("/api/collision/model", [collision_config](const httplib::Request&, httplib::Response& res) {
      std::ostringstream out;
      out << "{\"configured\":" << (collision_config.configured ? "true" : "false")
          << ",\"enabled\":" << (collision_config.enabled ? "true" : "false")
          << ",\"required\":" << (collision_config.required ? "true" : "false")
          << ",\"safety_margin_m\":" << collision_config.safety_margin_m
          << ",\"obstacles\":[";
      for (std::size_t i = 0; i < collision_config.obstacles.size(); ++i) {
        const auto& box = collision_config.obstacles[i];
        if (i) out << ',';
        out << "{\"name\":\"" << escape_json(box.name.c_str()) << "\",";
        out << "\"min\":[" << box.min.x_m << ',' << box.min.y_m << ',' << box.min.z_m << "],";
        out << "\"max\":[" << box.max.x_m << ',' << box.max.y_m << ',' << box.max.z_m << "]}";
      }
      out << "]}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/ik/check", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      Pose target;
      target.x_m = extract_number(req.body, "x_m");
      target.y_m = extract_number(req.body, "y_m");
      target.z_m = extract_number(req.body, "z_m");
      target.rx_rad = extract_number(req.body, "rx_rad");
      target.ry_rad = extract_number(req.body, "ry_rad");
      target.rz_rad = extract_number(req.body, "rz_rad");
      const JointState current_joints = actual_joints(*state);
      auto result = inverse_kinematics(target, current_joints);
      CollisionCheck collision;
      if (result.ok) {
        collision = check_endpoint_motion(actual_joints(*state), result.joints,
                                          effective_collision_config(*state, collision_config));
      } else {
        collision.ok = true;
        collision.checked = collision_config.enabled;
        collision.reason = "not checked because IK failed";
      }
      const bool ok = result.ok && collision.ok;
      const std::string reason = result.ok ? collision.reason : result.error;
      std::ostringstream out;
      out << "{\"ok\":" << (ok ? "true" : "false")
          << ",\"ik_ok\":" << (result.ok ? "true" : "false")
          << ",\"collision_checked\":" << (collision.checked ? "true" : "false")
          << ",\"collision_enabled\":" << (collision_config.enabled ? "true" : "false")
          << ",\"reason\":\"" << escape_json(reason.c_str()) << "\""
          << ",\"collision_link\":\"" << escape_json(collision.link_name.c_str()) << "\""
          << ",\"collision_obstacle\":\"" << escape_json(collision.obstacle_name.c_str()) << "\""
          << ",\"path_fraction\":" << collision.path_fraction << "}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/command/endpoint_target", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      if (state->control.collision.manual_recovery) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"endpoint motion is locked until K1-K4 recovery-home completes and the full enclosure/tool collision check is clear\"}", "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      if (std::string(state->run_mode) == "hardware_relative") {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"calibrated axis offsets are required for endpoint motion\"}", "application/json");
        return;
      }
      Pose target;
      target.x_m = extract_number(req.body, "x_m");
      target.y_m = extract_number(req.body, "y_m");
      target.z_m = extract_number(req.body, "z_m");
      target.rx_rad = extract_number(req.body, "rx_rad");
      target.ry_rad = extract_number(req.body, "ry_rad");
      target.rz_rad = extract_number(req.body, "rz_rad");
      const JointState current_joints = actual_joints(*state);
      auto ik = inverse_kinematics(target, current_joints);
      if (!ik.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(ik.error.c_str()) + "\"}",
                        "application/json");
        return;
      }
      auto collision = check_endpoint_motion(current_joints, ik.joints,
                                             effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" +
                        escape_json(collision.reason.c_str()) + "\"}",
                        "application/json");
        return;
      }
      auto& ep = state->control.endpoint_target;
      ep.x_m = target.x_m;
      ep.y_m = target.y_m;
      ep.z_m = target.z_m;
      ep.rx_rad = target.rx_rad;
      ep.ry_rad = target.ry_rad;
      ep.rz_rad = target.rz_rad;
      ep.valid = 1;
      ep.status = 1;
      std::atomic_thread_fence(std::memory_order_release);
      ep.target_seq++;
      set_text(ep.last_error, sizeof(ep.last_error), "pending");
      res.set_content("{\"ok\":true,\"command\":\"endpoint_target\"}", "application/json");
    });
    server.Get("/api/mode", [state](const httplib::Request&, httplib::Response& res) {
      const bool hardware = std::string(state->run_mode) != "sim";
      std::ostringstream out;
      out << "{\"ok\":true,\"mode\":\"" << (hardware ? "hardware" : "sim")
          << "\",\"run_mode\":\"" << escape_json(state->run_mode)
          << "\",\"switching\":false}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/mode/switch", [state](const httplib::Request& req, httplib::Response& res) {
      const std::string target = extract_string(req.body, "mode");
      if (target != "sim" && target != "hardware") {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"mode must be sim or hardware\"}", "application/json");
        return;
      }
      const bool currently_hardware = std::string(state->run_mode) != "sim";
      const bool target_hardware = target == "hardware";
      if (currently_hardware == target_hardware) {
        std::ostringstream out;
        out << "{\"ok\":true,\"changed\":false,\"mode\":\"" << target << "\"}";
        res.set_content(out.str(), "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"急停已锁存，请先复位急停\"}", "application/json");
        return;
      }
      std::string disabled_reason;
      if (!all_motors_disabled(*state, disabled_reason)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"切换模式前必须全部电机下电：" +
                        escape_json(disabled_reason.c_str()) + "\"}", "application/json");
        return;
      }
      if (state->control.collision.manual_recovery ||
          acupoint_sequence_running() || motion_test_sequence_running()) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"请先停止自动序列并退出碰撞恢复，再切换全局模式\"}", "application/json");
        return;
      }
      const std::string script = root_dir() + "/scripts/switch-run-mode.sh";
      const std::string log_path = runtime_file("mode_switch_request.log");
      const std::string command = "mkdir -p " + shell_quote(runtime_dir()) + "; nohup " + shell_quote(script) +
                                  " " + shell_quote(target) +
                                  " >" + shell_quote(log_path) + " 2>&1 </dev/null &";
      const int rc = std::system(command.c_str());
      if (rc != 0) {
        res.status = 500;
        res.set_content("{\"ok\":false,\"error\":\"无法启动模式切换进程\"}", "application/json");
        return;
      }
      std::ostringstream out;
      out << "{\"ok\":true,\"changed\":true,\"pending\":true,\"target_mode\":\""
          << target << "\",\"message\":\"模式切换已启动；服务将短暂断开并按目标模式重启\"}";
      res.set_content(out.str(), "application/json");
    });
    server.Get("/api/motion_test/points", [](const httplib::Request& req, httplib::Response& res) {
      const std::string side = req.has_param("side") && req.get_param_value("side") == "left"
                                   ? "left" : "right";
      std::ostringstream out;
      out << "{\"ok\":true,\"side\":\"" << side << "\",\"points\":[";
      const auto points = motion_test_points(side);
      for (std::size_t i = 0; i < points.size(); ++i) {
        if (i) out << ',';
        const auto& point = points[i];
        out << "{\"index\":" << point.index
            << ",\"name\":\"" << escape_json(point.name)
            << "\",\"description\":\"" << escape_json(point.description)
            << "\",\"x_mm\":" << point.x_mm
            << ",\"y_mm\":" << point.y_mm
            << ",\"z_mm\":" << point.z_mm
            << ",\"rx_deg\":0,\"ry_deg\":0}";
      }
      out << "]}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/motion_test/simulate", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
      const std::string side = extract_string(req.body, "side") == "left" ? "left" : "right";
      bool all_ok = true;
      std::ostringstream out;
      out << "{\"simulation_only\":true,\"start_pose\":\"actual_joint_feedback\","
          << "\"side\":\"" << side << "\",\"points\":[";
      const auto points = motion_test_points(side);
      const auto checks = check_motion_test_path(*state, collision_config, points);
      for (std::size_t i = 0; i < checks.size(); ++i) {
        if (i) out << ',';
        const auto& point = points[i];
        const auto& check = checks[i];
        const bool point_ok = check.ok;
        double position_error_mm = 0.0;
        if (point_ok) {
          const Pose achieved = forward_kinematics(check.joints);
          position_error_mm = 1000.0 * std::hypot(
              std::hypot(achieved.x_m - point.x_mm / 1000.0,
                         achieved.y_m - point.y_mm / 1000.0),
              achieved.z_m - point.z_mm / 1000.0);
        }
        all_ok = all_ok && point_ok;
        constexpr double kRadToDeg = 180.0 / 3.14159265358979323846;
        out << "{\"index\":" << point.index
            << ",\"name\":\"" << escape_json(point.name)
            << "\",\"ok\":" << (point_ok ? "true" : "false")
            << ",\"reason\":\"" << escape_json(check.reason.c_str())
            << "\",\"collision_link\":\"" << escape_json(check.collision.link_name.c_str())
            << "\",\"collision_obstacle\":\"" << escape_json(check.collision.obstacle_name.c_str())
            << "\",\"path_fraction\":" << check.collision.path_fraction
            << ",\"position_error_mm\":" << position_error_mm
            << ",\"joints\":{\"k0_mm\":" << check.joints.k0_m * 1000.0
            << ",\"k1_deg\":" << check.joints.k1_rad * kRadToDeg
            << ",\"k2_deg\":" << check.joints.k2_rad * kRadToDeg
            << ",\"k3_deg\":" << check.joints.k3_rad * kRadToDeg
            << ",\"k4_deg\":" << check.joints.k4_rad * kRadToDeg << '}';
        out << '}';
        if (!point_ok) break;
      }
      out << "],\"result\":\"" << (all_ok ? "all_points_passed" : "failed")
          << "\",\"path_order\":\"high_deploy_then_vertical_lower_then_y_scan_then_reverse_return\","
          << "\"execution_allowed\":false,"
          << "\"entity_action_authorized\":false,"
          << "\"motor_command_generated\":false,"
          << "\"motor_target_generated\":false,"
          << "\"serial_payload_generated\":false,"
          << "\"motor_command_written\":false,\"ok\":"
          << (all_ok ? "true" : "false") << '}';
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/motion_test/point", [state, collision_config](const httplib::Request& req, httplib::Response& res) {
#ifdef THERAPY_ROBOT_WEB_SIM
      // A low work point is intentionally not reachable by one direct command:
      // it must be entered through the high-plane deployment and exterior
      // descent corridor.  The simulation UI plays that complete safe route.
      res.status = 409;
      res.set_content("{\"ok\":false,\"simulation_only\":true,\"error\":\"simulation build: selected test points are preview-only; use the full trajectory preview\"}",
                      "application/json");
      return;
#endif
      if (state->control.collision.manual_recovery) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"碰撞恢复未完成，测试点控制已锁定\"}", "application/json");
        return;
      }
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"emergency stop is latched\"}", "application/json");
        return;
      }
      if (std::string(state->run_mode) == "hardware_relative") {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"当前为硬件相对模式，先完成软件零位捕获\"}", "application/json");
        return;
      }
      const std::string side = extract_string(req.body, "side") == "left" ? "left" : "right";
      const auto points = motion_test_points(side);
      const int requested_index = static_cast<int>(std::llround(extract_number(req.body, "index", 0.0)));
      const std::string requested_name = extract_string(req.body, "name");
      const MotionTestPoint* selected = nullptr;
      for (const auto& point : points) {
        if ((requested_index > 0 && point.index == requested_index) ||
            (!requested_name.empty() && requested_name == point.name)) {
          selected = &point;
          break;
        }
      }
      if (!selected) {
        res.status = 400;
        res.set_content("{\"ok\":false,\"error\":\"测试点编号或名称无效，请先读取 /api/motion_test/points\"}", "application/json");
        return;
      }
      Pose target;
      target.x_m = selected->x_mm / 1000.0;
      target.y_m = selected->y_mm / 1000.0;
      target.z_m = selected->z_mm / 1000.0;
      target.rx_rad = 0.0;
      target.ry_rad = 0.0;
      target.rz_rad = 0.0;
      const JointState current_joints = actual_joints(*state);
      const auto ik = inverse_kinematics(target, current_joints);
      if (!ik.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" + escape_json(ik.error.c_str()) + "\"}", "application/json");
        return;
      }
      const auto collision = check_endpoint_motion(current_joints, ik.joints,
                                                   effective_collision_config(*state, collision_config));
      if (!collision.ok) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"" + escape_json(collision.reason.c_str()) + "\"}", "application/json");
        return;
      }
      auto& ep = state->control.endpoint_target;
      ep.x_m = target.x_m;
      ep.y_m = target.y_m;
      ep.z_m = target.z_m;
      ep.rx_rad = target.rx_rad;
      ep.ry_rad = target.ry_rad;
      ep.rz_rad = target.rz_rad;
      ep.valid = 1;
      ep.status = 1;
      ep.target_seq++;
      set_text(ep.last_error, sizeof(ep.last_error), "pending");
      std::ostringstream out;
      out << "{\"ok\":true,\"command\":\"motion_test_point\",\"index\":" << selected->index
          << ",\"name\":\"" << escape_json(selected->name)
          << "\",\"target_pose\":{\"x\":" << selected->x_mm
          << ",\"y\":" << selected->y_mm << ",\"z\":" << selected->z_mm
          << ",\"rx\":0,\"ry\":0,\"rz\":0}}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/motion_test/sequence/start", [](const httplib::Request&, httplib::Response& res) {
      res.status = 409;
      res.set_content(
          "{\"ok\":false,\"execution_locked\":true,"
          "\"error_code\":\"automatic_trajectory_locked\","
          "\"error\":\"完整自动轨迹尚未完成安全复核，当前仅允许只读仿真预检\","
          "\"motor_command_written\":false,\"motion_started\":false}",
          "application/json");
    });
    server.Post("/api/motion_test/sequence/stop", [state](const httplib::Request&, httplib::Response& res) {
      const int pid = read_motion_test_sequence_pid();
      if (process_running(pid)) kill(pid, SIGTERM);
      const std::string pid_file = runtime_file("motion_test_sequence.pid");
      std::remove(pid_file.c_str());
      state->command.command_id = 4;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.command_seq++;
      res.set_content("{\"ok\":true,\"running\":false}", "application/json");
    });
    server.Get("/api/motion_test/sequence/status", [](const httplib::Request&, httplib::Response& res) {
      const std::string log = read_file(runtime_file("motion_test_sequence.log"));
      const std::string progress = read_file(runtime_file("motion_test_progress.json"));
      std::ostringstream out;
      out << "{\"ok\":true,\"execution_locked\":true,"
          << "\"error_code\":\"automatic_trajectory_locked\","
          << "\"lock_reason\":\"完整自动轨迹尚未完成安全复核，当前仅允许只读仿真预检\","
          << "\"motor_command_written\":false,\"motion_started\":false,\"running\":"
          << (motion_test_sequence_running() ? "true" : "false")
          << ",\"log_tail\":\"" << escape_json(tail_text(log, 3000).c_str())
          << "\",\"progress\":" << (progress.empty() ? "null" : progress) << "}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/acupoint_sequence/start", [](const httplib::Request&, httplib::Response& res) {
      res.status = 409;
      res.set_content(
          "{\"ok\":false,\"execution_locked\":true,"
          "\"error_code\":\"automatic_trajectory_locked\","
          "\"error\":\"完整自动轨迹尚未完成安全复核，当前仅允许只读仿真预检\","
          "\"motor_command_written\":false,\"motion_started\":false}",
          "application/json");
    });
    server.Post("/api/speed", [state](const httplib::Request& req, httplib::Response& res) {
      const double multiplier = std::clamp(extract_number(req.body, "multiplier", 0.65), 0.25, 1.0);
      write_speed_multiplier(multiplier);
      std::ostringstream out;
      out << "{\"ok\":true,\"multiplier\":" << multiplier
          << ",\"mode\":\"" << (std::string(state->run_mode) == "sim" ? "sim" : "hardware")
          << "\",\"offline_simulation\":true"
          << ",\"execution_allowed\":false"
          << ",\"entity_action_authorized\":false"
          << ",\"motor_command_generated\":false"
          << ",\"motor_target_generated\":false"
          << ",\"serial_payload_generated\":false}";
      res.set_content(out.str(), "application/json");
    });
    server.Post("/api/acupoint_sequence/stop", [](const httplib::Request&, httplib::Response& res) {
      int pid = read_acupoint_sequence_pid();
      if (process_running(pid)) {
        kill(pid, SIGTERM);
      }
      const std::string pid_file = runtime_file("acupoint_sequence.pid");
      std::remove(pid_file.c_str());
      res.set_content("{\"ok\":true,\"running\":false}", "application/json");
    });
    server.Get("/api/acupoint_sequence/status", [](const httplib::Request&, httplib::Response& res) {
      const std::string log_path = runtime_file("acupoint_sequence.log");
      std::string log = read_file(log_path);
      std::string progress = read_file(runtime_file("acupoint_sequence_progress.json"));
      std::ostringstream out;
      out << "{\"ok\":true,\"running\":" << (acupoint_sequence_running() ? "true" : "false")
          << ",\"log\":\"" << escape_json(log_path.c_str()) << "\",\"log_tail\":\"" << escape_json(tail_text(log, 4000).c_str())
          << "\",\"progress\":" << (progress.empty() ? "null" : progress) << "}";
      res.set_content(out.str(), "application/json");
    });
    auto simple = [state](int cmd) {
      state->command.command_id = cmd;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.command_seq++;
    };
    server.Post("/api/command/enable_all", [&](const httplib::Request&, httplib::Response& res) {
      if (state->emergency_stop) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"reset emergency stop before enabling\"}", "application/json");
        return;
      }
      simple(2);
      res.set_content("{\"ok\":true,\"pending\":true}", "application/json");
    });
    server.Post("/api/command/recover_arm_zero", [&](const httplib::Request&, httplib::Response& res) {
      state->command.command_id = 6;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.command_seq++;
      res.set_content("{\"ok\":true,\"pending\":true,\"message\":\"K1-K4 recovery return-to-zero; K0 holds current height\"}", "application/json");
    });
    server.Post("/api/command/disable_all", [&](const httplib::Request&, httplib::Response& res) { simple(3); res.set_content("{\"ok\":true}", "application/json"); });
    server.Post("/api/command/stop_all", [&](const httplib::Request&, httplib::Response& res) { simple(4); res.set_content("{\"ok\":true}", "application/json"); });
    server.Post("/api/command/set_zero", [&](const httplib::Request&, httplib::Response& res) { simple(5); res.set_content("{\"ok\":true}", "application/json"); });
    server.Post("/api/command/emergency_stop", [&](const httplib::Request&, httplib::Response& res) {
      state->emergency_stop = 1;
      simple(4);
      res.set_content("{\"ok\":true,\"emergency_stop\":true}", "application/json");
    });
    server.Post("/api/command/reset_emergency_stop", [&](const httplib::Request&, httplib::Response& res) {
      for (const auto& group : state->groups) {
        for (int slot = 0; slot < group.motor_count; ++slot) {
          if (group.motors[slot].enabled) {
            res.status = 409;
            res.set_content("{\"ok\":false,\"error\":\"all motors must be disabled before reset\"}", "application/json");
            return;
          }
        }
      }
      state->emergency_stop = 0;
      set_text(state->system_state, sizeof(state->system_state), "hardware_ready");
      res.set_content("{\"ok\":true,\"emergency_stop\":false}", "application/json");
    });
    server.Post("/api/command/clear_faults", [&](const httplib::Request&, httplib::Response& res) {
      std::string disabled_reason;
      if (!all_motors_disabled(*state, disabled_reason)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"清零前必须全部下电：" +
                        escape_json(disabled_reason.c_str()) + "\"}", "application/json");
        return;
      }
      const int pid = read_motion_test_sequence_pid();
      if (process_running(pid)) kill(pid, SIGTERM);
      const std::string pid_file = runtime_file("motion_test_sequence.pid");
      std::remove(pid_file.c_str());
      state->command.command_id = 4;
      state->command.command_seq++;
      state->emergency_stop = 0;
      state->control.limit_alarm = 0;
      state->control.collision.alarm = 0;
      state->control.collision.manual_recovery = 0;
      state->control.collision.recovery_arm_zero_active = 0;
      for (int group = 0; group < kGroupCount; ++group) {
        state->groups[group].hardware_enabled = 0;
        set_text(state->groups[group].last_error, sizeof(state->groups[group].last_error), "");
        for (int slot = 0; slot < state->groups[group].motor_count; ++slot)
          state->groups[group].motors[slot].fault = 0;
      }
      set_text(state->system_state, sizeof(state->system_state), "hardware_ready");
      res.set_content("{\"ok\":true,\"message\":\"软件急停、软限位和序列锁定已清除；电机保持下电，不会自动运动\"}", "application/json");
    });
    server.Post("/api/reconcile/apply", [&](const httplib::Request& req, httplib::Response& res) {
      std::string disabled_reason;
      if (!all_motors_disabled(*state, disabled_reason)) {
        res.status = 409;
        res.set_content("{\"ok\":false,\"error\":\"all motors must be disabled before pose reconciliation: " +
                        escape_json(disabled_reason.c_str()) + "\"}", "application/json");
        return;
      }
      JointState confirmed{
          extract_number(req.body, "k0_mm", 0.0) / 1000.0,
          extract_number(req.body, "k1_deg", 0.0) * 3.14159265358979323846 / 180.0,
          extract_number(req.body, "k2_deg", 0.0) * 3.14159265358979323846 / 180.0,
          extract_number(req.body, "k3_deg", 0.0) * 3.14159265358979323846 / 180.0,
          extract_number(req.body, "k4_deg", 0.0) * 3.14159265358979323846 / 180.0};
      std::array<int64_t, kAxisCount> requested{};
      std::string reason;
      if (!native_targets_from_joints(*state, confirmed, requested, reason)) {
        res.status = 422;
        res.set_content("{\"ok\":false,\"error\":\"" + escape_json(reason.c_str()) + "\"}", "application/json");
        return;
      }
      for (int idx = 0; idx < kAxisCount; ++idx) state->command.target_native[idx] = requested[idx];
      state->command.command_id = 8;
      std::atomic_thread_fence(std::memory_order_release);
      state->command.command_seq++;
      res.set_content("{\"ok\":true,\"pending\":true,\"motor_command_written\":false,\"motion_started\":false,\"message\":\"pose confirmation queued; software offsets only, motors remain disabled\"}", "application/json");
    });
    server.Post("/api/command/enable_limit_stop_recovery", [&](const httplib::Request&, httplib::Response& res) {
      for (const auto& group : state->groups) {
        for (int slot = 0; slot < group.motor_count; ++slot) {
          if (group.motors[slot].enabled) {
            res.status = 409;
            res.set_content("{\"ok\":false,\"error\":\"disable all motors before enabling limit-stop recovery\"}", "application/json");
            return;
          }
        }
      }
      state->control.collision.manual_recovery = 1;
      state->control.collision.alarm = 0;
      state->control.limit_alarm = 0;
      state->emergency_stop = 0;
      set_text(state->system_state, sizeof(state->system_state), "limit_stop_recovery_ready");
      res.set_content("{\"ok\":true,\"manual_recovery\":true,\"message\":\"forearm stop ignored; enclosure remains active; K0 down/return and endpoint motion locked\"}", "application/json");
    });
    server.Post("/api/command/disable_limit_stop_recovery", [&](const httplib::Request&, httplib::Response& res) {
      state->control.collision.manual_recovery = 0;
      res.set_content("{\"ok\":true,\"manual_recovery\":false}", "application/json");
    });
    server.Get("/control", [&](const httplib::Request&, httplib::Response& res) { serve_file(res, web + "/control.html"); });
    server.Get("/sim", [&](const httplib::Request&, httplib::Response& res) { serve_file(res, web + "/sim.html"); });
    server.Get(R"(/(.*))", [&](const httplib::Request& req, httplib::Response& res) {
      std::string path = req.matches[1];
      if (path.empty()) path = "control.html";
      serve_file(res, web + "/" + path);
    });
    std::cout << "web listening on " << port << '\n';
    server.listen("0.0.0.0", port);
  } catch (const std::exception& e) {
    std::cerr << "main_web: " << e.what() << '\n';
    return 1;
  }
}
