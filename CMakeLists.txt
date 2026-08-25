cmake_minimum_required(VERSION 3.16)
project(therapy_robot VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_compile_options(-Wall -Wextra -Wpedantic)

include_directories(${CMAKE_SOURCE_DIR}/include ${CMAKE_SOURCE_DIR}/third_party)

add_library(therapy_robot_common STATIC
  src/common/collision.cpp
  src/common/control_safety_gate.cpp
  src/common/endpoint_positioning.cpp
  src/common/joint_limits.cpp
  src/common/kinematics.cpp
  src/common/motion_plan.cpp
  src/common/readiness.cpp
  src/common/shared_memory.cpp
  src/common/shared_memory_defaults.cpp
  src/common/time_utils.cpp
  src/common/workflow.cpp
  src/common/k0_prepare_sim.cpp
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

add_executable(h1_readonly_collector tools/h1_readonly_collector.cpp)
target_link_libraries(h1_readonly_collector PRIVATE therapy_robot_motor_driver)

add_executable(endpoint_positioning_report tools/endpoint_positioning_report.cpp)
target_link_libraries(endpoint_positioning_report PRIVATE therapy_robot_common)

# Linaro GCC 7.5, used by the Jetson Nano toolchain, exposes C++17
# filesystem through libstdc++fs and <experimental/filesystem>.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 9)
  target_link_libraries(main_web_control PRIVATE stdc++fs)
  target_link_libraries(main_web_sim PRIVATE stdc++fs)
endif()

install(TARGETS main_core main_control main_motor main_sim main_web_control main_web_sim h1_readonly_collector endpoint_positioning_report RUNTIME DESTINATION bin)
install(DIRECTORY web/ DESTINATION web)

include(CTest)
if(BUILD_TESTING)
  find_package(Python3 REQUIRED COMPONENTS Interpreter)
  add_executable(test_collision tests/test_collision.cpp)
  target_link_libraries(test_collision PRIVATE therapy_robot_common)
  add_test(NAME collision_geometry COMMAND test_collision)
  add_executable(test_kinematics tests/test_kinematics.cpp)
  target_link_libraries(test_kinematics PRIVATE therapy_robot_common)
  add_test(NAME kinematics_roundtrip COMMAND test_kinematics)
  add_executable(test_motion_plan tests/test_motion_plan.cpp)
  target_link_libraries(test_motion_plan PRIVATE therapy_robot_common)
  add_test(NAME motion_plan COMMAND test_motion_plan)
  add_executable(test_workflow tests/test_workflow.cpp)
  target_link_libraries(test_workflow PRIVATE therapy_robot_common)
  add_test(NAME workflow_model COMMAND test_workflow)
  add_executable(test_k0_prepare_sim tests/test_k0_prepare_sim.cpp)
  target_link_libraries(test_k0_prepare_sim PRIVATE therapy_robot_common)
  add_test(NAME k0_prepare_sim COMMAND test_k0_prepare_sim)
  add_executable(test_readiness tests/test_readiness.cpp)
  target_link_libraries(test_readiness PRIVATE therapy_robot_common)
  add_test(NAME readiness_attestation COMMAND test_readiness)
  add_executable(test_control_safety_gate tests/test_control_safety_gate.cpp)
  target_link_libraries(test_control_safety_gate PRIVATE therapy_robot_common)
  add_test(NAME control_safety_gate COMMAND test_control_safety_gate)
  add_executable(test_endpoint_positioning tests/test_endpoint_positioning.cpp)
  target_link_libraries(test_endpoint_positioning PRIVATE therapy_robot_common)
  add_test(NAME endpoint_positioning COMMAND test_endpoint_positioning)
  add_test(
    NAME control_safety_gate_integration
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_SOURCE_DIR}/tests/test_control_safety_gate_integration.py
            --root ${CMAKE_SOURCE_DIR}
  )
  add_test(
    NAME control_safety_gate_api
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_SOURCE_DIR}/tests/test_control_safety_gate_api.py
            --main-core $<TARGET_FILE:main_core>
            --main-web-control $<TARGET_FILE:main_web_control>
  )
  add_test(
    NAME shared_memory_isolation
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_shared_memory_isolation.py
            --main-core $<TARGET_FILE:main_core>
  )
  add_test(
    NAME runtime_isolation
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_runtime_isolation.py
            --main-core $<TARGET_FILE:main_core>
            --main-web-control $<TARGET_FILE:main_web_control>
            --kill-script ${CMAKE_SOURCE_DIR}/scripts/kill-robot.sh
  )
  add_test(
    NAME interface_contract
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_interface_contract.py
            --root ${CMAKE_SOURCE_DIR}
  )
  add_test(
    NAME workflow_api
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_workflow_api.py
            --main-core $<TARGET_FILE:main_core>
            --main-web-control $<TARGET_FILE:main_web_control>
  )
  add_test(
    NAME motion_plan_api
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_motion_plan_api.py
            --main-core $<TARGET_FILE:main_core>
            --main-web-control $<TARGET_FILE:main_web_control>
  )
  add_test(
    NAME readiness_api
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_readiness_api.py
            --main-core $<TARGET_FILE:main_core>
            --main-web-control $<TARGET_FILE:main_web_control>
  )
  add_test(
    NAME b3_audit_report
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_b3_audit_report.py
  )
  add_test(
    NAME readiness_frontend
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_readiness_frontend.py
            --root ${CMAKE_SOURCE_DIR}
  )
  add_test(
    NAME d405_quality_gate
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_SOURCE_DIR}/tests/test_d405_quality_gate.py
  )
  add_test(
    NAME camera_extrinsics_candidate
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_SOURCE_DIR}/tests/test_camera_extrinsics_candidate.py
  )
  add_test(
    NAME workflow_frontend
    COMMAND ${Python3_EXECUTABLE}
            ${CMAKE_SOURCE_DIR}/tests/test_workflow_frontend.py
            --root ${CMAKE_SOURCE_DIR}
  )
  add_test(
    NAME capture_d405_contract
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_capture_d405.py
  )
  add_test(
    NAME experiment_workflow_contract
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_experiment_workflow.py
  )
  add_test(
    NAME h1_readonly_collector_source_contract
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/tests/test_h1_readonly_collector.py
            --root ${CMAKE_SOURCE_DIR}
  )
endif()
