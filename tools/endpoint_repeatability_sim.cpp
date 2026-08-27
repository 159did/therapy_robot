#include "therapy_robot/collision.hpp"
#include "therapy_robot/endpoint_positioning.hpp"
#include "therapy_robot/kinematics.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

using therapy_robot::EndpointPositioningMeasurement;
using therapy_robot::EndpointPositioningResult;
using therapy_robot::JointState;
using therapy_robot::Pose;

constexpr double kPi = 3.14159265358979323846;
constexpr std::array<const char*, 7> kPointHeaderFields{
    "point_id", "target_x_m", "target_y_m", "target_z_m",
    "target_rx_rad", "target_ry_rad", "target_rz_rad"};

struct InputError : std::runtime_error {
  using std::runtime_error::runtime_error;
};

struct Point {
  std::string id;
  Pose target{};
};

struct Options {
  std::string points_path;
  std::string collision_path;
  std::string json_path;
  std::string csv_path;
  double retreat_radius_m = 0.015;
  std::uint32_t random_seed = 20260827U;
  int random_candidate_attempts = 36;
  int repetitions = 3;
  int move_timeout_ms = 2000;
  int settle_timeout_ms = 500;
  std::string feedback_loss_at;
};

struct Event {
  std::string state;
  std::string point_id;
  int repetition = 0;
  std::string detail;
};

struct Sample {
  std::string point_id;
  int repetition = 0;
  std::string arrival_type;
  Pose target{};
  JointState actual_joints{};
  EndpointPositioningResult evaluation{};
  int move_duration_ms = 0;
  int settle_duration_ms = 0;
  bool feedback_valid = false;
  bool retreat_completed = false;
  std::uint32_t random_seed = 0;
  int random_candidate_attempt = 0;
  double random_angle_rad = 0.0;
  double retreat_radius_m = 0.0;
  Pose retreat_pose{};
  int retreat_move_duration_ms = 0;
  bool retreat_ik_passed = false;
  bool retreat_limit_passed = false;
  bool retreat_collision_passed = false;
  bool retreat_path_passed = false;
  bool return_path_passed = false;
};

struct RunResult {
  bool passed = false;
  std::string status = "FAIL";
  std::string final_state = "STOPPED";
  std::string failure_reason;
  bool safe_start_returned = false;
  int total_move_duration_ms = 0;
  std::vector<Event> events;
  std::vector<Sample> samples;
};

class DeterministicRandom {
 public:
  explicit DeterministicRandom(std::uint32_t seed)
      : state_(seed == 0U ? 0x6d2b79f5U : seed) {}

  double next_angle_rad() {
    // Xorshift32 is used instead of a platform library distribution so a
    // recorded seed reproduces exactly the same retreat points.
    std::uint32_t value = state_;
    value ^= value << 13U;
    value ^= value >> 17U;
    value ^= value << 5U;
    state_ = value;
    const double unit = static_cast<double>(value) / 4294967296.0;
    return 2.0 * kPi * unit;
  }

 private:
  std::uint32_t state_;
};

std::string trim_field(const std::string& value) {
  const auto first = value.find_first_not_of(" \t");
  if (first == std::string::npos) return {};
  const auto last = value.find_last_not_of(" \t");
  return value.substr(first, last - first + 1);
}

void remove_trailing_carriage_return(std::string& line) {
  if (!line.empty() && line.back() == '\r') line.pop_back();
}

void remove_utf8_bom(std::string& line) {
  constexpr char kUtf8Bom[] = "\xEF\xBB\xBF";
  if (line.compare(0, 3, kUtf8Bom) == 0) line.erase(0, 3);
}

std::vector<std::string> split_csv(const std::string& line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) fields.push_back(trim_field(field));
  return fields;
}

double parse_number(const std::string& text, const std::string& field,
                    std::size_t row) {
  std::size_t consumed = 0;
  double value = 0.0;
  try {
    value = std::stod(text, &consumed);
  } catch (const std::exception&) {
    throw InputError("row " + std::to_string(row) + ": invalid " + field);
  }
  if (consumed != text.size() || !std::isfinite(value)) {
    throw InputError("row " + std::to_string(row) + ": invalid " + field);
  }
  return value;
}

