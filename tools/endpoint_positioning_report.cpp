#include "therapy_robot/endpoint_positioning.hpp"

#include "therapy_robot/collision.hpp"
#include "therapy_robot/motion_plan.hpp"
#include "therapy_robot/shared_memory.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using therapy_robot::EndpointPositioningMeasurement;
using therapy_robot::EndpointPositioningResult;
using therapy_robot::JointState;
using therapy_robot::Pose;

constexpr const char* kRequiredHeader =
    "sample_id,side,source_k0_m,source_k1_rad,source_k2_rad,source_k3_rad,source_k4_rad,"
    "target_x_m,target_y_m,target_z_m,target_rx_rad,target_ry_rad,target_rz_rad,"
    "actual_k0_m,actual_k1_rad,actual_k2_rad,actual_k3_rad,actual_k4_rad";

struct Summary {
  std::size_t accepted = 0;
  std::size_t rejected = 0;
  double mean_x = 0.0;
  double mean_y = 0.0;
  double mean_z = 0.0;
  double mean_target_error_m = 0.0;
  double max_target_error_m = 0.0;
  double rms_target_error_m = 0.0;
  double mean_repeatability_error_m = 0.0;
  double max_repeatability_error_m = 0.0;
  double rms_repeatability_error_m = 0.0;
  double stddev_repeatability_error_m = 0.0;
};

std::vector<std::string> split_csv(const std::string& line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) fields.push_back(field);
  return fields;
}

double parse_number(const std::string& text, const std::string& field,
                    std::size_t row) {
  std::size_t consumed = 0;
  double value = 0.0;
  try {
    value = std::stod(text, &consumed);
  } catch (const std::exception&) {
    throw std::runtime_error("row " + std::to_string(row) + ": invalid " + field);
  }
  if (consumed != text.size() || !std::isfinite(value)) {
    throw std::runtime_error("row " + std::to_string(row) + ": invalid " + field);
  }
  return value;
}

EndpointPositioningMeasurement parse_measurement(const std::string& line,
                                                  std::size_t row) {
  const auto fields = split_csv(line);
  if (fields.size() != 18) {
    throw std::runtime_error("row " + std::to_string(row) + ": expected 18 CSV fields");
  }
  if (fields[0].empty() || (fields[1] != "left" && fields[1] != "right")) {
    throw std::runtime_error("row " + std::to_string(row) + ": sample_id and side are required");
  }
  EndpointPositioningMeasurement measurement;
  measurement.sample_id = fields[0];
  measurement.side = fields[1];
  measurement.source = {parse_number(fields[2], "source_k0_m", row),
                        parse_number(fields[3], "source_k1_rad", row),
                        parse_number(fields[4], "source_k2_rad", row),
                        parse_number(fields[5], "source_k3_rad", row),
                        parse_number(fields[6], "source_k4_rad", row)};
  measurement.target = {parse_number(fields[7], "target_x_m", row),
                        parse_number(fields[8], "target_y_m", row),
                        parse_number(fields[9], "target_z_m", row),
                        parse_number(fields[10], "target_rx_rad", row),
                        parse_number(fields[11], "target_ry_rad", row),
                        parse_number(fields[12], "target_rz_rad", row)};
  measurement.actual = {parse_number(fields[13], "actual_k0_m", row),
                        parse_number(fields[14], "actual_k1_rad", row),
                        parse_number(fields[15], "actual_k2_rad", row),
                        parse_number(fields[16], "actual_k3_rad", row),
                        parse_number(fields[17], "actual_k4_rad", row)};
  return measurement;
}

std::vector<EndpointPositioningMeasurement> read_measurements(const std::string& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open input CSV: " + path);
  std::string line;
  if (!std::getline(input, line) || line != kRequiredHeader) {
    throw std::runtime_error("input CSV header does not match required schema");
  }
  std::vector<EndpointPositioningMeasurement> output;
  std::size_t row = 1;
  while (std::getline(input, line)) {
    ++row;
    if (line.empty()) continue;
    output.push_back(parse_measurement(line, row));
  }
  if (output.empty()) throw std::runtime_error("input CSV contains no measurements");
  return output;
}

