/* PCMSynth machine panel. */
"use strict";

function buildPCMSynth(body, slot, m) {
  const g0 = makeGroup("SAMPLER", body);
  g0.box.style.flex = "1 1 100%";
  const zone = m.samples[m.sample_sel] || m.samples[0];

  const info = el("div", "bb-lcd", g0.row);
  info.style.flex = "1"; info.style.height = "40px"; info.style.fontSize = "12px";
  const zi = m.samples.indexOf(zone);
  info.innerHTML = `[${zi + 1}/${m.samples.length}] <b>${zone.sample}</b> ` +
    ` root:${noteName(zone.root)} lo:${noteName(zone.low)} hi:${noteName(zone.high)}` +
    ` mode:${["Once", "On/Off", "LoopF", "LoopFB", "In+LF", "In+LFB"][zone.mode]}` +
    ` lvl:${Math.round(zone.level * 100)}%`;

  const mkBtn = (label, fn) => {
    const b = el("button", "pattern-btn", g0.row);
    b.textContent = label; b.style.height = "40px";
    b.addEventListener("click", fn);
    return b;
  };
  mkBtn("SAMPLE", () => {
    pickSample("SELECT SAMPLE", (name) => {
      send({ op: "set_sample_param", slot, index: zi, param: "sample", value: name });
    });
  });
  mkBtn("+ZONE", () => {
    pickSample("ADD SAMPLE ZONE", (name) => {
      send({ op: "set_sample_param", slot, index: 0, param: "add", value: name });
    });
  });
  mkBtn("−ZONE", () => send({ op: "set_sample_param", slot, index: zi, param: "remove" }));
  mkBtn("<", () => send({ op: "set_sample_param", slot, index: Math.max(0, zi - 1), param: "select" }));
  mkBtn(">", () => send({ op: "set_sample_param", slot, index: Math.min(m.samples.length - 1, zi + 1), param: "select" }));

  const zparam = (label, key, min, max, curve, fmt) => {
    const w = makeKnob({ label, min, max, default: zone[key], curve }, zone[key],
      (v) => send({ op: "set_sample_param", slot, index: zi, param: key, value: v }),
      { format: fmt });
    g0.row.appendChild(w);
  };
  zparam("Level", "level", 0, 2);
  zparam("Tune", "tune", -50, 50, "int");
  zparam("Pan", "pan", -1, 1);
  zparam("Root", "root", 12, 108, "int", (v) => noteName(Math.round(v)));
  zparam("Low", "low", 0, 127, "int", (v) => noteName(Math.round(v)));
  zparam("High", "high", 0, 127, "int", (v) => noteName(Math.round(v)));
  zparam("Mode", "mode", 0, 5, "int",
    (v) => ["Once", "On/Off", "LoopF", "LoopFB", "In+LF", "In+LFB"][Math.round(v)]);
  zparam("Start", "start", 0, 1);
  zparam("End", "end", 0, 1);

  let g = makeGroup("FILTER", body);
  widgets(g, slot, m, ["flt_type", "flt_cutoff", "flt_res", "flt_attack",
    "flt_decay", "flt_sustain", "flt_release"]);
  g = makeGroup("LFO", body);
  widgets(g, slot, m, ["lfo_target", "lfo_wave", "lfo_rate", "lfo_depth"]);
  g = makeGroup("PITCH", body);
  widgets(g, slot, m, ["octave", "semis", "cents"]);
  g = makeGroup("VOLUME ENVELOPE", body);
  widgets(g, slot, m, ["vol_attack", "vol_decay", "vol_sustain", "vol_release"]);
  outGroup(body, slot, m);
}

function noteName(n) {
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  return names[n % 12] + (Math.floor(n / 12) - 1);
}

function allSampleNames() {
  return [...App.sampleLib.factory, ...App.sampleLib.user];
}