int parse_positive_int(const std::string& text, const std::string& field) {
  std::size_t consumed = 0;
  long value = 0;
  try {
    value = std::stol(text, &consumed);
  } catch (const std::exception&) {
    throw InputError(field + " must be a positive integer");
  }
  if (consumed != text.size() || value <= 0 || value > 600000) {
    throw InputError(field + " must be a positive integer");
  }
  return static_cast<int>(value);
}

int parse_repetitions(const std::string& text) {
  if (text.empty() ||
      !std::all_of(text.begin(), text.end(),
                   [](unsigned char character) {
                     return character >= '0' && character <= '9';
                   })) {
    throw InputError("repetitions must be a decimal integer from 1 to 100");
  }
  std::size_t consumed = 0;
  unsigned long value = 0;
  try {
    value = std::stoul(text, &consumed, 10);
  } catch (const std::exception&) {
    throw InputError("repetitions must be a decimal integer from 1 to 100");
  }
  if (consumed != text.size() || value < 1UL || value > 100UL) {
    throw InputError("repetitions must be a decimal integer from 1 to 100");
  }
  return static_cast<int>(value);
}

std::uint32_t parse_seed(const std::string& text) {
  std::size_t consumed = 0;
  unsigned long value = 0;
  try {
    value = std::stoul(text, &consumed);
  } catch (const std::exception&) {
    throw InputError("random-seed must be an unsigned 32-bit integer");
  }
  if (consumed != text.size() || value > 0xffffffffUL) {
    throw InputError("random-seed must be an unsigned 32-bit integer");
  }
  return static_cast<std::uint32_t>(value);
}

std::vector<Point> read_points(const std::string& path) {
  std::ifstream input(path);
  if (!input) throw InputError("cannot open points CSV: " + path);
  std::string line;
  if (!std::getline(input, line)) {
    throw InputError("points CSV header does not match required schema");
  }
  remove_trailing_carriage_return(line);
  remove_utf8_bom(line);
  const auto header_fields = split_csv(line);
  if (header_fields.size() != kPointHeaderFields.size() ||
      !std::equal(header_fields.begin(), header_fields.end(),
                  kPointHeaderFields.begin())) {
    throw InputError("points CSV header does not match required schema");
  }
  std::vector<Point> points;
  std::map<std::string, bool> ids;
  std::size_t row = 1;
  while (std::getline(input, line)) {
    ++row;
    remove_trailing_carriage_return(line);
    if (trim_field(line).empty()) continue;
    const auto fields = split_csv(line);
    if (fields.size() != 7 || fields[0].empty()) {
      throw InputError("row " + std::to_string(row) +
                       ": expected point_id and six pose values");
    }
    if (ids.count(fields[0]) != 0) {
      throw InputError("row " + std::to_string(row) + ": duplicate point_id");
    }
    ids[fields[0]] = true;
    points.push_back({fields[0],
                      {parse_number(fields[1], "target_x_m", row),
                       parse_number(fields[2], "target_y_m", row),
                       parse_number(fields[3], "target_z_m", row),
                       parse_number(fields[4], "target_rx_rad", row),
                       parse_number(fields[5], "target_ry_rad", row),
                       parse_number(fields[6], "target_rz_rad", row)}});
  }
  if (points.empty()) throw InputError("points CSV contains no points");
  return points;
}

std::string json_string(const std::string& value) {
  std::ostringstream escaped;
  for (const char character : value) {
    switch (character) {
      case '\\': escaped << "\\\\"; break;
      case '"': escaped << "\\\""; break;
      case '\n': escaped << "\\n"; break;
      case '\r': escaped << "\\r"; break;
      case '\t': escaped << "\\t"; break;
      default: escaped << character; break;
    }
  }
  return escaped.str();
}

double max_joint_fraction(const JointState& source, const JointState& target) {
  return std::max({std::abs(target.k0_m - source.k0_m) / 0.33,
                   std::abs(target.k1_rad - source.k1_rad) / 1.57,
                   std::abs(target.k2_rad - source.k2_rad) / 1.57,
                   std::abs(target.k3_rad - source.k3_rad) / 0.79,
                   std::abs(target.k4_rad - source.k4_rad) / 1.05});
}

