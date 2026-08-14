#include "therapy_robot/shared_memory.hpp"

#include <cerrno>
#include <chrono>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace therapy_robot {

void set_text(char* dst, unsigned long size, const char* src) {
  if (!dst || size == 0) return;
  std::snprintf(dst, size, "%s", src ? src : "");
}

uint64_t now_ms() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

SharedState* open_or_create_shared_state(bool create) {
  int flags = O_RDWR | (create ? O_CREAT : 0);
  int fd = shm_open(kSharedMemoryName, flags, 0666);
  if (fd < 0) {
    throw std::runtime_error(std::string("shm_open failed: ") + std::strerror(errno));
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