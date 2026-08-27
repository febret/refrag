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
)

install(TARGETS refrag_engine LIBRARY DESTINATION .)

target_compile_options(refrag_engine PRIVATE
  $<$<CXX_COMPILER_ID:MSVC>:/O2>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-O3>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-march=native>
  $<$<NOT:$<CXX_COMPILER_ID:MSVC>>:-ffast-math>
)
