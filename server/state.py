"""Collaborative room state and persistence for Refrag.

A Room owns a JSON-serializable document describing the entire rack:
machines, their parameters, patterns, effects, mixer strips, master
section, song sequence and automation.  Mutations arrive as small
"op" dicts (usually via the WebSocket) and are applied atomically,
then re-broadcast to every connected client.
"""

import copy
import json
import os
import re
import threading
import time

from . import catalog, flourish

MAX_MACHINES = 14
BANKS = ["A", "B", "C", "D"]
PATTERNS_PER_BANK = 16
BEATS_PER_MEASURE = 4
AUDIO_SAMPLE_RATES = [22050, 32000, 44100, 48000, 88200, 96000]
AUDIO_BLOCK_SIZES = [256, 512, 1024, 2048, 4096]
AUDIO_DEFAULT_SAMPLE_RATE = 44100
AUDIO_DEFAULT_BLOCK_SIZE = 2048

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SESSION_DIR = os.path.join(DATA_DIR, "sessions")
PRESET_DIR = os.path.join(DATA_DIR, "presets")
SAMPLE_DIR = os.path.join(DATA_DIR, "samples")

DEFAULT_BEATBOX_KIT = ["kick", "snare", "clhat", "ophat", "clap",
                       "tom_lo", "tom_hi", "crash"]


def _safe_name(name):
    name = re.sub(r"[^A-Za-z0-9 _\-\.]", "", str(name)).strip()
    return name[:48] or "untitled"


def new_pattern():
    return {"length": 1, "notes": []}   # length in measures; notes: [key, start, dur, vel, flags]


def _clamp_transpose(value):
    return max(-24, min(24, int(value)))


def _normalize_transpose_steps(m):
    legacy = _clamp_transpose(m.get("transpose", 0))
    raw = m.get("transpose_steps")
    if not isinstance(raw, list) or len(raw) != 4:
        raw = [{"transpose": legacy, "loops": 1} for _ in range(4)]
    steps = []
    for item in raw[:4]:
        if not isinstance(item, dict):
            item = {}
        steps.append({
            "transpose": _clamp_transpose(item.get("transpose", legacy)),
            "loops": max(1, min(4, int(item.get("loops", 1)))),
        })
    while len(steps) < 4:
        steps.append({"transpose": legacy, "loops": 1})
    m["transpose_steps"] = steps
    m["transpose"] = steps[0]["transpose"]


def _normalize_looper_settings(m):
    m["looper_bank"] = max(
        0, min(len(BANKS) - 1, int(m.get("looper_bank", m.get("bank", 0)))))
    mode = m.get("looper_mode", "queue")
    m["looper_mode"] = mode if mode in ("queue", "random") else "queue"


def _normalize_audio_settings(doc):
    audio = doc.get("audio")
    if not isinstance(audio, dict):
        audio = {}
    sr = int(audio.get("sample_rate", AUDIO_DEFAULT_SAMPLE_RATE))
    block = int(audio.get("block_size", AUDIO_DEFAULT_BLOCK_SIZE))
    if sr not in AUDIO_SAMPLE_RATES:
        sr = AUDIO_DEFAULT_SAMPLE_RATE
    if block not in AUDIO_BLOCK_SIZES:
        block = AUDIO_DEFAULT_BLOCK_SIZE
    doc["audio"] = {"sample_rate": sr, "block_size": block}