std::string file_contents(const std::string& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) throw std::runtime_error("cannot open input CSV: " + path);
  std::ostringstream output;
  output << input.rdbuf();
  return output.str();
}

void validate_repeatability_groups(
    const std::vector<EndpointPositioningMeasurement>& measurements) {
  std::map<std::string, Pose> targets;
  constexpr double kTargetToleranceM = 1e-12;
  for (const auto& measurement : measurements) {
    const auto found = targets.find(measurement.side);
    if (found == targets.end()) {
      targets.emplace(measurement.side, measurement.target);
      continue;
    }
    if (std::hypot(std::hypot(measurement.target.x_m - found->second.x_m,
                              measurement.target.y_m - found->second.y_m),
                   measurement.target.z_m - found->second.z_m) > kTargetToleranceM ||
        std::abs(measurement.target.rx_rad - found->second.rx_rad) > kTargetToleranceM ||
        std::abs(measurement.target.ry_rad - found->second.ry_rad) > kTargetToleranceM ||
        std::abs(measurement.target.rz_rad - found->second.rz_rad) > kTargetToleranceM) {
      throw std::runtime_error("side '" + measurement.side +
                               "' has inconsistent target poses");
    }
  }
}

double distance(const Pose& pose, double x, double y, double z) {
  return std::hypot(std::hypot(pose.x_m - x, pose.y_m - y), pose.z_m - z);
}

Summary summarize(const std::vector<const EndpointPositioningResult*>& results) {
  Summary output;
  for (const auto* result : results) {
    if (result->accepted) ++output.accepted; else ++output.rejected;
  }
  if (output.accepted == 0) return output;
  for (const auto* result : results) {
    if (!result->accepted) continue;
    output.mean_x += result->actual_pose.x_m;
    output.mean_y += result->actual_pose.y_m;
    output.mean_z += result->actual_pose.z_m;
    output.mean_target_error_m += result->target_error_m;
    output.max_target_error_m = std::max(output.max_target_error_m, result->target_error_m);
  }
  const double count = static_cast<double>(output.accepted);
  output.mean_x /= count;
  output.mean_y /= count;
  output.mean_z /= count;
  output.mean_target_error_m /= count;
  double target_squared = 0.0;
  double repeatability_sum = 0.0;
  double repeatability_squared = 0.0;
  for (const auto* result : results) {
    if (!result->accepted) continue;
    target_squared += result->target_error_m * result->target_error_m;
    const double repeat = distance(result->actual_pose, output.mean_x, output.mean_y, output.mean_z);
    repeatability_sum += repeat;
    repeatability_squared += repeat * repeat;
    output.max_repeatability_error_m = std::max(output.max_repeatability_error_m, repeat);
  }
  output.rms_target_error_m = std::sqrt(target_squared / count);
  output.mean_repeatability_error_m = repeatability_sum / count;
  output.rms_repeatability_error_m = std::sqrt(repeatability_squared / count);
  double variance = 0.0;
  for (const auto* result : results) {
    if (!result->accepted) continue;
    const double repeat = distance(result->actual_pose, output.mean_x, output.mean_y, output.mean_z);
    const double delta = repeat - output.mean_repeatability_error_m;
    variance += delta * delta;
  }
  output.stddev_repeatability_error_m = std::sqrt(variance / count);
  return output;
}

void write_summary_json(std::ostream& out, const Summary& summary) {
  out << "{\"accepted\":" << summary.accepted
      << ",\"rejected\":" << summary.rejected
      << ",\"mean_endpoint_m\":[" << summary.mean_x << ',' << summary.mean_y << ',' << summary.mean_z << ']'
      << ",\"mean_target_error_m\":" << summary.mean_target_error_m
      << ",\"max_target_error_m\":" << summary.max_target_error_m
      << ",\"rms_target_error_m\":" << summary.rms_target_error_m
      << ",\"mean_repeatability_error_m\":" << summary.mean_repeatability_error_m
      << ",\"max_repeatability_error_m\":" << summary.max_repeatability_error_m
      << ",\"rms_repeatability_error_m\":" << summary.rms_repeatability_error_m
      << ",\"stddev_repeatability_error_m\":" << summary.stddev_repeatability_error_m
      << '}';
}