int simulated_move_duration_ms(const JointState& source,
                               const JointState& target) {
  return 100 + static_cast<int>(std::ceil(300.0 * max_joint_fraction(source, target)));
}

JointState simulated_feedback(const JointState& nominal, int repetition) {
  // Deterministic mock encoder offsets make repeatability measurable without
  // random data or any hardware access.
  constexpr std::array<double, 3> kLiftOffsets{
      0.00010, -0.00005, 0.00015};
  constexpr std::array<double, 3> kJointOffsets{
      0.00002, -0.00001, 0.00003};
  const std::size_t pattern_index =
      static_cast<std::size_t>(repetition - 1) % kLiftOffsets.size();
  JointState feedback = nominal;
  feedback.k0_m += kLiftOffsets[pattern_index];
  feedback.k1_rad += kJointOffsets[pattern_index];
  return feedback;
}

bool feedback_loss_matches(const std::string& specification,
                           const std::string& point_id, int repetition) {
  if (specification.empty()) return false;
  return specification == point_id + ":" + std::to_string(repetition);
}

void add_event(RunResult& result, const std::string& state,
               const std::string& point_id, int repetition,
               const std::string& detail) {
  result.events.push_back({state, point_id, repetition, detail});
}

bool fail(RunResult& result, const std::string& reason,
          const std::string& point_id, int repetition) {
  result.status = "FAIL";
  result.final_state = "STOPPED";
  result.failure_reason = reason;
  add_event(result, "STOPPED", point_id, repetition, reason);
  return false;
}

bool simulate_move(RunResult& result, const JointState& source,
                   const JointState& target, int timeout_ms,
                   const std::string& state, const std::string& point_id,
                   int repetition, int& duration_ms) {
  add_event(result, state, point_id, repetition, "mock_move_started");
  duration_ms = simulated_move_duration_ms(source, target);
  result.total_move_duration_ms += duration_ms;
  if (duration_ms > timeout_ms) {
    return fail(result, "move_timeout", point_id, repetition);
  }
  add_event(result, state, point_id, repetition, "mock_move_completed");
  return true;
}

