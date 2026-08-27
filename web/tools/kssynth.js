/* KSSynth machine panel. */
"use strict";

function buildKSSynth(body, slot, m) {
  let g = makeGroup("EXCITE", body);
  widgets(g, slot, m, ["pre_filter", "pre_track", "pre_vel", "decay"]);
  g = makeGroup("UNIT 1", body);
  widgets(g, slot, m, ["u1_follow", "u1_octave", "u1_semis", "u1_cents",
    "u1_damping", "u1_damp_track", "u1_damp_vel", "u1_invert"]);
  g = makeGroup("UNIT 2", body);
  widgets(g, slot, m, ["u2_follow", "u2_octave", "u2_semis", "u2_cents",
    "u2_damping", "u2_damp_track", "u2_damp_vel", "u2_invert"]);
  g = makeGroup("MIX", body);
  widgets(g, slot, m, ["mix", "invert_mix"]);
  outGroup(body, slot, m);
}
