#include "therapy_robot/mf9025v2_driver.hpp"

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <sstream>
#include <termios.h>
#include <unistd.h>

namespace therapy_robot {
namespace {

std::string errno_text(const char* operation) {
  std::ostringstream out;
  out << operation << ": " << std::strerror(errno);
  return out.str();
}

bool parse_status_payload(const std::vector<uint8_t>& data,
                          Mf9025v2Feedback& feedback,
                          std::string& error) {
  if (data.size() < 7) {
    error = "status response is shorter than 7 bytes";
    return false;
  }
  feedback.temperature_c = data[0];
  feedback.current_native = static_cast<int16_t>(
      static_cast<uint16_t>(data[1]) |
      (static_cast<uint16_t>(data[2]) << 8));
  feedback.speed_native = static_cast<int16_t>(
      static_cast<uint16_t>(data[3]) |
      (static_cast<uint16_t>(data[4]) << 8));
  feedback.encoder = static_cast<uint16_t>(
      static_cast<uint16_t>(data[5]) |
      (static_cast<uint16_t>(data[6]) << 8));
  return true;
}

}  // namespace

Mf9025v2Bus::~Mf9025v2Bus() { close_port(); }

bool Mf9025v2Bus::open_port(const std::string& port, int timeout_ms,
                            std::string& error) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (fd_ >= 0) {
    ::close(fd_);
    fd_ = -1;
  }

  int fd = ::open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
  if (fd < 0) {
    error = errno_text(("open " + port).c_str());
    return false;
  }

  termios options{};
  if (tcgetattr(fd, &options) != 0) {
    error = errno_text("tcgetattr");
    ::close(fd);
    return false;
  }
  cfmakeraw(&options);
  cfsetispeed(&options, B115200);
  cfsetospeed(&options, B115200);
  options.c_cflag |= CLOCAL | CREAD;
  options.c_cflag &= ~CSTOPB;
  options.c_cflag &= ~PARENB;
  options.c_cflag &= ~CSIZE;
  options.c_cflag |= CS8;
#ifdef CRTSCTS
  options.c_cflag &= ~CRTSCTS;
#endif
  options.c_cc[VMIN] = 0;
  options.c_cc[VTIME] = 0;
  if (tcsetattr(fd, TCSANOW, &options) != 0) {
    error = errno_text("tcsetattr");
    ::close(fd);
    return false;
  }
  tcflush(fd, TCIOFLUSH);

  fd_ = fd;
  timeout_ms_ = timeout_ms > 0 ? timeout_ms : 80;
  port_ = port;
  error.clear();
  return true;
}

void Mf9025v2Bus::close_port() {
  std::lock_guard<std::mutex> lock(mutex_);
  if (fd_ >= 0) {
    tcflush(fd_, TCIOFLUSH);
    ::close(fd_);
    fd_ = -1;
  }
  port_.clear();
}

bool Mf9025v2Bus::is_open() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return fd_ >= 0;
}

bool Mf9025v2Bus::motor_on(uint8_t motor_id, std::string& error) {
  std::vector<uint8_t> response;
  return exchange(0x88, motor_id, {}, false, response, error);
}

bool Mf9025v2Bus::motor_off(uint8_t motor_id, std::string& error) {
  std::vector<uint8_t> response;
  return exchange(0x80, motor_id, {}, false, response, error);
}

bool Mf9025v2Bus::stop(uint8_t motor_id, std::string& error) {
  std::vector<uint8_t> response;
  return exchange(0x81, motor_id, {}, false, response, error);
}

bool Mf9025v2Bus::engage_brake(uint8_t motor_id, bool& brake_engaged,
                               std::string& error) {
  return brake_command(motor_id, 0x00, brake_engaged, error);
}

bool Mf9025v2Bus::release_brake(uint8_t motor_id, bool& brake_engaged,
                                std::string& error) {
  return brake_command(motor_id, 0x01, brake_engaged, error);
}

bool Mf9025v2Bus::read_brake(uint8_t motor_id, bool& brake_engaged,
                             std::string& error) {
  return brake_command(motor_id, 0x10, brake_engaged, error);
}

bool Mf9025v2Bus::brake_command(uint8_t motor_id, uint8_t operation,
                                bool& brake_engaged, std::string& error) {
  std::vector<uint8_t> response;
  if (!exchange(0x8C, motor_id, {operation}, true, response, error)) {
    return false;
  }
  if (response.size() != 1 || (response[0] != 0x00 && response[0] != 0x01)) {
    error = "brake response must contain one 0x00/0x01 state byte";
    return false;
  }
  // Protocol: 0x00 = brake coil off, brake engaged; 0x01 = released.
  brake_engaged = response[0] == 0x00;
  if (operation == 0x00 && !brake_engaged) {
    error = "brake acknowledged but did not report engaged";
    return false;
  }
  if (operation == 0x01 && brake_engaged) {
    error = "brake acknowledged but did not report released";
    return false;
  }
  error.clear();
  return true;
}

