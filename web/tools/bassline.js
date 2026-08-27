/* BassLine machine panel. */
"use strict";

function buildBassLine(body, slot, m) {
  let g = makeGroup("OSC", body);
  widgets(g, slot, m, ["wave", "pulse_width", "tune"]);
  g = makeGroup("FILTER", body);
  widgets(g, slot, m, ["cutoff", "res", "env_mod", "decay", "accent"]);
  g = makeGroup("LFO", body);
  widgets(g, slot, m, ["lfo_target", "lfo_rate", "lfo_depth", "lfo_phase"]);
  g = makeGroup("DISTORTION", body);
  widgets(g, slot, m, ["dist_program", "dist_pre", "dist_amount", "dist_post"]);
  g = makeGroup("GLIDE", body);
  widgets(g, slot, m, ["legacy_glide"]);
  outGroup(body, slot, m);
}
