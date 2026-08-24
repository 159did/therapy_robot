// Standalone H1 collector. It intentionally exposes only MF9025V2 read calls.
#include "therapy_robot/mf9025v2_driver.hpp"

#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

using therapy_robot::Mf9025v2Bus;
using therapy_robot::Mf9025v2Feedback;

namespace {
struct Axis { const char* name; int group; uint8_t motor_id; double scale; bool brake; };
constexpr Axis kAxes[] = {
    {"K0", 0, 1, 1.0 / 14400.0, true},
    {"K1", 1, 1, 1.0 / 4800.0, false},
    {"K2", 1, 2, 1.0 / 1200.0, false},
    {"K3", 2, 1, 1.0 / 1000.0, false},
    {"K4", 2, 2, 1.0 / 1000.0, false},
};
struct Options {
  std::string g0, g1, g2, output, controller_time_utc;
  std::string offsets_file = "config/axis-offsets-native.txt";
  std::string k0_file = "config/k0-last-logical-native.txt";
  int samples = 10, interval_ms = 100, timeout_ms = 200;
};
struct Reading { int64_t raw = 0; Mf9025v2Feedback status{}, state{}; uint32_t encoder = 0; bool brake_known = false, brake_engaged = false; };

bool value(int& i, int argc, char** argv, std::string& out) { if (i + 1 >= argc) return false; out = argv[++i]; return true; }
bool parse(int argc, char** argv, Options& o) {
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--g0-port" && value(i, argc, argv, o.g0)) continue;
    if (a == "--g1-port" && value(i, argc, argv, o.g1)) continue;
    if (a == "--g2-port" && value(i, argc, argv, o.g2)) continue;
    if (a == "--output" && value(i, argc, argv, o.output)) continue;
    if (a == "--controller-time-utc" && value(i, argc, argv, o.controller_time_utc)) continue;
    if (a == "--offsets-file" && value(i, argc, argv, o.offsets_file)) continue;
    if (a == "--k0-file" && value(i, argc, argv, o.k0_file)) continue;
    if (a == "--samples" && i + 1 < argc) { o.samples = std::stoi(argv[++i]); continue; }
    if (a == "--interval-ms" && i + 1 < argc) { o.interval_ms = std::stoi(argv[++i]); continue; }
    if (a == "--timeout-ms" && i + 1 < argc) { o.timeout_ms = std::stoi(argv[++i]); continue; }
    std::cerr << "unknown or incomplete option: " << a << '\n'; return false;
  }
  if (o.g0.empty() || o.g1.empty() || o.g2.empty() || o.output.empty() || o.controller_time_utc.empty()) return false;
  for (const auto* p : {&o.g0, &o.g1, &o.g2}) if (p->rfind("/dev/serial/by-path/", 0) != 0) return false;
  return o.samples >= 1 && o.samples <= 300 && o.interval_ms >= 0 && o.timeout_ms > 0;
}
std::optional<std::array<int64_t, 5>> offsets(const std::string& path) {
  std::ifstream in(path); std::string line; if (!in || !std::getline(in, line)) return std::nullopt;
  std::array<int64_t, 5> out{}; std::stringstream ss(line); std::string item; int n = 0;
  while (std::getline(ss, item, ',') && n < 5) out[n++] = std::stoll(item);
  return n == 5 ? std::optional<std::array<int64_t, 5>>(out) : std::nullopt;
}
std::optional<int64_t> k0_value(const std::string& path) { std::ifstream in(path); int64_t v = 0; return (in >> v) ? std::optional<int64_t>(v) : std::nullopt; }
std::string esc(const std::string& s) { std::ostringstream o; for (char c : s) { if (c == '\\' || c == '"') o << '\\'; o << c; } return o.str(); }
bool read_axis(Mf9025v2Bus& bus, const Axis& axis, Reading& r, std::string& error) {
  if (!bus.read_position(axis.motor_id, r.raw, error)) return false;
  if (!bus.read_status(axis.motor_id, r.status, error)) return false;
  if (!bus.read_state(axis.motor_id, r.state, error)) return false;
  if (!bus.read_encoder(axis.motor_id, false, r.encoder, error)) return false;
  if (axis.brake && !bus.read_brake(axis.motor_id, r.brake_engaged, error)) return false;
  r.brake_known = axis.brake; return true;
}
double si(const Axis& a, int64_t logical) { const double display = logical * a.scale; return a.group == 0 ? display / 1000.0 : display * 3.14159265358979323846 / 180.0; }
void write_sample(std::ostream& out, const Axis& a, const Reading& r, int64_t offset, int sample, int64_t mono, const Options& o, const std::string& port) {
  const int64_t logical = r.raw - offset;
  out << "{\"sample_index\":" << sample << ",\"absolute_time\":\"" << esc(o.controller_time_utc)
      << "\",\"time_authority\":\"controller_network_clock\",\"monotonic_time_ms\":" << mono
      << ",\"axis_name\":\"" << a.name << "\",\"port\":\"" << esc(port) << "\",\"motor_id\":" << int(a.motor_id)
      << ",\"feedback_sequence\":" << sample << ",\"feedback_time_ms\":" << mono << ",\"feedback_age_ms\":0"
      << ",\"feedback_position_native\":" << r.raw << ",\"coordinate_offset_native\":" << offset
      << ",\"actual_motor_native\":" << logical << ",\"actual_axis_si\":" << std::setprecision(12) << si(a, logical)
      << ",\"native_unit\":\"native\",\"si_unit\":\"" << (a.group == 0 ? "m" : "rad") << "\""
      << ",\"online\":true,\"fault\":" << int(r.state.error_state) << ",\"enabled\":" << (r.state.motor_state ? "true" : "false")
      << ",\"velocity_native\":" << r.status.speed_native << ",\"temperature_c\":" << int(r.status.temperature_c)
      << ",\"current_native\":" << r.status.current_native << ",\"encoder\":" << r.encoder
      << ",\"brake_state_known\":" << (r.brake_known ? "true" : "false") << ",\"brake_engaged\":";
  if (r.brake_known) out << (r.brake_engaged ? "true" : "false"); else out << "null";
  out << ",\"feedback_valid\":true,\"limit_state\":\"unknown\",\"collision_state\":\"unknown\",\"hardware_mode\":\"readonly_serial\"}\n";
}
}  // namespace

int main(int argc, char** argv) {
  Options o; if (!parse(argc, argv, o)) return 2;
  const auto off = offsets(o.offsets_file); const auto k0 = k0_value(o.k0_file);
  if (!off || !k0) { std::cerr << "offset or k0 persistence file unavailable\n"; return 3; }
  const std::string ports[] = {o.g0, o.g1, o.g2}; std::vector<Mf9025v2Bus> buses(3); std::string error;
  for (int g = 0; g < 3; ++g) if (!buses[g].open_port(ports[g], o.timeout_ms, error)) { std::cerr << error << '\n'; return 4; }
  std::ofstream out(o.output, std::ios::trunc); if (!out) return 3;
  for (int sample = 1; sample <= o.samples; ++sample) {
    for (int i = 0; i < 5; ++i) {
      Reading r; if (!read_axis(buses[kAxes[i].group], kAxes[i], r, error)) { std::cerr << kAxes[i].name << ": " << error << '\n'; return 5; }
      int64_t offset = i == 0 ? r.raw - *k0 : (*off)[i];
      write_sample(out, kAxes[i], r, offset, sample,
                   std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(), o, ports[kAxes[i].group]);
    }
    out.flush(); if (sample < o.samples) std::this_thread::sleep_for(std::chrono::milliseconds(o.interval_ms));
  }
  return 0;
}