bool Mf9025v2Bus::clear_error(uint8_t motor_id,
                              Mf9025v2Feedback& feedback,
                              std::string& error) {
  std::vector<uint8_t> data;
  if (!exchange(0x9B, motor_id, {}, true, data, error)) return false;
  if (data.size() < 7) {
    error = "clear-error response is shorter than 7 bytes";
    return false;
  }
  feedback.motor_state = data[5];
  feedback.error_state = data[6];
  return true;
}

bool Mf9025v2Bus::set_position(uint8_t motor_id, int64_t position_native,
                               uint32_t max_speed_native,
                               Mf9025v2Feedback& feedback,
                               std::string& error) {
  std::vector<uint8_t> request;
  request.reserve(12);
  append_i64_le(request, position_native);
  append_u32_le(request, max_speed_native);
  std::vector<uint8_t> response;
  if (!exchange(0xA4, motor_id, request, true, response, error)) return false;
  return parse_status_payload(response, feedback, error);
}

bool Mf9025v2Bus::read_position(uint8_t motor_id, int64_t& position_native,
                                std::string& error) {
  std::vector<uint8_t> response;
  if (!exchange(0x92, motor_id, {}, true, response, error)) return false;
  if (response.size() < 8) {
    error = "multi-turn position response is shorter than 8 bytes";
    return false;
  }
  position_native = read_i64_le(response.data());
  return true;
}

bool Mf9025v2Bus::read_encoder(uint8_t motor_id, bool raw,
                               uint32_t& encoder, std::string& error) {
  std::vector<uint8_t> request(7, 0);
  request[0] = raw ? 1 : 0;
  std::vector<uint8_t> response;
  if (!exchange(0x90, motor_id, request, true, response, error)) return false;
  if (response.size() != 7 || response[0] != request[0]) {
    error = "encoder response has an invalid length or type echo";
    return false;
  }
  encoder = read_u32_le(response.data() + 3);
  return true;
}

bool Mf9025v2Bus::read_single_angle(uint8_t motor_id,
                                    uint32_t& angle_native,
                                    std::string& error) {
  std::vector<uint8_t> response;
  if (!exchange(0x94, motor_id, {}, true, response, error)) return false;
  if (response.size() != 4) {
    error = "single-angle response must contain 4 data bytes";
    return false;
  }
  angle_native = read_u32_le(response.data());
  return true;
}

bool Mf9025v2Bus::read_status(uint8_t motor_id,
                              Mf9025v2Feedback& feedback,
                              std::string& error) {
  std::vector<uint8_t> response;
  if (!exchange(0x9C, motor_id, {}, true, response, error)) return false;
  return parse_status_payload(response, feedback, error);
}

bool Mf9025v2Bus::read_state(uint8_t motor_id,
                             Mf9025v2Feedback& feedback,
                             std::string& error) {
  std::vector<uint8_t> response;
  if (!exchange(0x9A, motor_id, {}, true, response, error)) return false;
  if (response.size() < 7) {
    error = "state response is shorter than 7 bytes";
    return false;
  }
  feedback.motor_state = response[5];
  feedback.error_state = response[6];
  return true;
}

bool Mf9025v2Bus::set_zero_ram(uint8_t motor_id, std::string& error) {
  std::vector<uint8_t> response;
  return exchange(0x95, motor_id, std::vector<uint8_t>(7, 0), true,
                  response, error);
}

bool Mf9025v2Bus::exchange(uint8_t command, uint8_t motor_id,
                           const std::vector<uint8_t>& request_data,
                           bool response_has_data_checksum,
                           std::vector<uint8_t>& response_data,
                           std::string& error) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (fd_ < 0) {
    error = "serial port is not open";
    return false;
  }
  if (request_data.size() > 255) {
    error = "request data is too large";
    return false;
  }

  std::vector<uint8_t> frame;
  frame.reserve(5 + request_data.size() + (request_data.empty() ? 0 : 1));
  frame.push_back(0x3E);
  frame.push_back(command);
  frame.push_back(motor_id);
  frame.push_back(static_cast<uint8_t>(request_data.size()));
  frame.push_back(checksum(frame.data(), 4));
  frame.insert(frame.end(), request_data.begin(), request_data.end());
  if (!request_data.empty()) {
    frame.push_back(checksum(request_data.data(), request_data.size()));
  }

  drain_input();
  if (!write_all(frame.data(), frame.size(), error)) return false;
  if (tcdrain(fd_) != 0) {
    error = errno_text("tcdrain");
    return false;
  }

  uint8_t header[5]{};
  if (!read_header(command, motor_id, header, error)) return false;
  const std::size_t data_size = header[3];
  const std::size_t wire_size =
      data_size + ((response_has_data_checksum && data_size > 0) ? 1 : 0);
  std::vector<uint8_t> wire_data(wire_size);
  if (wire_size > 0 && !read_exact(wire_data.data(), wire_size, error)) {
    return false;
  }
  if (response_has_data_checksum && data_size > 0) {
    const uint8_t expected = checksum(wire_data.data(), data_size);
    if (wire_data[data_size] != expected) {
      error = "response data checksum mismatch";
      return false;
    }
  }
  response_data.assign(wire_data.begin(), wire_data.begin() + data_size);
  error.clear();
  return true;
}

