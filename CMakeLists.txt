cmake_minimum_required(VERSION 3.28)
project(refrag_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(pybind11 CONFIG REQUIRED)

pybind11_add_module(refrag_engine
  native/refrag_engine.cpp
  native/src/dsp.cpp
  native/src/spec.cpp
  native/src/expr.cpp
  native/src/effects.cpp
  native/src/machine.cpp
  native/src/machines_synth.cpp
  native/src/machines_extra.cpp
  native/src/mixer.cpp
  native/src/thread_pool.cpp
  native/src/room.cpp
  native/src/pydoc.cpp
)

target_include_directories(refrag_engine PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/native)

install(TARGETS refrag_engine LIBRARY DESTINATION .)

target_compile_options(refrag_engine PRIVATE
  $<$<CXX_COMPILER_ID:MSVC>:/O2>
  $<$<CXX_COMPILER_ID:MSVC>:/fp:fast>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-O3>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-march=native>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-ffast-math>
  # -ffast-math implies -ffinite-math-only, which lets GCC/Clang fold away the
  # std::isfinite() guards the render path relies on to sanitise NaN/Inf. Keep
  # the rest of the fast-math relaxations, but restore honest NaN/Inf handling.
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-fno-finite-math-only>
)