def new_machine(mtype, name=None):
    spec = catalog.MACHINES[mtype]
    m = {
        "type": mtype,
        "name": name or spec["name"].upper(),
        "params": catalog.default_params(spec["controls"]),
        "poly": spec["poly"],
        "mute": 0,
        "solo": 0,
        "octave": 4,
        "bank": 0,
        "pattern": 0,
        "transpose": 0,
        "transpose_steps": [{"transpose": 0, "loops": 1} for _ in range(4)],
        "looper_bank": 0,
        "looper_mode": "queue",
        "patterns": {},          # "A1".."D16" -> pattern
        "effects": [None, None],  # {type, params, bypass}
        "mixer": catalog.default_params(catalog.MIXER_STRIP),
        "preset": "",
    }
    if mtype == "beatbox":
        m["channels"] = [
            {"sample": DEFAULT_BEATBOX_KIT[i],
             "params": catalog.default_params(spec["channel_controls"]),
             "mute": 0, "solo": 0, "mute_group": 0}
            for i in range(8)
        ]
    if mtype == "pcmsynth":
        m["samples"] = [
            {"sample": "piano", "level": 1.0, "tune": 0, "pan": 0.0,
             "root": 60, "low": 0, "high": 127, "mode": 0,
             "start": 0.0, "end": 1.0}
        ]
        m["sample_sel"] = 0
    if mtype == "padsynth":
        n = spec["harmonics"]
        h1 = [1.0] + [0.0] * (n - 1)
        h2 = [1.0 / (i + 1) for i in range(n)]
        m["harm1"] = h1
        m["harm2"] = h2
        m["width1"] = 0.3
        m["width2"] = 0.3
    if mtype == "bitsynth":
        m["expr_a"] = spec["expression_default"]
        m["expr_b"] = "(t>>4)|(t<<2)"
        m["expr_sel"] = 0
    if mtype == "modular":
        m["components"] = [None] * spec["bays"]   # {type, params}
        m["wires"] = []   # [fromJack, toJack] with jack ids like "c0.out" / "panel.left_out"
    if mtype == "vocoder":
        m["modulators"] = [{"source": "", "machine": -1} for _ in range(6)]
        m["mod_sel"] = 0
    return m


def new_room_doc():
    return {
        "version": 1,
        "name": "untitled",
        "bpm": 120,
        "shuffle_mode": 0,       # 0 = 8th (march), 1 = 16th (swing)
        "shuffle": 0.0,
        "machines": [None] * MAX_MACHINES,
        "master": {
            "params": catalog.default_params(catalog.MASTER),
            "effects": [None, None],
        },
        "transport": {
            "playing": False,
            "mode": "pattern",    # or "song"
            "record": False,
            "pos": 0.0,           # beats
            "start_pos": 0.0,
            "loop": None,         # [start_measure, end_measure]
        },
        "audio": {
            "sample_rate": AUDIO_DEFAULT_SAMPLE_RATE,
            "block_size": AUDIO_DEFAULT_BLOCK_SIZE,
        },
        "song": [],               # blocks: {id, machine, bank, pattern, start, length} (measures)
        # automation:
        #   pattern: "slot:BANKPAT:param" -> {"bars": [...], "smooth": 0.5}
        #   song:    "slot:param" -> {"keys": [[beat, value], ...]}
        "automation": {"pattern": {}, "song": {}},
    }


