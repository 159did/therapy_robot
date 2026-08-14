#include "therapy_robot/shared_memory.hpp"

#include <cerrno>
#include <chrono>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace therapy_robot {

namespace {

constexpr std::size_t kMaxSharedMemoryNameLength = 255;

bool is_safe_shared_memory_character(char value) {
  return (value >= 'a' && value <= 'z') ||
         (value >= 'A' && value <= 'Z') ||
         (value >= '0' && value <= '9') || value == '_' || value == '-' ||
         value == '.';
}

void validate_shared_memory_name(const char* name) {
  const std::size_t length = name ? std::strlen(name) : 0;
  if (length < 2 || length > kMaxSharedMemoryNameLength || name[0] != '/' ||
      std::strcmp(name, "/.") == 0 || std::strcmp(name, "/..") == 0) {
    throw std::invalid_argument(
        "invalid THERAPY_ROBOT_SHM_NAME: expected '/' followed by 1-254 "
        "safe characters");
  }
  for (std::size_t index = 1; index < length; ++index) {
    if (!is_safe_shared_memory_character(name[index])) {
      throw std::invalid_argument(
          "invalid THERAPY_ROBOT_SHM_NAME: allowed characters after '/' are "
          "ASCII letters, digits, '_', '-' and '.'");
    }
  }
}

}  // namespace

void set_text(char* dst, unsigned long size, const char* src) {
  if (!dst || size == 0) return;
  std::snprintf(dst, size, "%s", src ? src : "");
}

uint64_t now_ms() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

const char* shared_memory_name() {
  const char* configured = std::getenv("THERAPY_ROBOT_SHM_NAME");
  const char* name = configured ? configured : kDefaultSharedMemoryName;
  validate_shared_memory_name(name);
  return name;
}

SharedState* open_or_create_shared_state(bool create) {
  const char* name = shared_memory_name();
  int flags = O_RDWR | (create ? O_CREAT : 0);
  int fd = shm_open(name, flags, 0666);
  if (fd < 0) {
    throw std::runtime_error(std::string("shm_open failed for ") + name + ": " +
                             std::strerror(errno));
  }
  if (create && ftruncate(fd, sizeof(SharedState)) != 0) {
    int e = errno;
    close(fd);
    throw std::runtime_error(std::string("ftruncate failed: ") + std::strerror(e));
  }
  void* ptr = mmap(nullptr, sizeof(SharedState), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
  int e = errno;
  close(fd);
  if (ptr == MAP_FAILED) {
    throw std::runtime_error(std::string("mmap failed: ") + std::strerror(e));
  }
  return static_cast<SharedState*>(ptr);
}

}