RunResult run_simulation(const std::vector<Point>& points,
                         const therapy_robot::CollisionConfig& collision,
                         const Options& options) {
  RunResult run;
  therapy_robot::SharedState limits;
  therapy_robot::initialize_defaults(limits);
  const auto tolerance = therapy_robot::default_endpoint_positioning_tolerance();
  // This is a synthetic software start state, not a formal entity SAFE_HIGH.
  const JointState simulated_safe_start{0.3131, 0.0, 0.0, 0.0, 0.0};
  const Pose simulated_safe_pose = therapy_robot::forward_kinematics(simulated_safe_start);
  JointState current = simulated_safe_start;
  DeterministicRandom random(options.random_seed);
  add_event(run, "READY", "", 0, "simulated_safe_start_ready");

  for (const auto& point : points) {
    for (int repetition = 1; repetition <= options.repetitions; ++repetition) {
      const JointState approach_source = current;
      const auto preflight = therapy_robot::preflight_endpoint_positioning(
          approach_source, point.target, limits, collision);
      if (!preflight.ok) {
        fail(run, "target_preflight_rejected:" + preflight.reason,
             point.id, repetition);
        return run;
      }

      int move_duration_ms = 0;
      if (!simulate_move(run, approach_source, preflight.target_joints,
                         options.move_timeout_ms, "MOVING_TO_TARGET",
                         point.id, repetition, move_duration_ms)) {
        return run;
      }
      add_event(run, "WAITING_TARGET_SETTLE", point.id, repetition,
                "mock_settle_started");
      constexpr int kSettleDurationMs = 60;
      if (kSettleDurationMs > options.settle_timeout_ms) {
        fail(run, "settle_timeout", point.id, repetition);
        return run;
      }
      add_event(run, "WAITING_TARGET_SETTLE", point.id, repetition,
                "mock_settle_completed");
      add_event(run, "CAPTURING_FEEDBACK", point.id, repetition,
                "mock_feedback_requested");
      if (feedback_loss_matches(options.feedback_loss_at, point.id, repetition)) {
        fail(run, "feedback_lost", point.id, repetition);
        return run;
      }

      Sample sample;
      sample.point_id = point.id;
      sample.repetition = repetition;
      sample.arrival_type = repetition == 1 ? "INITIAL_APPROACH" : "RETURN_AFTER_RETREAT";
      sample.target = point.target;
      sample.actual_joints = simulated_feedback(preflight.target_joints, repetition);
      sample.move_duration_ms = move_duration_ms;
      sample.settle_duration_ms = kSettleDurationMs;
      sample.feedback_valid = true;
      EndpointPositioningMeasurement measurement;
      measurement.sample_id = point.id + "-" + std::to_string(repetition);
      measurement.side = point.id;
      measurement.source = approach_source;
      measurement.target = point.target;
      measurement.actual = sample.actual_joints;
      sample.evaluation = therapy_robot::evaluate_endpoint_positioning_measurement(
          measurement, limits, collision, therapy_robot::default_geometry(), tolerance);
      run.samples.push_back(sample);
      if (!run.samples.back().evaluation.accepted) {
        fail(run, "feedback_rejected:" + run.samples.back().evaluation.reason,
             point.id, repetition);
        return run;
      }
      add_event(run, "CAPTURING_FEEDBACK", point.id, repetition,
                "mock_feedback_captured");

      // After every measurement choose a point on the BASE_XY circle around
      // the target. Randomness selects only a candidate direction; both the
      // target-to-retreat and retreat-to-target paths must pass the existing
      // IK, formal soft-limit and required collision checks.
      therapy_robot::EndpointPositioningPreflight retreat;
      Pose retreat_pose{};
      double retreat_angle_rad = 0.0;
      int accepted_attempt = 0;
      for (int attempt = 1; attempt <= options.random_candidate_attempts; ++attempt) {
        const double angle = random.next_angle_rad();
        Pose candidate = point.target;
        candidate.x_m += options.retreat_radius_m * std::cos(angle);
        candidate.y_m += options.retreat_radius_m * std::sin(angle);
        const auto outward = therapy_robot::preflight_endpoint_positioning(
            sample.actual_joints, candidate, limits, collision);
        if (!outward.ok) {
          add_event(run, "SELECTING_RANDOM_RETREAT", point.id, repetition,
                    "candidate_rejected_outward:" + outward.reason);
          continue;
        }
        const auto inward = therapy_robot::preflight_endpoint_positioning(
            outward.target_joints, point.target, limits, collision);
        if (!inward.ok) {
          add_event(run, "SELECTING_RANDOM_RETREAT", point.id, repetition,
                    "candidate_rejected_return:" + inward.reason);
          continue;
        }
        retreat = outward;
        retreat_pose = candidate;
        retreat_angle_rad = angle;
        accepted_attempt = attempt;
        break;
      }
      if (accepted_attempt == 0) {
        fail(run, "no_safe_random_retreat_point", point.id, repetition);
        return run;
      }
      add_event(run, "SELECTING_RANDOM_RETREAT", point.id, repetition,
                "safe_candidate_selected");
      run.samples.back().random_seed = options.random_seed;
      run.samples.back().random_candidate_attempt = accepted_attempt;
      run.samples.back().random_angle_rad = retreat_angle_rad;
      run.samples.back().retreat_radius_m = options.retreat_radius_m;
      run.samples.back().retreat_pose = retreat_pose;
      run.samples.back().retreat_ik_passed = true;
      run.samples.back().retreat_limit_passed = true;
      run.samples.back().retreat_collision_passed = true;
      run.samples.back().retreat_path_passed = true;
      run.samples.back().return_path_passed = true;
      int retreat_duration_ms = 0;
      if (!simulate_move(run, sample.actual_joints, retreat.target_joints,
                         options.move_timeout_ms, "RETREATING",
                         point.id, repetition, retreat_duration_ms)) {
        return run;
      }
      add_event(run, "WAITING_RETREAT_SETTLE", point.id, repetition,
                "mock_retreat_settled");
      run.samples.back().retreat_completed = true;
      run.samples.back().retreat_move_duration_ms = retreat_duration_ms;
      current = retreat.target_joints;
    }
  }

  const auto return_preflight = therapy_robot::preflight_endpoint_positioning(
      current, simulated_safe_pose, limits, collision);
  if (!return_preflight.ok) {
    fail(run, "safe_return_preflight_rejected:" + return_preflight.reason, "", 0);
    return run;
  }
  int return_duration_ms = 0;
  if (!simulate_move(run, current, return_preflight.target_joints,
                     options.move_timeout_ms, "RETURNING_SAFE", "", 0,
                     return_duration_ms)) {
    return run;
  }
  run.safe_start_returned = true;
  run.passed = true;
  run.status = "PASS";
  run.final_state = "COMPLETE";
  add_event(run, "COMPLETE", "", 0, "all_points_completed");
  return run;
}

