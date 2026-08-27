/* Machine panel core: shared header/footer/widgets and the builder registry.
   Per-machine panel builders live in web/tools/<machine>.js. */
"use strict";

function renderMachine(mv, slot, m) {
  const panel = el("div", "machine", mv);
  buildMachineHead(panel, slot, m);
  const body = el("div", "machine-body", panel);
  const builder = MACHINE_BUILDERS[m.type] || buildGenericPanel;
  builder(body, slot, m);
  if (m.type !== "beatbox") buildKeyboardFooter(panel, slot, m);
}

/* ------------ shared header (label, LED, preset LCD, M/S, pattern btn) ---- */

function buildMachineHead(panel, slot, m) {
  const head = el("div", "machine-head", panel);
  const title = el("div", "machine-title", head);
  title.textContent = m.name;
  title.title = "Click to rename";
  title.addEventListener("click", () =>
    promptText("Rename machine", m.name, (v) =>
      send({ op: "rename_machine", slot, name: v })));

  const ledWrap = el("div", "", head);
  el("div", "led-label", ledWrap).textContent = "NOTE ON";
  const led = el("div", "note-led", ledWrap);
  window._noteLed = led;

  const lcd = el("div", "preset-lcd", head);
  lcd.textContent = m.preset || "Select preset";
  lcd.addEventListener("click", async () => {
    const r = await fetch(`/api/presets/${m.type}`);
    const { presets } = await r.json();
    pickFromList("LOAD PRESET — " + m.type, presets, presets.indexOf(m.preset),
      (i, name) => send({ op: "load_preset", slot, name }));
  });
  const saveBtn = el("button", "preset-save", head);
  saveBtn.innerHTML = "&#128190;";
  saveBtn.title = "Save preset";
  saveBtn.addEventListener("click", () =>
    promptText("Save preset as", m.preset || "", (v) =>
      v && send({ op: "save_preset", slot, name: v })));

  el("div", "spacer", head);

  if (m.type !== "beatbox") {
    const poly = el("div", "poly", head);
    const minus = el("button", "", poly); minus.textContent = "−";
    const pl = el("div", "poly-lcd", poly); pl.textContent = m.poly;
    const plus = el("button", "", poly); plus.textContent = "+";
    const setPoly = (v) => {
      v = Math.max(1, Math.min(16, v));
      m.poly = v; pl.textContent = v;
      send({ op: "set_machine_prop", slot, prop: "poly", value: v });
    };
    minus.addEventListener("click", () => setPoly(m.poly - 1));
    plus.addEventListener("click", () => setPoly(m.poly + 1));
    el("div", "led-label", poly).textContent = "POLY";
  }

  const ms = makeMS(m.mute, m.solo,
    (v) => send({ op: "set_mixer", slot, param: "mute", value: v }),
    (v) => send({ op: "set_mixer", slot, param: "solo", value: v }));
  head.appendChild(ms);

  const patBtn = el("button", "pattern-btn" + (App.editorOpen[slot] ? " on" : ""), head);
  patBtn.textContent = "PATTERN EDITOR";
  patBtn.addEventListener("click", () => {
    App.editorOpen[slot] = !App.editorOpen[slot];
    renderAll();
  });
}

function buildKeyboardFooter(panel, slot, m) {
  const kb = makeKeyboard(() => m.octave ?? 4,
    (note, on) => sendNote(slot, note, on),
    { onOctave: (d) => {
        m.octave = Math.max(0, Math.min(8, (m.octave ?? 4) + d));
        if (App.editorOpen[slot]) renderAll();
        send({ op: "set_machine_prop", slot, prop: "octave", value: m.octave });
      } });
  panel.appendChild(kb);
  window._kbdFlash = kb._flash;
}

function outGroup(body, slot, m, withVu = true) {
  const g = makeGroup("OUT", body);
  g.row.appendChild(paramWidget(slot, m, "volume"));
  if (Object.prototype.hasOwnProperty.call(m.params, "cut_note")) {
    g.row.appendChild(paramWidget(slot, m, "cut_note"));
  }
  if (withVu) {
    const vu = makeVU();
    g.row.appendChild(vu);
    const oldHook = window._statusHook;
    window._statusHook = (st) => {
      if (oldHook) oldHook(st);
      vu._set(st.vu?.[slot] ?? 0);
      if (window._noteLed) window._noteLed.classList.toggle("on", (st.vu?.[slot] ?? 0) > 0.02);
    };
  }
  return g;
}

function widgets(g, slot, m, ids) {
  ids.forEach(id => g.row.appendChild(paramWidget(slot, m, id)));
}

function buildGenericPanel(body, slot, m) {
  const g = makeGroup("CONTROLS", body);
  widgets(g, slot, m, Object.keys(App.catalog.machines[m.type].controls));
}

const MACHINE_BUILDERS = {
  subsynth: buildSubSynth,
  pcmsynth: buildPCMSynth,
  bassline: buildBassLine,
  beatbox: buildBeatBox,
  padsynth: buildPadSynth,
  bitsynth: build8Bit,
  modular: buildModular,
  organ: buildOrgan,
  vocoder: buildVocoder,
  fmsynth: buildFMSynth,
  kssynth: buildKSSynth,
};