class Room:
    def __init__(self, room_id):
        self.id = room_id
        self.doc = new_room_doc()
        self.lock = threading.RLock()
        self.rev = 0
        self.dirty = False
        self._last_save = 0.0
        self.listeners = set()          # ws connections managed by app.py
        self.engine = None              # attached by the audio engine
        self.runtime_only = False
        self.load()

    # -- persistence --------------------------------------------------------

    @property
    def path(self):
        return os.path.join(SESSION_DIR, _safe_name(self.id) + ".json")

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            base = new_room_doc()
            base.update(doc)
            _normalize_audio_settings(base)
            for m in base["machines"]:
                if m is not None:
                    _normalize_transpose_steps(m)
                    _normalize_looper_settings(m)
            base["transport"]["playing"] = False
            base["transport"]["record"] = False
            self.doc = base
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def save(self, force=False):
        with self.lock:
            if not self.dirty and not force:
                return
            os.makedirs(SESSION_DIR, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.doc, f)
            os.replace(tmp, self.path)
            self.dirty = False
            self._last_save = time.time()

    def maybe_save(self):
        if self.dirty and time.time() - self._last_save > 2.0:
            self.save()

    # -- helpers -------------------------------------------------------------

    def machine(self, slot):
        if 0 <= slot < MAX_MACHINES:
            return self.doc["machines"][slot]
        return None

    def pattern_key(self, m):
        return BANKS[m["bank"]] + str(m["pattern"] + 1)

    def get_pattern(self, m, key=None, create=False):
        key = key or self.pattern_key(m)
        pat = m["patterns"].get(key)
        if pat is None and create:
            pat = new_pattern()
            m["patterns"][key] = pat
        return pat

    # -- op application ------------------------------------------------------

    def apply(self, op):
        """Apply an op dict; returns True if the doc changed (=> broadcast)."""
        with self.lock:
            self.runtime_only = False
            fn = getattr(self, "_op_" + op.get("op", ""), None)
            if fn is None:
                return False
            changed = fn(op)
            if changed and not self.runtime_only:
                self.mark_changed()
            return changed

    def mark_changed(self):
        self.rev += 1
        self.dirty = True

    # machines ---------------------------------------------------------------

    def _op_add_machine(self, op):
        slot = int(op["slot"])
        mtype = op["mtype"]
        if mtype not in catalog.MACHINES or not 0 <= slot < MAX_MACHINES:
            return False
        self.doc["machines"][slot] = new_machine(mtype, op.get("name"))
        return True

    def _op_remove_machine(self, op):
        slot = int(op["slot"])
        if self.machine(slot) is None:
            return False
        self.doc["machines"][slot] = None
        self._drop_automation(slot)
        self.doc["song"] = [b for b in self.doc["song"] if b["machine"] != slot]
        return True

    def _op_move_machine(self, op):
        a, b = int(op["from"]), int(op["to"])
        ms = self.doc["machines"]
        if not (0 <= a < MAX_MACHINES and 0 <= b < MAX_MACHINES) or ms[a] is None:
            return False
        ms[a], ms[b] = ms[b], ms[a]
        for blk in self.doc["song"]:
            if blk["machine"] == a:
                blk["machine"] = b
            elif blk["machine"] == b:
                blk["machine"] = a
        self._swap_automation(a, b)
        return True

    def _op_replace_machine(self, op):
        slot = int(op["slot"])
        old = self.machine(slot)
        if old is None or op["mtype"] not in catalog.MACHINES:
            return False
        m = new_machine(op["mtype"])
        m["patterns"] = old["patterns"]
        m["bank"], m["pattern"] = old["bank"], old["pattern"]
        m["transpose"] = _clamp_transpose(old.get("transpose", 0))
        m["transpose_steps"] = copy.deepcopy(old.get("transpose_steps", m["transpose_steps"]))
        _normalize_transpose_steps(m)
        m["looper_bank"] = max(0, min(len(BANKS) - 1, int(old.get("looper_bank", old.get("bank", 0)))))
        old_mode = old.get("looper_mode", "queue")
        m["looper_mode"] = old_mode if old_mode in ("queue", "random") else "queue"
        m["mixer"] = old["mixer"]
        m["effects"] = old["effects"]
        self.doc["machines"][slot] = m
        self._drop_automation(slot)
        return True

    def _op_rename_machine(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        m["name"] = _safe_name(op["name"]).upper() or m["name"]
        return True

    def _drop_automation(self, slot):
        for scope in ("pattern", "song"):
            table = self.doc["automation"][scope]
            for k in [k for k in table if k.startswith(f"{slot}:")]:
                del table[k]

    def _swap_automation(self, a, b):
        for scope in ("pattern", "song"):
            table = self.doc["automation"][scope]
            out = {}
            for k, v in table.items():
                slot, rest = k.split(":", 1)
                slot = int(slot)
                slot = b if slot == a else (a if slot == b else slot)
                out[f"{slot}:{rest}"] = v
            self.doc["automation"][scope] = out

    # parameters ---------------------------------------------------------------

    def _op_set_param(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or op["param"] not in m["params"]:
            return False
        m["params"][op["param"]] = op["value"]
        self._maybe_record_automation(int(op["slot"]), op["param"], op["value"])
        return True

    def _op_set_channel_param(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "channels" not in m:
            return False
        ch = m["channels"][int(op["channel"])]
        if op["param"] in ("mute", "solo", "mute_group"):
            ch[op["param"]] = op["value"]
        elif op["param"] == "sample":
            ch["sample"] = str(op["value"])
        else:
            ch["params"][op["param"]] = op["value"]
        return True

    def _op_set_sample_param(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "samples" not in m:
            return False
        idx = int(op["index"])
        if op["param"] == "add":
            m["samples"].append({"sample": str(op["value"]), "level": 1.0,
                                 "tune": 0, "pan": 0.0, "root": 60, "low": 0,
                                 "high": 127, "mode": 0, "start": 0.0, "end": 1.0})
            m["sample_sel"] = len(m["samples"]) - 1
            return True
        if not 0 <= idx < len(m["samples"]):
            return False
        if op["param"] == "remove":
            if len(m["samples"]) <= 1:
                return False
            m["samples"].pop(idx)
            m["sample_sel"] = max(0, m["sample_sel"] - 1)
            return True
        if op["param"] == "select":
            m["sample_sel"] = idx
            return True
        m["samples"][idx][op["param"]] = op["value"]
        return True

    def _op_set_machine_prop(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        prop = op["prop"]
        if prop in ("mute", "solo", "poly", "octave", "expr_a", "expr_b",
                    "expr_sel", "mod_sel", "width1", "width2", "preset"):
            m[prop] = op["value"]
            return True
        if prop in ("harm1", "harm2") and isinstance(op["value"], list):
            m[prop] = [max(0.0, min(1.0, float(v))) for v in op["value"]]
            return True
        return False

    def _op_set_harmonic(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or op["table"] not in ("harm1", "harm2"):
            return False
        idx = int(op["index"])
        if 0 <= idx < len(m[op["table"]]):
            m[op["table"]][idx] = max(0.0, min(1.0, float(op["value"])))
            return True
        return False

    def _op_set_modulator(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "modulators" not in m:
            return False
        mod = m["modulators"][int(op["index"])]
        mod["source"] = op.get("source", mod["source"])
        mod["machine"] = op.get("machine", mod["machine"])
        return True

    # modular ------------------------------------------------------------------

    def _op_mod_place(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "components" not in m:
            return False
        bay = int(op["bay"])
        ctype = op["ctype"]
        spec = catalog.MODULAR_COMPONENTS.get(ctype)
        if spec is None or not 0 <= bay < len(m["components"]):
            return False
        size = spec["size"]
        if bay + size > len(m["components"]):
            return False
        for i in range(bay, bay + size):
            c = m["components"][i]
            if c is not None and c != "occupied":
                return False
            if c == "occupied":
                return False
        m["components"][bay] = {"type": ctype,
                                "params": catalog.default_params(spec["controls"])}
        for i in range(bay + 1, bay + size):
            m["components"][i] = "occupied"
        return True

    def _op_mod_remove(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "components" not in m:
            return False
        bay = int(op["bay"])
        comp = m["components"][bay]
        if comp is None or comp == "occupied":
            return False
        size = catalog.MODULAR_COMPONENTS[comp["type"]]["size"]
        for i in range(bay, bay + size):
            m["components"][i] = None
        pref = f"c{bay}."
        m["wires"] = [w for w in m["wires"]
                      if not (w[0].startswith(pref) or w[1].startswith(pref))]
        return True

    def _op_mod_param(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "components" not in m:
            return False
        comp = m["components"][int(op["bay"])]
        if not isinstance(comp, dict) or op["param"] not in comp["params"]:
            return False
        comp["params"][op["param"]] = op["value"]
        return True

    def _op_mod_wire(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or "wires" not in m:
            return False
        wire = [str(op["src"]), str(op["dst"])]
        if op.get("remove"):
            if wire in m["wires"]:
                m["wires"].remove(wire)
                return True
            return False
        # one wire per input jack
        m["wires"] = [w for w in m["wires"] if w[1] != wire[1]]
        m["wires"].append(wire)
        return True

    # effects -------------------------------------------------------------------

    def _effects_list(self, op):
        if op.get("target") == "master":
            return self.doc["master"]["effects"]
        m = self.machine(int(op["slot"]))
        return None if m is None else m["effects"]

    def _op_set_effect(self, op):
        fx = self._effects_list(op)
        idx = int(op["index"])
        if fx is None or not 0 <= idx < 2:
            return False
        etype = op.get("etype")
        if etype is None:
            fx[idx] = None
            return True
        if etype not in catalog.EFFECTS:
            return False
        fx[idx] = {"type": etype, "bypass": 0,
                   "params": catalog.default_params(catalog.EFFECTS[etype]["controls"])}
        return True

    def _op_set_effect_param(self, op):
        fx = self._effects_list(op)
        idx = int(op["index"])
        if fx is None or fx[idx] is None:
            return False
        if op["param"] == "bypass":
            fx[idx]["bypass"] = op["value"]
            return True
        if op["param"] not in fx[idx]["params"]:
            return False
        fx[idx]["params"][op["param"]] = op["value"]
        return True

    # mixer / master ---------------------------------------------------------

    def _op_set_mixer(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        if op["param"] in ("mute", "solo"):
            m[op["param"]] = op["value"]
            return True
        if op["param"] not in m["mixer"]:
            return False
        m["mixer"][op["param"]] = op["value"]
        self._maybe_record_automation(int(op["slot"]), "mixer." + op["param"], op["value"])
        return True

    def _op_set_master(self, op):
        p = self.doc["master"]["params"]
        if op["param"] not in p:
            return False
        p[op["param"]] = op["value"]
        self._maybe_record_automation(-1, op["param"], op["value"])
        return True

    # patterns ------------------------------------------------------------------

    def _op_select_pattern(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        m["bank"] = max(0, min(3, int(op.get("bank", m["bank"]))))
        m["pattern"] = max(0, min(15, int(op.get("pattern", m["pattern"]))))
        return True

    def _op_looper_pattern(self, op):
        slot = int(op["slot"])
        m = self.machine(slot)
        if m is None:
            return False
        bank = int(op["bank"])
        pattern = int(op["pattern"])
        if not 0 <= bank < len(BANKS) or not 0 <= pattern < PATTERNS_PER_BANK:
            return False
        if self.engine is None:
            m["bank"], m["pattern"] = bank, pattern
            self.doc["transport"]["mode"] = "pattern"
            return True
        result = self.engine.request_pattern(slot, bank, pattern)
        if result == "runtime":
            self.runtime_only = True
        return bool(result)

    def _op_looper_set_mode(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        mode = op.get("mode")
        if mode not in ("queue", "random"):
            return False
        if mode == m.get("looper_mode", "queue"):
            return False
        m["looper_mode"] = mode
        if self.engine:
            self.engine.set_looper_mode(int(op["slot"]), mode)
        return True

    def _op_looper_set_bank(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        bank = max(0, min(len(BANKS) - 1, int(op["bank"])))
        if bank == m.get("looper_bank", m.get("bank", 0)):
            return False
        m["looper_bank"] = bank
        return True

    def _op_looper_clear_queue(self, op):
        slot = int(op["slot"])
        if self.machine(slot) is None:
            return False
        if self.engine is None:
            return False
        cleared = self.engine.clear_pattern_queue(slot)
        if cleared:
            self.runtime_only = True
        return cleared

    def _op_set_transpose(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or m["type"] == "beatbox":
            return False
        value = _clamp_transpose(op["value"])
        _normalize_transpose_steps(m)
        changed = m.get("transpose", 0) != value
        for step in m["transpose_steps"]:
            if step["transpose"] != value:
                step["transpose"] = value
                changed = True
        m["transpose"] = value
        return changed

    def _op_set_transpose_step(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or m["type"] == "beatbox":
            return False
        step_idx = int(op["step"])
        if not 0 <= step_idx < 4:
            return False
        _normalize_transpose_steps(m)
        step = m["transpose_steps"][step_idx]
        changed = False
        if "transpose" in op:
            transpose = _clamp_transpose(op["transpose"])
            if transpose != step["transpose"]:
                step["transpose"] = transpose
                changed = True
        if "loops" in op:
            loops = max(1, min(4, int(op["loops"])))
            if loops != step["loops"]:
                step["loops"] = loops
                changed = True
        if changed:
            m["transpose"] = m["transpose_steps"][0]["transpose"]
        return changed

    def _op_set_pattern_length(self, op):
        m = self.machine(int(op["slot"]))
        if m is None or int(op["length"]) not in (1, 2, 4, 8):
            return False
        pat = self.get_pattern(m, op.get("key"), create=True)
        pat["length"] = int(op["length"])
        maxbeats = pat["length"] * BEATS_PER_MEASURE
        pat["notes"] = [n for n in pat["notes"] if n[1] < maxbeats]
        return True

    def _op_add_note(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"), create=True)
        note = [int(op["note"]), float(op["start"]), float(op["dur"]),
                float(op.get("vel", 1.0)), int(op.get("flags", 0))]
        maxbeats = pat["length"] * BEATS_PER_MEASURE
        if not 0 <= note[1] < maxbeats:
            return False
        note[2] = max(1 / 16, min(note[2], maxbeats - note[1]))
        pat["notes"].append(note)
        return True

    def _op_update_note(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        idx = int(op["index"])
        if pat is None or not 0 <= idx < len(pat["notes"]):
            return False
        n = pat["notes"][idx]
        for field, pos in (("note", 0), ("start", 1), ("dur", 2),
                           ("vel", 3), ("flags", 4)):
            if field in op:
                n[pos] = op[field]
        n[0] = int(n[0]); n[1] = float(n[1]); n[2] = float(n[2])
        return True

    def _op_remove_note(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        idx = int(op["index"])
        if pat is None or not 0 <= idx < len(pat["notes"]):
            return False
        pat["notes"].pop(idx)
        return True

    def _op_clear_pattern(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        if pat is None:
            return False
        pat["notes"] = []
        return True

    def _op_copy_pattern(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        src = m["patterns"].get(op["src"])
        if src is None:
            return False
        m["patterns"][op["dst"]] = copy.deepcopy(src)
        return True

    def _op_shift_pattern(self, op):
        """Shift notes in time (beats) or transpose (semitones)."""
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        if pat is None:
            return False
        dt = float(op.get("beats", 0))
        dn = int(op.get("semis", 0))
        span = pat["length"] * BEATS_PER_MEASURE
        for n in pat["notes"]:
            n[0] = max(0, min(127, n[0] + dn))
            n[1] = (n[1] + dt) % span
        return True

    def _op_set_pattern_notes(self, op):
        """Atomically replace a pattern's notes (and optionally its length).

        Used by AI Match to overwrite the current pattern in one op.
        """
        m = self.machine(int(op["slot"]))
        if m is None or not isinstance(op.get("notes"), list):
            return False
        pat = self.get_pattern(m, op.get("key"), create=True)
        if "length" in op:
            if int(op["length"]) not in (1, 2, 4, 8):
                return False
            pat["length"] = int(op["length"])
        maxbeats = pat["length"] * BEATS_PER_MEASURE
        notes = []
        for n in op["notes"]:
            try:
                key = max(0, min(127, int(n[0])))
                start = float(n[1])
                dur = float(n[2])
                vel = max(0.05, min(1.0, float(n[3]))) if len(n) > 3 else 1.0
                flags = int(n[4]) if len(n) > 4 else 0
            except (TypeError, ValueError, IndexError):
                return False
            if not 0 <= start < maxbeats:
                continue
            dur = max(1 / 16, min(dur, maxbeats - start))
            notes.append([key, start, dur, vel, flags])
        pat["notes"] = notes
        pat.pop("flourish", None)
        return True

    # flourish -------------------------------------------------------------------

    def _op_flourish(self, op):
        """Generate (or reroll) flourish notes for the current pattern."""
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        themes = [t for t in op.get("themes", []) if t in flourish.THEMES]
        pat = self.get_pattern(m, op.get("key"), create=True)
        seed = int(op.get("seed", 0))
        pat["notes"] = flourish.base_notes(pat)
        pat["notes"].extend(flourish.generate(pat, themes, seed,
                                              drum=m["type"] == "beatbox"))
        pat["flourish"] = {"on": 1, "themes": themes, "seed": seed}
        return True

    def _op_flourish_toggle(self, op):
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        if pat is None or "flourish" not in pat:
            return False
        pat["flourish"]["on"] = 1 if op.get("on", 1) else 0
        return True

    def _op_flourish_commit(self, op):
        """Turn one flourish note into a normal pattern note."""
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        idx = int(op["index"])
        if pat is None or not 0 <= idx < len(pat["notes"]):
            return False
        n = pat["notes"][idx]
        flags = int(n[4]) if len(n) > 4 else 0
        if not flags & flourish.FLAG:
            return False
        n[4] = flags & ~flourish.FLAG
        return True

    def _op_flourish_clear(self, op):
        """Remove all flourish notes and metadata from the pattern."""
        m = self.machine(int(op["slot"]))
        if m is None:
            return False
        pat = self.get_pattern(m, op.get("key"))
        if pat is None:
            return False
        before = len(pat["notes"])
        pat["notes"] = flourish.base_notes(pat)
        had_meta = pat.pop("flourish", None) is not None
        return had_meta or len(pat["notes"]) != before

    # song sequencer -------------------------------------------------------------

    def _op_song_add(self, op):
        slot = int(op["machine"])
        if self.machine(slot) is None:
            return False
        blk = {"id": int(time.time() * 1000) % 2_000_000_000 + len(self.doc["song"]),
               "machine": slot, "bank": int(op["bank"]),
               "pattern": int(op["pattern"]),
               "start": max(0, int(op["start"])),
               "length": max(1, int(op.get("length", 1)))}
        self.doc["song"].append(blk)
        return True

    def _op_song_update(self, op):
        for blk in self.doc["song"]:
            if blk["id"] == op["id"]:
                for f in ("start", "length", "bank", "pattern", "machine"):
                    if f in op:
                        blk[f] = int(op[f])
                blk["start"] = max(0, blk["start"])
                blk["length"] = max(1, blk["length"])
                return True
        return False

    def _op_song_remove(self, op):
        before = len(self.doc["song"])
        self.doc["song"] = [b for b in self.doc["song"] if b["id"] != op["id"]]
        return len(self.doc["song"]) != before

    def _op_song_clear(self, op):
        if not self.doc["song"]:
            return False
        self.doc["song"] = []
        return True

    # transport --------------------------------------------------------------------

    def _op_transport(self, op):
        t = self.doc["transport"]
        was_playing = t["playing"]
        old_mode = t["mode"]
        for f in ("playing", "mode", "record", "loop", "start_pos"):
            if f in op:
                t[f] = op[f]
        if "pos" in op:
            t["pos"] = float(op["pos"])
            if self.engine:
                self.engine.seek(float(op["pos"]))
        if op.get("playing") and self.engine:
            self.engine.wake()
        if self.engine:
            self.engine.transport_updated(was_playing, old_mode)
        return True

    def _op_set_song_prop(self, op):
        if op["prop"] == "bpm":
            self.doc["bpm"] = max(40, min(250, float(op["value"])))
        elif op["prop"] == "shuffle":
            self.doc["shuffle"] = max(0.0, min(1.0, float(op["value"])))
        elif op["prop"] == "shuffle_mode":
            self.doc["shuffle_mode"] = int(op["value"])
        elif op["prop"] == "name":
            self.doc["name"] = _safe_name(op["value"])
        else:
            return False
        return True

    def _op_set_audio_config(self, op):
        audio = self.doc["audio"]
        prop = op.get("prop")
        if prop == "sample_rate":
            value = int(op["value"])
            if value not in AUDIO_SAMPLE_RATES:
                return False
            if audio["sample_rate"] == value:
                return False
            audio["sample_rate"] = value
            return True
        if prop == "block_size":
            value = int(op["value"])
            if value not in AUDIO_BLOCK_SIZES:
                return False
            if audio["block_size"] == value:
                return False
            audio["block_size"] = value
            return True
        return False

    def _op_new_song(self, op):
        name = self.doc["name"]
        audio = copy.deepcopy(self.doc.get("audio"))
        self.doc = new_room_doc()
        self.doc["name"] = name
        if isinstance(audio, dict):
            self.doc["audio"] = audio
            _normalize_audio_settings(self.doc)
        return True

    # automation ----------------------------------------------------------------

    def _maybe_record_automation(self, slot, param, value):
        t = self.doc["transport"]
        if not (t["record"] and t["playing"]) or self.engine is None:
            return
        pos = self.engine.position()
        if t["mode"] == "pattern" and slot >= 0:
            m = self.machine(slot)
            if m is None:
                return
            key = self.pattern_key(m)
            pat = self.get_pattern(m, key, create=True)
            akey = f"{slot}:{key}:{param}"
            table = self.doc["automation"]["pattern"]
            entry = table.get(akey)
            nbars = pat["length"] * BEATS_PER_MEASURE * 8   # 32nd notes
            if entry is None or len(entry["bars"]) != nbars:
                entry = {"bars": [None] * nbars, "smooth": 0.5}
                table[akey] = entry
            span = pat["length"] * BEATS_PER_MEASURE
            bar = int((pos % span) * 8) % nbars
            entry["bars"][bar] = value
        elif t["mode"] == "song":
            akey = f"{slot}:{param}"
            table = self.doc["automation"]["song"]
            entry = table.setdefault(akey, {"keys": []})
            entry["keys"] = [k for k in entry["keys"] if abs(k[0] - pos) > 1 / 16]
            entry["keys"].append([round(pos, 4), value])
            entry["keys"].sort(key=lambda k: k[0])

    def _op_clear_automation(self, op):
        scope = op.get("scope", "pattern")
        table = self.doc["automation"].get(scope, {})
        key = op.get("key")
        if key in table:
            del table[key]
            return True
        return False

    def _op_set_automation_smooth(self, op):
        entry = self.doc["automation"]["pattern"].get(op["key"])
        if entry is None:
            return False
        entry["smooth"] = max(0.0, min(1.0, float(op["value"])))
        return True

    # presets ----------------------------------------------------------------------

    def preset_dir(self, mtype):
        return os.path.join(PRESET_DIR, _safe_name(mtype))

    def list_presets(self, mtype):
        d = self.preset_dir(mtype)
        if not os.path.isdir(d):
            return []
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))

    def save_preset(self, slot, name):
        m = self.machine(slot)
        if m is None:
            return False
        d = self.preset_dir(m["type"])
        os.makedirs(d, exist_ok=True)
        data = {"type": m["type"], "params": m["params"]}
        for extra in ("channels", "samples", "harm1", "harm2", "width1",
                      "width2", "expr_a", "expr_b", "components", "wires",
                      "modulators", "poly"):
            if extra in m:
                data[extra] = m[extra]
        with open(os.path.join(d, _safe_name(name) + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(data, f)
        with self.lock:
            m["preset"] = _safe_name(name)
            self.rev += 1
            self.dirty = True
        return True

    def load_preset(self, slot, name):
        m = self.machine(slot)
        if m is None:
            return False
        path = os.path.join(self.preset_dir(m["type"]), _safe_name(name) + ".json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            return False
        if data.get("type") != m["type"]:
            return False
        with self.lock:
            spec_params = catalog.default_params(catalog.MACHINES[m["type"]]["controls"])
            spec_params.update({k: v for k, v in data.get("params", {}).items()
                                if k in spec_params})
            m["params"] = spec_params
            for extra in ("channels", "samples", "harm1", "harm2", "width1",
                          "width2", "expr_a", "expr_b", "components", "wires",
                          "modulators", "poly"):
                if extra in data:
                    m[extra] = data[extra]
            m["preset"] = _safe_name(name)
            self.rev += 1
            self.dirty = True
        return True


class RoomManager:
    def __init__(self):
        self.rooms = {}
        self.lock = threading.Lock()

    def get(self, room_id):
        room_id = _safe_name(room_id or "default")
        with self.lock:
            room = self.rooms.get(room_id)
            if room is None:
                room = Room(room_id)
                self.rooms[room_id] = room
            return room
