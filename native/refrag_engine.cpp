// pybind11 bindings for the Refrag native audio engine.
//
// The persistent room graph is the only supported render interface:
// create_room_engine(...) returns a RoomEngine that owns every machine,
// effect, mixer strip and the master section for one room.  Status is
// reported as a plain dict of lists so no other Python types are exposed.
#include <cstddef>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>

#include "src/pydoc.h"
#include "src/room.h"

namespace py = pybind11;

namespace {

using refrag::RoomEngine;
using refrag::RoomSpec;

py::array_t<float> make_planar(std::size_t frames) {
    return py::array_t<float>(std::vector<py::ssize_t>{2, static_cast<py::ssize_t>(frames)});
}

std::size_t check_frames(long long frames) {
    if (frames < 0) {
        throw std::invalid_argument("frame count must not be negative");
    }
    if (frames > (1 << 22)) {
        throw std::invalid_argument("frame count is unreasonably large");
    }
    return static_cast<std::size_t>(frames);
}

class PyRoomEngine {
  public:
    PyRoomEngine(int sample_rate, int block_size, int slot_count)
        : engine_(sample_rate, block_size, slot_count) {}

    void register_sample(const std::string &name, const py::handle &data, double source_rate) {
        if (source_rate <= 0.0) {
            throw std::invalid_argument("source_rate must be positive");
        }
        engine_.register_sample(name, refrag::parse_sample_array(data), source_rate);
    }

    void sync(const py::handle &doc) {
        RoomSpec spec = refrag::parse_room(doc, engine_.sample_rate(), engine_.block_size());
        engine_.sync(spec);
    }

    void note_on(int slot, int note, float vel, int offset, int flags) {
        engine_.note_on(slot, note, vel, offset, flags);
    }
    void note_off(int slot, int note, int offset) { engine_.note_off(slot, note, offset); }
    void all_off(int slot) { engine_.all_off(slot); }
    bool active() const { return engine_.active(); }

    py::array_t<float> render(long long frames_in, double bpm) {
        std::size_t frames = check_frames(frames_in);
        py::array_t<float> out = make_planar(frames);
        float *l = out.mutable_data();
        float *r = l + frames;
        {
            py::gil_scoped_release release;
            engine_.render(l, r, frames, bpm);
        }
        return out;
    }

    py::dict status() const {
        py::dict out;
        py::list vu;
        for (float v : engine_.slot_vu()) {
            vu.append(v);
        }
        out["slot_vu"] = vu;
        py::list voice_counts;
        for (int count : engine_.slot_voice_counts()) {
            voice_counts.append(count);
        }
        out["slot_voice_counts"] = voice_counts;
        py::list master;
        master.append(engine_.master_vu_left());
        master.append(engine_.master_vu_right());
        out["master_vu"] = master;
        out["lim_gr"] = engine_.limiter_gr();
        py::dict vocoder;
        for (const auto &entry : engine_.vocoder_vu()) {
            py::list bands;
            for (float v : entry.second) {
                bands.append(v);
            }
            vocoder[py::str(std::to_string(entry.first))] = bands;
        }
        out["vocoder_vu"] = vocoder;
        out["has_tail"] = engine_.has_tail();
        out["sample_rate"] = engine_.sample_rate();
        out["block_size"] = engine_.block_size();
        return out;
    }

    int sample_rate() const { return engine_.sample_rate(); }
    int block_size() const { return engine_.block_size(); }
    int slot_count() const { return engine_.slot_count(); }

  private:
    RoomEngine engine_;
};

}  // namespace

PYBIND11_MODULE(refrag_engine, m) {
    m.doc() = "Refrag native audio engine";

    py::register_exception_translator([](std::exception_ptr p) {
        try {
            if (p) {
                std::rethrow_exception(p);
            }
        } catch (const std::invalid_argument &e) {
            PyErr_SetString(PyExc_ValueError, e.what());
        } catch (const std::out_of_range &e) {
            PyErr_SetString(PyExc_IndexError, e.what());
        }
    });

    py::class_<PyRoomEngine, std::shared_ptr<PyRoomEngine>>(m, "RoomEngine")
        .def("register_sample", &PyRoomEngine::register_sample, py::arg("name"), py::arg("data"),
             py::arg("source_rate") = 44100.0)
        .def("sync", &PyRoomEngine::sync, py::arg("doc"))
        .def("note_on", &PyRoomEngine::note_on, py::arg("slot"), py::arg("note"), py::arg("vel"),
             py::arg("offset") = 0, py::arg("flags") = 0)
        .def("note_off", &PyRoomEngine::note_off, py::arg("slot"), py::arg("note"),
             py::arg("offset") = 0)
        .def("all_off", &PyRoomEngine::all_off, py::arg("slot") = -1)
        .def("active", &PyRoomEngine::active)
        .def("render", &PyRoomEngine::render, py::arg("frames"), py::arg("bpm") = 120.0)
        .def("status", &PyRoomEngine::status)
        .def_property_readonly("sample_rate", &PyRoomEngine::sample_rate)
        .def_property_readonly("block_size", &PyRoomEngine::block_size)
        .def_property_readonly("slot_count", &PyRoomEngine::slot_count);

    m.def(
        "create_room_engine",
        [](int sample_rate, int block_size, int slot_count) {
            return std::make_shared<PyRoomEngine>(sample_rate, block_size, slot_count);
        },
        py::arg("sample_rate"), py::arg("block_size"), py::arg("slot_count"));
}
