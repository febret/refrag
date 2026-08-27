/* PadSynth machine panel. */
"use strict";

function buildPadSynth(body, slot, m) {
  const tabs = el("div", "", body);
  tabs.style.flex = "1 1 100%";
  tabs.style.display = "flex";
  tabs.style.gap = "4px";
  let mode = m._padView || "controls";
  const mk = (id, label) => {
    const b = el("button", "pattern-btn" + (mode === id ? " on" : ""), tabs);
    b.textContent = label;
    b.addEventListener("click", () => { m._padView = id; renderAll(); });
  };
  mk("harm1", "HARMONICS 1"); mk("harm2", "HARMONICS 2"); mk("controls", "CONTROLS");
  const copy = el("button", "pattern-btn", tabs); copy.textContent = "COPY";
  copy.title = "Copy the other table into this one";
  copy.addEventListener("click", () => {
    if (mode === "controls") return;
    const src = mode === "harm1" ? "harm2" : "harm1";
    send({ op: "set_machine_prop", slot, prop: mode, value: [...m[src]] });
  });
  const swap = el("button", "pattern-btn", tabs); swap.textContent = "SWAP";
  swap.addEventListener("click", () => {
    send({ op: "set_machine_prop", slot, prop: "harm1", value: [...m.harm2] });
    send({ op: "set_machine_prop", slot, prop: "harm2", value: [...m.harm1] });
  });

  if (mode === "controls") {
    let g = makeGroup("LFO 1", body);
    widgets(g, slot, m, ["lfo1_target", "lfo1_rate", "lfo1_depth", "lfo1_phase"]);
    g = makeGroup("LFO 2", body);
    widgets(g, slot, m, ["lfo2_target", "lfo2_rate", "lfo2_depth", "lfo2_phase"]);
    g = makeGroup("MORPH", body);
    widgets(g, slot, m, ["morph", "morph_env", "morph_attack", "morph_decay",
      "morph_sustain", "morph_release"]);
    g = makeGroup("TABLE GAINS", body);
    widgets(g, slot, m, ["gain1", "gain2"]);
    g = makeGroup("VOLUME ENVELOPE", body);
    widgets(g, slot, m, ["vol_attack", "vol_decay", "vol_sustain", "vol_release"]);
  } else {
    buildHarmonicEditor(body, slot, m, mode);
  }
  outGroup(body, slot, m);
}

function buildHarmonicEditor(body, slot, m, table) {
  const wrap = el("div", "", body);
  wrap.style.flex = "1 1 100%";
  const cv = el("canvas", "harm-canvas", wrap);
  const N = m[table].length;
  cv.width = 1000; cv.height = 220;
  cv.style.width = "100%";
  const widthKey = table === "harm1" ? "width1" : "width2";

  function draw() {
    const ctx = cv.getContext("2d");
    ctx.fillStyle = "#10142e"; ctx.fillRect(0, 0, cv.width, cv.height);
    const bw = cv.width / (N + 2);
    for (let i = 0; i < N; i++) {
      const h = m[table][i] * (cv.height - 10);
      ctx.fillStyle = "#4f8dff";
      ctx.fillRect(i * bw + 2, cv.height - h, bw - 4, h);
    }
    // width bar (yellow, rightmost)
    const wh = m[widthKey] * (cv.height - 10);
    ctx.fillStyle = "#ffd23d";
    ctx.fillRect((N + 1) * bw + 2, cv.height - wh, bw - 4, wh);
    ctx.fillStyle = "#667";
    ctx.font = "10px sans-serif";
    ctx.fillText("WIDTH", (N + 0.9) * bw, 12);
  }
  let dragging = false;
  function apply(e) {
    const r = cv.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * (N + 2);
    const val = Math.min(1, Math.max(0, 1 - (e.clientY - r.top) / r.height));
    const i = Math.floor(x);
    if (i >= 0 && i < N) {
      m[table][i] = val;
      send({ op: "set_harmonic", slot, table, index: i, value: val });
    } else if (i === N + 1) {
      m[widthKey] = val;
      send({ op: "set_machine_prop", slot, prop: widthKey, value: val });
    }
    draw();
  }
  cv.addEventListener("pointerdown", (e) => { dragging = true; cv.setPointerCapture(e.pointerId); apply(e); });
  cv.addEventListener("pointermove", (e) => { if (dragging) apply(e); });
  cv.addEventListener("pointerup", () => { dragging = false; });
  draw();
}
