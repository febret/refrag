/* SubSynth machine panel. */
"use strict";

function buildSubSynth(body, slot, m) {
  let g = makeGroup("OSCILLATOR 1", body);
  widgets(g, slot, m, ["osc1_wave", "osc_mix", "osc_mod", "mod_mode"]);
  g = makeGroup("BEND", body);
  widgets(g, slot, m, ["bend"]);
  g = makeGroup("FILTER", body);
  widgets(g, slot, m, ["flt_type", "flt_cutoff", "flt_res", "flt_track",
    "flt_attack", "flt_decay", "flt_sustain", "flt_release"]);
  g = makeGroup("LFO 1", body);
  widgets(g, slot, m, ["lfo1_target", "lfo1_wave", "lfo1_rate", "lfo1_depth"]);
  g = makeGroup("LFO 2", body);
  widgets(g, slot, m, ["lfo2_target", "lfo2_rate", "lfo2_depth"]);
  g = makeGroup("OSCILLATOR 2", body);
  widgets(g, slot, m, ["osc2_wave", "osc2_phase", "osc2_octave", "osc2_semis",
    "osc2_cents", "detune_mode"]);
  g = makeGroup("VOLUME ENVELOPE", body);
  widgets(g, slot, m, ["vol_attack", "vol_decay", "vol_sustain", "vol_release"]);
  outGroup(body, slot, m);
}
