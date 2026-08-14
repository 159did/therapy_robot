cmake_minimum_required(VERSION 3.16)
project(therapy_robot VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_compile_options(-Wall -Wextra -Wpedantic)

include_directories(${CMAKE_SOURCE_DIR}/include ${CMAKE_SOURCE_DIR}/third_party)

add_library(therapy_robot_common STATIC
  src/common/collision.cpp
  src/common/kinematics.cpp
  src/common/shared_memory.cpp
  src/common/shared_memory_defaults.cpp
  src/common/time_utils.cpp
)

target_link_libraries(therapy_robot_common PUBLIC pthread rt)

add_library(therapy_robot_motor_driver STATIC
  src/motor/mf9025v2_driver.cpp
)

target_link_libraries(therapy_robot_motor_driver PUBLIC therapy_robot_common)

add_executable(main_core src/core/main_core.cpp)
target_link_libraries(main_core PRIVATE therapy_robot_common)

add_executable(main_control src/control/main_control.cpp)
target_link_libraries(main_control PRIVATE therapy_robot_common)

add_executable(main_motor src/motor/main_motor.cpp)
target_link_libraries(main_motor PRIVATE therapy_robot_common therapy_robot_motor_driver)

add_executable(main_sim src/sim/main_sim.cpp)
target_link_libraries(main_sim PRIVATE therapy_robot_common)

add_executable(main_web_control src/web/main_web.cpp)
target_link_libraries(main_web_control PRIVATE therapy_robot_common)

add_executable(main_web_sim src/web/main_web.cpp)
target_compile_definitions(main_web_sim PRIVATE THERAPY_ROBOT_WEB_SIM=1)
target_link_libraries(main_web_sim PRIVATE therapy_robot_common)

# Linaro GCC 7.5, used by the Jetson Nano toolchain, exposes C++17
# filesystem through libstdc++fs and <experimental/filesystem>.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9)
  target_link_libraries(main_web_control PRIVATE stdc++fs)
  target_link_libraries(main_web_sim PRIVATE stdc++fs)
endif()

install(TARGETS main_core main_control main_motor main_sim main_web_control main_web_sim RUNTIME DESTINATION bin)
install(DIRECTORY web/ DESTINATION web)

include(CTest)
if(BUILD_TESTING)
  add_executable(test_collision tests/test_collision.cpp)
  target_link_libraries(test_collision PRIVATE therapy_robot_common)
  add_test(NAME collision_geometry COMMAND test_collision)
  add_executable(test_kinematics tests/test_kinematics.cpp)
  target_link_libraries(test_kinematics PRIVATE therapy_robot_common)
  add_test(NAME kinematics_roundtrip COMMAND test_kinematics)
endif()
