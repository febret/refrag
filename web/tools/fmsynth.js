/* FMSynth machine panel. */
"use strict";

function buildFMSynth(body, slot, m) {
  let g = makeGroup("ALGORITHM", body);
  widgets(g, slot, m, ["algorithm", "feedback", "feedback_vel", "volume_vel"]);
  g = makeGroup("LFO", body);
  widgets(g, slot, m, ["lfo_a1", "lfo_a2", "lfo_a3", "lfo_ao", "lfo_f1",
    "lfo_f2", "lfo_f3", "lfo_rate", "lfo_depth"]);
  for (let i = 1; i <= 3; i++) {
    g = makeGroup("OPERATOR " + i, body);
    g.box.style.flex = "1 1 100%";
    widgets(g, slot, m, [`op${i}_level`, `op${i}_level_vel`, `op${i}_octave`,
      `op${i}_semis`, `op${i}_fixed`, `op${i}_attack`, `op${i}_decay`,
      `op${i}_sustain`, `op${i}_release`]);
  }
  outGroup(body, slot, m);
}
