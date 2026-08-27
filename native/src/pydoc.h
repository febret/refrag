// Translation of the Python room document into the plain C++ specs used by the
// render graph.  Everything here runs with the GIL held; nothing below does.
#pragma once

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include <vector>

#include "room.h"

namespace refrag {

namespace py = pybind11;

RoomSpec parse_room(const py::handle &doc, int fallback_sample_rate, int fallback_block_size);
std::vector<float> parse_sample_array(const py::handle &array);

}  // namespace refrag
