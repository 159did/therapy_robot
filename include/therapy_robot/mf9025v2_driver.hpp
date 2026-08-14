#pragma once

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

namespace therapy_robot {

struct Mf9025v2Feedback {
  int64_t position_native = 0;
  int16_t speed_native = 0;
  int16_t current_native = 0;
  uint16_t encoder = 0;
  uint8_t temperature_c = 0;
  uint8_t motor_state = 0;
  uint8_t error_state = 0;
};

// Minimal, dependency-free driver for the MF9025V2/LKMTECH 0x3E RS485
// protocol used by the original robo_arm project. One instance owns one
// serial bus; motor IDs may be reused safely on different bus instances.
class Mf9025v2Bus {
 public:
  Mf9025v2Bus() = default;
  ~Mf9025v2Bus();

  Mf9025v2Bus(const Mf9025v2Bus&) = delete;
  Mf9025v2Bus& operator=(const Mf9025v2Bus&) = delete;

  bool open_port(const std::string& port, int timeout_ms, std::string& error);
  void close_port();
  bool is_open() const;
  const std::string& port() const { return port_; }

  bool motor_on(uint8_t motor_id, std::string& error);
  bool motor_off(uint8_t motor_id, std::string& error);
  bool stop(uint8_t motor_id, std::string& error);
  bool engage_brake(uint8_t motor_id, bool& brake_engaged,
                    std::string& error);
  bool release_brake(uint8_t motor_id, bool& brake_engaged,
                     std::string& error);
  bool read_brake(uint8_t motor_id, bool& brake_engaged,
                  std::string& error);
  bool clear_error(uint8_t motor_id, Mf9025v2Feedback& feedback, std::string& error);

  bool set_position(uint8_t motor_id, int64_t position_native,
                    uint32_t max_speed_native, Mf9025v2Feedback& feedback,
                    std::string& error);
  bool read_position(uint8_t motor_id, int64_t& position_native,
                     std::string& error);
  bool read_encoder(uint8_t motor_id, bool raw, uint32_t& encoder,
                    std::string& error);
  bool read_single_angle(uint8_t motor_id, uint32_t& angle_native,
                         std::string& error);
  bool read_status(uint8_t motor_id, Mf9025v2Feedback& feedback,
                   std::string& error);
  bool read_state(uint8_t motor_id, Mf9025v2Feedback& feedback,
                  std::string& error);

  // Volatile zero: changes the motor RAM zero and is lost after power-down.
  // ROM zero is deliberately not exposed by this runtime driver.
  bool set_zero_ram(uint8_t motor_id, std::string& error);

 private:
  bool exchange(uint8_t command, uint8_t motor_id,
                const std::vector<uint8_t>& request_data,
                bool response_has_data_checksum,
                std::vector<uint8_t>& response_data,
                std::string& error);
  bool brake_command(uint8_t motor_id, uint8_t operation,
                     bool& brake_engaged, std::string& error);
  bool write_all(const uint8_t* data, std::size_t size, std::string& error);
  bool read_exact(uint8_t* data, std::size_t size, std::string& error);
  bool read_header(uint8_t command, uint8_t motor_id, uint8_t header[5],
                   std::string& error);
  void drain_input();

  static uint8_t checksum(const uint8_t* data, std::size_t size);
  static int16_t read_i16_le(const uint8_t* data);
  static uint16_t read_u16_le(const uint8_t* data);
  static int64_t read_i64_le(const uint8_t* data);
  static uint32_t read_u32_le(const uint8_t* data);
  static void append_u32_le(std::vector<uint8_t>& out, uint32_t value);
  static void append_i64_le(std::vector<uint8_t>& out, int64_t value);

  mutable std::mutex mutex_;
  int fd_ = -1;
  int timeout_ms_ = 80;
  std::string port_;
};

}  // namespace therapy_robot