void write_usage(std::ostream& out) {
  out << "usage: endpoint_positioning_report --input measurements.csv --collision-config enclosure.csv --json report.json --csv results.csv\n";
}

}  // namespace

int main(int argc, char** argv) {
  std::string input_path;
  std::string collision_path;
  std::string json_path;
  std::string csv_path;
  for (int index = 1; index < argc; index += 2) {
    if (index + 1 >= argc) { write_usage(std::cerr); return 2; }
    const std::string flag = argv[index];
    const std::string value = argv[index + 1];
    if (flag == "--input") input_path = value;
    else if (flag == "--collision-config") collision_path = value;
    else if (flag == "--json") json_path = value;
    else if (flag == "--csv") csv_path = value;
    else { write_usage(std::cerr); return 2; }
  }
  if (input_path.empty() || collision_path.empty() || json_path.empty() || csv_path.empty()) {
    write_usage(std::cerr);
    return 2;
  }

  try {
    const auto measurements = read_measurements(input_path);
    validate_repeatability_groups(measurements);
    const std::string input_sha256 = therapy_robot::sha256_hex(file_contents(input_path));
    const auto collision = therapy_robot::load_collision_config(collision_path, true);
    therapy_robot::SharedState limits;
    therapy_robot::initialize_defaults(limits);
    std::vector<EndpointPositioningResult> results;
    results.reserve(measurements.size());
    for (const auto& measurement : measurements) {
      results.push_back(therapy_robot::evaluate_endpoint_positioning_measurement(
          measurement, limits, collision));
    }

    std::map<std::string, std::vector<const EndpointPositioningResult*>> groups;
    for (std::size_t index = 0; index < results.size(); ++index) {
      groups[measurements[index].side].push_back(&results[index]);
    }

    std::ofstream csv(csv_path);
    if (!csv) throw std::runtime_error("cannot write CSV: " + csv_path);
    csv << "sample_id,side,accepted,reason,actual_x_m,actual_y_m,actual_z_m,target_error_m,collision_checked,collision_reason\n";
    csv << std::setprecision(17);
    for (std::size_t index = 0; index < results.size(); ++index) {
      const auto& result = results[index];
      csv << measurements[index].sample_id << ',' << measurements[index].side << ','
          << (result.accepted ? "true" : "false") << ',' << result.reason << ','
          << result.actual_pose.x_m << ',' << result.actual_pose.y_m << ','
          << result.actual_pose.z_m << ',' << result.target_error_m << ','
          << (result.preflight.collision.checked ? "true" : "false") << ','
          << result.preflight.collision.reason << '\n';
    }

    std::ofstream json(json_path);
    if (!json) throw std::runtime_error("cannot write JSON: " + json_path);
    json << std::setprecision(17);
    json << "{\"schema_version\":\"s3.endpoint-positioning.offline.v1\""
         << ",\"platform\":\"x86_64_vm\""
         << ",\"host\":\"zzqVM\""
         << ",\"input_sha256\":\"" << input_sha256 << "\""
         << ",\"execution_allowed\":false"
         << ",\"entity_action_authorized\":false"
         << ",\"motor_command_generated\":false"
         << ",\"motor_target_generated\":false"
         << ",\"serial_payload_generated\":false"
         << ",\"serial_accessed\":false"
         << ",\"d405_accessed\":false"
         << ",\"hardware_mode_started\":false"
         << ",\"nano_tested\":false"
         << ",\"arm64_tested\":false"
         << ",\"entity_hardware_tested\":false"
         << ",\"collision_config\":\"" << collision_path << "\""
         << ",\"sides\":{";
    bool first = true;
    for (const auto& item : groups) {
      if (!first) json << ',';
      first = false;
      json << '"' << item.first << "\":";
      write_summary_json(json, summarize(item.second));
    }
    json << "}}\n";
    std::cout << "offline endpoint positioning report created: " << json_path << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "endpoint positioning report rejected: " << error.what() << '\n';
    return 1;
  }
}
