/* Vocoder machine panel. */
"use strict";

function buildVocoder(body, slot, m) {
  const g0 = makeGroup("MODULATOR", body);
  g0.box.style.flex = "1 1 100%";
  const modSel = el("div", "", g0.row);
  modSel.style.display = "flex"; modSel.style.gap = "3px";
  for (let i = 0; i < 6; i++) {
    const b = el("button", "pattern-btn" + (m.mod_sel === i ? " on" : ""), modSel);
    b.textContent = (i + 1);
    b.addEventListener("click", () => {
      m.mod_sel = i;
      send({ op: "set_machine_prop", slot, prop: "mod_sel", value: i });
      renderAll();
    });
  }
  const mod = m.modulators[m.mod_sel];
  const lcd = el("div", "bb-lcd", g0.row);
  lcd.style.flex = "1";
  lcd.textContent = mod.machine >= 0
    ? "machine " + (mod.machine + 1) + (App.doc.machines[mod.machine] ? " (" + App.doc.machines[mod.machine].name + ")" : "")
    : (mod.source || "(no modulator)");
  const load = el("button", "pattern-btn", g0.row);
  load.textContent = "LOAD WAV";
  load.addEventListener("click", () => {
    pickSample("SELECT MODULATOR SAMPLE", (name) =>
      send({ op: "set_modulator", slot, index: m.mod_sel, source: name, machine: -1 }));
  });
  const mach = el("button", "pattern-btn", g0.row);
  mach.textContent = "MACHINE";
  mach.title = "Use another machine as the modulation source";
  mach.addEventListener("click", () => {
    let next = (mod.machine + 1) % App.doc.machines.length;
    while (next !== mod.machine && (!App.doc.machines[next] || next === slot)) {
      next = (next + 1) % App.doc.machines.length;
    }
    send({ op: "set_modulator", slot, index: m.mod_sel, machine: next, source: "" });
  });
  const clear = el("button", "pattern-btn", g0.row);
  clear.textContent = "CLEAR";
  clear.addEventListener("click", () =>
    send({ op: "set_modulator", slot, index: m.mod_sel, source: "", machine: -1 }));

  // band VU
  const vuw = el("div", "voc-vu-wrap", g0.row);
  const vus = [];
  for (let i = 0; i < 8; i++) {
    const v = el("div", "voc-vu", vuw);
    vus.push(el("div", "vu-fill", v));
  }
  const oldHook = window._statusHook;
  window._statusHook = (st) => {
    if (oldHook) oldHook(st);
    const bv = st.vocoder_vu?.[slot];
    if (bv) bv.forEach((x, i) => { vus[i].style.height = Math.min(100, x * 100) + "%"; });
  };

  let g = makeGroup("CHARACTER", body);
  widgets(g, slot, m, ["band1", "band2", "band3", "band4", "band5", "band6", "band7", "band8"]);
  g = makeGroup("CARRIER", body);
  widgets(g, slot, m, ["carrier", "send_notes", "wave", "unison", "sub", "noise"]);
  g = makeGroup("ARTICULATION", body);
  widgets(g, slot, m, ["slew", "hf_bypass", "dry"]);
  outGroup(body, slot, m);
  const hint = el("div", "", body);
  hint.style.cssText = "flex:1 1 100%;font-size:10px;color:#39405a;padding:2px 4px";
  hint.textContent = "Tip: notes in the bottom octave (C1–F1) of the pattern select which modulator slot (1–6) plays.";
}