bool Mf9025v2Bus::write_all(const uint8_t* data, std::size_t size,
                            std::string& error) {
  std::size_t written = 0;
  while (written < size) {
    pollfd descriptor{fd_, POLLOUT, 0};
    int ready;
    do {
      ready = poll(&descriptor, 1, timeout_ms_);
    } while (ready < 0 && errno == EINTR);
    if (ready == 0) {
      error = "serial write timed out";
      return false;
    }
    if (ready < 0) {
      error = errno_text("poll write");
      return false;
    }
    ssize_t count = ::write(fd_, data + written, size - written);
    if (count > 0) {
      written += static_cast<std::size_t>(count);
      continue;
    }
    if (count < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    error = errno_text("serial write");
    return false;
  }
  return true;
}

bool Mf9025v2Bus::read_exact(uint8_t* data, std::size_t size,
                             std::string& error) {
  std::size_t received = 0;
  while (received < size) {
    pollfd descriptor{fd_, POLLIN, 0};
    int ready;
    do {
      ready = poll(&descriptor, 1, timeout_ms_);
    } while (ready < 0 && errno == EINTR);
    if (ready == 0) {
      std::ostringstream out;
      out << "serial read timed out after " << received << '/' << size
          << " bytes";
      error = out.str();
      return false;
    }
    if (ready < 0) {
      error = errno_text("poll read");
      return false;
    }
    ssize_t count = ::read(fd_, data + received, size - received);
    if (count > 0) {
      received += static_cast<std::size_t>(count);
      continue;
    }
    if (count < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    error = count == 0 ? "serial port returned end-of-file"
                       : errno_text("serial read");
    return false;
  }
  return true;
}

bool Mf9025v2Bus::read_header(uint8_t command, uint8_t motor_id,
                              uint8_t header[5], std::string& error) {
  for (int scan = 0; scan < 64; ++scan) {
    uint8_t first = 0;
    if (!read_exact(&first, 1, error)) return false;
    if (first != 0x3E) continue;
    header[0] = first;
    if (!read_exact(header + 1, 4, error)) return false;
    if (header[4] != checksum(header, 4)) {
      error = "response header checksum mismatch";
      return false;
    }
    if (header[1] != command || header[2] != motor_id) {
      std::ostringstream out;
      out << "unexpected response cmd/id: got 0x" << std::hex
          << static_cast<int>(header[1]) << '/' << std::dec
          << static_cast<int>(header[2]) << ", expected 0x" << std::hex
          << static_cast<int>(command) << '/' << std::dec
          << static_cast<int>(motor_id);
      error = out.str();
      return false;
    }
    return true;
  }
  error = "could not synchronize to response frame header";
  return false;
}

void Mf9025v2Bus::drain_input() {
  uint8_t buffer[256];
  while (fd_ >= 0) {
    ssize_t count = ::read(fd_, buffer, sizeof(buffer));
    if (count > 0) continue;
    if (count < 0 && errno == EINTR) continue;
    break;
  }
}

uint8_t Mf9025v2Bus::checksum(const uint8_t* data, std::size_t size) {
  uint8_t value = 0;
  for (std::size_t i = 0; i < size; ++i) value = static_cast<uint8_t>(value + data[i]);
  return value;
}

int16_t Mf9025v2Bus::read_i16_le(const uint8_t* data) {
  return static_cast<int16_t>(read_u16_le(data));
}

uint16_t Mf9025v2Bus::read_u16_le(const uint8_t* data) {
  return static_cast<uint16_t>(static_cast<uint16_t>(data[0]) |
                               (static_cast<uint16_t>(data[1]) << 8));
}

int64_t Mf9025v2Bus::read_i64_le(const uint8_t* data) {
  uint64_t value = 0;
  for (int i = 0; i < 8; ++i) {
    value |= static_cast<uint64_t>(data[i]) << (i * 8);
  }
  return static_cast<int64_t>(value);
}

uint32_t Mf9025v2Bus::read_u32_le(const uint8_t* data) {
  uint32_t value = 0;
  for (int i = 0; i < 4; ++i) {
    value |= static_cast<uint32_t>(data[i]) << (i * 8);
  }
  return value;
}

void Mf9025v2Bus::append_u32_le(std::vector<uint8_t>& out,
                                uint32_t value) {
  for (int i = 0; i < 4; ++i) {
    out.push_back(static_cast<uint8_t>((value >> (i * 8)) & 0xFF));
  }
}

void Mf9025v2Bus::append_i64_le(std::vector<uint8_t>& out, int64_t value) {
  const uint64_t raw = static_cast<uint64_t>(value);
  for (int i = 0; i < 8; ++i) {
    out.push_back(static_cast<uint8_t>((raw >> (i * 8)) & 0xFF));
  }
}

}  // namespace therapy_robot