double distance(const Pose& pose, double x, double y, double z) {
  return std::hypot(std::hypot(pose.x_m - x, pose.y_m - y), pose.z_m - z);
}

void write_csv(const std::string& path, const std::vector<Sample>& samples) {
  std::ofstream out(path);
  if (!out) throw std::runtime_error("cannot write CSV: " + path);
  out << "point_id,repetition,arrival_type,target_x_m,target_y_m,target_z_m,"
         "target_rx_rad,target_ry_rad,target_rz_rad,actual_k0_m,actual_k1_rad,"
         "actual_k2_rad,actual_k3_rad,actual_k4_rad,actual_x_m,actual_y_m,"
         "actual_z_m,actual_rx_rad,actual_ry_rad,actual_rz_rad,position_error_m,"
         "orientation_error_rad,position_tolerance_m,orientation_tolerance_rad,"
         "position_check_passed,orientation_check_passed,accepted,reason,"
         "feedback_valid,move_duration_ms,settle_duration_ms,random_seed,"
         "random_candidate_attempt,random_angle_rad,random_angle_deg,"
         "retreat_radius_m,retreat_x_m,retreat_y_m,retreat_z_m,"
         "retreat_rx_rad,retreat_ry_rad,retreat_rz_rad,retreat_move_duration_ms,"
         "retreat_ik_passed,retreat_limit_passed,retreat_collision_passed,"
         "retreat_path_passed,return_path_passed,retreat_completed,"
         "simulation_only,motor_command_generated,serial_accessed,d405_accessed\n";
  out << std::setprecision(17);
  for (const auto& sample : samples) {
    const auto& pose = sample.evaluation.actual_pose;
    const auto& joints = sample.actual_joints;
    const auto& evaluation = sample.evaluation;
    out << sample.point_id << ',' << sample.repetition << ',' << sample.arrival_type << ','
        << sample.target.x_m << ',' << sample.target.y_m << ',' << sample.target.z_m << ','
        << sample.target.rx_rad << ',' << sample.target.ry_rad << ',' << sample.target.rz_rad << ','
        << joints.k0_m << ',' << joints.k1_rad << ',' << joints.k2_rad << ','
        << joints.k3_rad << ',' << joints.k4_rad << ','
        << pose.x_m << ',' << pose.y_m << ',' << pose.z_m << ','
        << pose.rx_rad << ',' << pose.ry_rad << ',' << pose.rz_rad << ','
        << evaluation.target_error_m << ',' << evaluation.orientation_error_rad << ','
        << evaluation.position_tolerance_m << ',' << evaluation.orientation_tolerance_rad << ','
        << (evaluation.position_check_passed ? "true" : "false") << ','
        << (evaluation.orientation_check_passed ? "true" : "false") << ','
        << (evaluation.accepted ? "true" : "false") << ',' << evaluation.reason << ','
        << (sample.feedback_valid ? "true" : "false") << ','
        << sample.move_duration_ms << ',' << sample.settle_duration_ms << ','
        << sample.random_seed << ',' << sample.random_candidate_attempt << ','
        << sample.random_angle_rad << ',' << sample.random_angle_rad * 180.0 / kPi << ','
        << sample.retreat_radius_m << ',' << sample.retreat_pose.x_m << ','
        << sample.retreat_pose.y_m << ',' << sample.retreat_pose.z_m << ','
        << sample.retreat_pose.rx_rad << ',' << sample.retreat_pose.ry_rad << ','
        << sample.retreat_pose.rz_rad << ',' << sample.retreat_move_duration_ms << ','
        << (sample.retreat_ik_passed ? "true" : "false") << ','
        << (sample.retreat_limit_passed ? "true" : "false") << ','
        << (sample.retreat_collision_passed ? "true" : "false") << ','
        << (sample.retreat_path_passed ? "true" : "false") << ','
        << (sample.return_path_passed ? "true" : "false") << ','
        << (sample.retreat_completed ? "true" : "false")
        << ",true,false,false,false\n";
  }
  out.flush();
  if (!out) throw std::runtime_error("cannot finish CSV: " + path);
}

void write_pose_json(std::ostream& out, const Pose& pose) {
  out << "{\"x_m\":" << pose.x_m << ",\"y_m\":" << pose.y_m
      << ",\"z_m\":" << pose.z_m << ",\"rx_rad\":" << pose.rx_rad
      << ",\"ry_rad\":" << pose.ry_rad << ",\"rz_rad\":" << pose.rz_rad << '}';
}

void write_json(const std::string& path, const std::vector<Point>& points,
                const Options& options, const RunResult& run) {
  std::ofstream out(path);
  if (!out) throw std::runtime_error("cannot write JSON: " + path);
  out << std::setprecision(17);
  out << "{\"schema_version\":\"s3.endpoint-repeatability-sim.v1\""
      << ",\"status\":\"" << run.status << "\""
      << ",\"final_state\":\"" << run.final_state << "\""
      << ",\"failure_reason\":\"" << json_string(run.failure_reason) << "\""
      << ",\"platform\":\"x86_64_vm\",\"host\":\"zzqVM\""
      << ",\"simulation_only\":true,\"mock_motor_used\":true"
      << ",\"mock_feedback_used\":true,\"repetitions_per_point\":"
      << options.repetitions
      << ",\"selected_points\":" << points.size()
      << ",\"planned_samples\":" << points.size() * options.repetitions
      << ",\"completed_samples\":" << run.samples.size()
      << ",\"test_mode\":\"randomized_radial_reacquisition\""
      << ",\"retreat_plane\":\"BASE_XY\""
      << ",\"retreat_radius_m\":" << options.retreat_radius_m
      << ",\"random_seed\":" << options.random_seed
      << ",\"random_candidate_attempts\":" << options.random_candidate_attempts
      << ",\"retreat_destination\":\"RANDOM_CIRCLE_POINT\""
      << ",\"move_timeout_ms\":" << options.move_timeout_ms
      << ",\"settle_timeout_ms\":" << options.settle_timeout_ms
      << ",\"total_move_duration_ms\":" << run.total_move_duration_ms
      << ",\"safe_start_returned\":" << (run.safe_start_returned ? "true" : "false")
      << ",\"formal_safe_high_generated\":false"
      << ",\"execution_allowed\":false,\"entity_action_authorized\":false"
      << ",\"entity_motion_authorized\":false,\"motor_command_generated\":false"
      << ",\"motor_target_generated\":false,\"serial_payload_generated\":false"
      << ",\"shared_memory_written\":false,\"serial_accessed\":false"
      << ",\"d405_accessed\":false,\"nano_tested\":false"
      << ",\"arm64_tested\":false,\"entity_hardware_tested\":false";

  out << ",\"point_summaries\":[";
  for (std::size_t point_index = 0; point_index < points.size(); ++point_index) {
    if (point_index != 0) out << ',';
    const auto& point = points[point_index];
    std::vector<const Sample*> selected;
    for (const auto& sample : run.samples) {
      if (sample.point_id == point.id && sample.evaluation.accepted) selected.push_back(&sample);
    }
    double mean_x = 0.0, mean_y = 0.0, mean_z = 0.0;
    double mean_error = 0.0, max_error = 0.0, squared_error = 0.0;
    for (const auto* sample : selected) {
      mean_x += sample->evaluation.actual_pose.x_m;
      mean_y += sample->evaluation.actual_pose.y_m;
      mean_z += sample->evaluation.actual_pose.z_m;
      mean_error += sample->evaluation.target_error_m;
      max_error = std::max(max_error, sample->evaluation.target_error_m);
      squared_error += sample->evaluation.target_error_m *
                       sample->evaluation.target_error_m;
    }
    if (!selected.empty()) {
      const double count = static_cast<double>(selected.size());
      mean_x /= count; mean_y /= count; mean_z /= count;
      mean_error /= count;
    }
    double mean_repeatability = 0.0, max_repeatability = 0.0;
    double squared_repeatability = 0.0;
    for (const auto* sample : selected) {
      const double repeatability =
          distance(sample->evaluation.actual_pose, mean_x, mean_y, mean_z);
      mean_repeatability += repeatability;
      squared_repeatability += repeatability * repeatability;
      max_repeatability = std::max(max_repeatability, repeatability);
    }
    double rms_error = 0.0, rms_repeatability = 0.0;
    double repeatability_stddev = 0.0;
    if (!selected.empty()) {
      const double count = static_cast<double>(selected.size());
      mean_repeatability /= count;
      rms_error = std::sqrt(squared_error / count);
      rms_repeatability = std::sqrt(squared_repeatability / count);
      double variance = 0.0;
      for (const auto* sample : selected) {
        const double repeatability =
            distance(sample->evaluation.actual_pose, mean_x, mean_y, mean_z);
        const double delta = repeatability - mean_repeatability;
        variance += delta * delta;
      }
      repeatability_stddev = std::sqrt(variance / count);
    }
    out << "{\"point_id\":\"" << json_string(point.id) << "\",\"target\":";
    write_pose_json(out, point.target);
    out << ",\"completed_repetitions\":" << selected.size()
        << ",\"mean_actual_xyz_m\":[" << mean_x << ',' << mean_y << ',' << mean_z << ']'
        << ",\"mean_position_error_m\":" << mean_error
        << ",\"max_position_error_m\":" << max_error
        << ",\"rms_position_error_m\":" << rms_error
        << ",\"mean_repeatability_error_m\":" << mean_repeatability
        << ",\"max_repeatability_error_m\":" << max_repeatability
        << ",\"rms_repeatability_error_m\":" << rms_repeatability
        << ",\"stddev_repeatability_error_m\":" << repeatability_stddev << '}';
  }
  out << ']';

  out << ",\"samples\":[";
  for (std::size_t index = 0; index < run.samples.size(); ++index) {
    if (index != 0) out << ',';
    const auto& sample = run.samples[index];
    out << "{\"point_id\":\"" << json_string(sample.point_id)
        << "\",\"repetition\":" << sample.repetition
        << ",\"arrival_type\":\"" << sample.arrival_type << "\",\"target\":";
    write_pose_json(out, sample.target);
    out << ",\"actual\":";
    write_pose_json(out, sample.evaluation.actual_pose);
    out << ",\"actual_joints\":[" << sample.actual_joints.k0_m << ','
        << sample.actual_joints.k1_rad << ',' << sample.actual_joints.k2_rad << ','
        << sample.actual_joints.k3_rad << ',' << sample.actual_joints.k4_rad << ']'
        << ",\"position_error_m\":" << sample.evaluation.target_error_m
        << ",\"orientation_error_rad\":" << sample.evaluation.orientation_error_rad
        << ",\"accepted\":" << (sample.evaluation.accepted ? "true" : "false")
        << ",\"reason\":\"" << json_string(sample.evaluation.reason) << "\""
        << ",\"feedback_valid\":" << (sample.feedback_valid ? "true" : "false")
        << ",\"move_duration_ms\":" << sample.move_duration_ms
        << ",\"settle_duration_ms\":" << sample.settle_duration_ms
        << ",\"random_seed\":" << sample.random_seed
        << ",\"random_candidate_attempt\":" << sample.random_candidate_attempt
        << ",\"random_angle_rad\":" << sample.random_angle_rad
        << ",\"random_angle_deg\":" << sample.random_angle_rad * 180.0 / kPi
        << ",\"retreat_radius_m\":" << sample.retreat_radius_m
        << ",\"retreat_pose\":";
    write_pose_json(out, sample.retreat_pose);
    out << ",\"retreat_move_duration_ms\":" << sample.retreat_move_duration_ms
        << ",\"retreat_ik_passed\":" << (sample.retreat_ik_passed ? "true" : "false")
        << ",\"retreat_limit_passed\":" << (sample.retreat_limit_passed ? "true" : "false")
        << ",\"retreat_collision_passed\":" << (sample.retreat_collision_passed ? "true" : "false")
        << ",\"retreat_path_passed\":" << (sample.retreat_path_passed ? "true" : "false")
        << ",\"return_path_passed\":" << (sample.return_path_passed ? "true" : "false")
        << ",\"retreat_completed\":" << (sample.retreat_completed ? "true" : "false")
        << '}';
  }
  out << ']';

  out << ",\"events\":[";
  for (std::size_t index = 0; index < run.events.size(); ++index) {
    if (index != 0) out << ',';
    const auto& event = run.events[index];
    out << "{\"index\":" << index << ",\"state\":\"" << event.state
        << "\",\"point_id\":\"" << json_string(event.point_id)
        << "\",\"repetition\":" << event.repetition
        << ",\"detail\":\"" << json_string(event.detail) << "\"}";
  }
  out << "]}\n";
  out.flush();
  if (!out) throw std::runtime_error("cannot finish JSON: " + path);
}

void usage(std::ostream& out) {
  out << "usage: endpoint_repeatability_sim --points points.csv "
         "--collision-config enclosure.csv --json report.json --csv table.csv "
         "[--retreat-radius-m N] [--random-seed N] "
         "[--random-candidate-attempts N] [--repetitions N] "
         "[--move-timeout-ms N] "
         "[--settle-timeout-ms N] [--simulate-feedback-loss-at point_id:repetition]\n";
}

Options parse_options(int argc, char** argv) {
  Options options;
  for (int index = 1; index < argc; index += 2) {
    if (index + 1 >= argc) throw InputError("missing option value");
    const std::string flag = argv[index];
    const std::string value = argv[index + 1];
    if (flag == "--points") options.points_path = value;
    else if (flag == "--collision-config") options.collision_path = value;
    else if (flag == "--json") options.json_path = value;
    else if (flag == "--csv") options.csv_path = value;
    else if (flag == "--retreat-radius-m" || flag == "--retreat-distance-m") {
      options.retreat_radius_m = parse_number(value, flag, 0);
    } else if (flag == "--random-seed") {
      options.random_seed = parse_seed(value);
    } else if (flag == "--random-candidate-attempts") {
      options.random_candidate_attempts = parse_positive_int(value, flag);
    } else if (flag == "--repetitions") {
      options.repetitions = parse_repetitions(value);
    } else if (flag == "--move-timeout-ms") {
      options.move_timeout_ms = parse_positive_int(value, flag);
    } else if (flag == "--settle-timeout-ms") {
      options.settle_timeout_ms = parse_positive_int(value, flag);
    } else if (flag == "--simulate-feedback-loss-at") {
      options.feedback_loss_at = value;
    } else {
      throw InputError("unknown option: " + flag);
    }
  }
  if (options.points_path.empty() || options.collision_path.empty() ||
      options.json_path.empty() || options.csv_path.empty()) {
    throw InputError("missing required option");
  }
  if (!std::isfinite(options.retreat_radius_m) || options.retreat_radius_m <= 0.0) {
    throw InputError("retreat-radius-m must be a finite positive number");
  }
  return options;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const auto options = parse_options(argc, argv);
    const auto points = read_points(options.points_path);
    const auto collision = therapy_robot::load_collision_config(
        options.collision_path, true);
    const auto run = run_simulation(points, collision, options);
    write_csv(options.csv_path, run.samples);
    write_json(options.json_path, points, options, run);
    std::cout << "endpoint repeatability simulation status=" << run.status
              << " samples=" << run.samples.size()
              << " report=" << options.json_path
              << " table=" << options.csv_path << '\n';
    return run.passed ? 0 : 1;
  } catch (const InputError& error) {
    usage(std::cerr);
    std::cerr << "endpoint repeatability input rejected: " << error.what() << '\n';
    return 2;
  } catch (const std::exception& error) {
    std::cerr << "endpoint repeatability simulation failed: " << error.what() << '\n';
    return 1;
  }
}
