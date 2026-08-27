/* Effects rack, mixer and master section views. */
"use strict";

/* ---------------- effects rack ---------------- */

function renderEffectsRack(mv) {
  const wrap = el("div", "fx-wrap", mv);
  const machines = App.doc.machines
    .map((m, i) => ({ m, i })).filter(x => x.m);
  if (!machines.length) {
    wrap.innerHTML = "<div style='text-align:center;padding:60px;color:#667'>Add machines first — each machine gets two insert effect slots here.</div>";
    return;
  }
  machines.forEach(({ m, i }) => {
    const panel = el("div", "machine", wrap);
    const head = el("div", "machine-head", panel);
    el("div", "machine-title", head).textContent = m.name;
    el("div", "led-label", head).textContent = "signal flows slot 1 → slot 2 → mixer";
    const body = el("div", "machine-body", panel);
    body.style.flexWrap = "nowrap";
    for (let s = 0; s < 2; s++) {
      const holder = el("div", "", body);
      holder.style.flex = "1";
      buildFxSlot(holder, { slot: i }, m.effects[s], s);
    }
  });
}

function buildFxSlot(holder, target, fxState, index) {
  const isMaster = target.target === "master";
  const base = isMaster ? { op: "set_effect", target: "master", index }
                        : { op: "set_effect", slot: target.slot, index };
  if (!fxState) {
    const slot = el("div", "fx-slot", holder);
    slot.textContent = "+ insert effect " + (index + 1);
    slot.addEventListener("click", () => {
      showModal("SELECT EFFECT", (b) => {
        const grid = el("div", "choice-grid", b);
        App.catalog.effectOrder.forEach(et => {
          const c = el("div", "citem", grid);
          c.textContent = App.catalog.effects[et].name;
          c.addEventListener("click", () => {
            closeModal();
            send({ ...base, etype: et });
          });
        });
      });
    });
    return;
  }
  const spec = App.catalog.effects[fxState.type];
  const unit = el("div", "fx-unit" + (fxState.bypass ? "" : " active"), holder);
  const head = el("div", "fx-head", unit);
  head.title = "Click to bypass/enable";
  el("div", "fx-name", head).textContent = spec.name.toUpperCase();
  const right = el("div", "", head);
  right.style.display = "flex"; right.style.alignItems = "center"; right.style.gap = "6px";
  el("div", "fx-led", right);
  const x = el("div", "fx-del", right);
  x.textContent = "✕";
  x.addEventListener("click", (e) => {
    e.stopPropagation();
    send({ ...base, etype: null });
  });
  head.addEventListener("click", () => {
    const pbase = isMaster
      ? { op: "set_effect_param", target: "master", index }
      : { op: "set_effect_param", slot: target.slot, index };
    send({ ...pbase, param: "bypass", value: fxState.bypass ? 0 : 1 });
    fxState.bypass = fxState.bypass ? 0 : 1;
    unit.classList.toggle("active", !fxState.bypass);
  });
  const bodyEl = el("div", "fx-body", unit);
  for (const pid in spec.controls) {
    const cspec = spec.controls[pid];
    const pbase = isMaster
      ? { op: "set_effect_param", target: "master", index }
      : { op: "set_effect_param", slot: target.slot, index };
    const onCh = (v) => send({ ...pbase, param: pid, value: v });
    let w;
    if (cspec.type === "select") w = makeSelector(cspec, fxState.params[pid], onCh);
    else if (cspec.type === "toggle") w = makeToggle(cspec, fxState.params[pid], onCh);
    else w = makeKnob(cspec, fxState.params[pid], onCh);
    bodyEl.appendChild(w);
  }
}

/* ---------------- mixer ---------------- */

function renderMixer(mv) {
  const wrap = el("div", "mixer-wrap", mv);
  for (let page = 0; page < 2; page++) {
    const strips = [];
    for (let i = page * 7; i < page * 7 + 7; i++) {
      if (App.doc.machines[i]) strips.push(i);
    }
    if (!strips.length && page === 1) continue;
    const panel = el("div", "machine", wrap);
    const head = el("div", "machine-head", panel);
    el("div", "machine-title", head).textContent =
      "MIXER " + (page + 1) + "  (machines " + (page * 7 + 1) + "–" + (page * 7 + 7) + ")";
    const row = el("div", "mixer-row", panel);
    if (!strips.length) {
      el("div", "", row).textContent = "no machines in this range";
    }
    strips.forEach(i => buildStrip(row, i, App.doc.machines[i]));
  }
}

function buildStrip(row, slot, m) {
  const strip = el("div", "strip", row);
  const spec = App.catalog.mixerStrip;
  const mkw = (pid) => {
    const w = makeKnob(spec[pid], m.mixer[pid],
      (v) => { m.mixer[pid] = v; send({ op: "set_mixer", slot, param: pid, value: v }); });
    w._autoKey = slot + ":mixer." + pid;
    w.dataset.autokey = slot + ":mixer." + pid;
    return w;
  };
  const eq = el("div", "", strip);
  eq.style.display = "flex";
  eq.appendChild(mkw("eq_bass"));
  eq.appendChild(mkw("eq_mid"));
  eq.appendChild(mkw("eq_high"));
  const sends = el("div", "", strip);
  sends.style.display = "flex";
  sends.appendChild(mkw("send_delay"));
  sends.appendChild(mkw("send_reverb"));
  const st = el("div", "", strip);
  st.style.display = "flex";
  st.appendChild(mkw("pan"));
  st.appendChild(mkw("width"));
  const ms = makeMS(m.mute, m.solo,
    (v) => send({ op: "set_mixer", slot, param: "mute", value: v }),
    (v) => send({ op: "set_mixer", slot, param: "solo", value: v }));
  strip.appendChild(ms);
  const volRow = el("div", "", strip);
  volRow.style.display = "flex"; volRow.style.alignItems = "center";
  volRow.appendChild(mkw("volume"));
  const vu = makeVU();
  volRow.appendChild(vu);
  const oldHook = window._statusHook;
  window._statusHook = (s) => { if (oldHook) oldHook(s); vu._set(s.vu?.[slot] ?? 0); };
  const name = el("div", "strip-name", strip);
  name.textContent = m.name;
  name.title = "Double-click to jump to machine";
  name.addEventListener("dblclick", () => setView({ kind: "machine", slot }));
}

/* ---------------- master ---------------- */

function renderMaster(mv) {
  const wrap = el("div", "master-wrap", mv);
  const panel = el("div", "machine", wrap);
  const head = el("div", "machine-head", panel);
  el("div", "machine-title", head).textContent = "MASTER";
  const body = el("div", "machine-body", panel);
  const P = App.doc.master.params;
  const spec = App.catalog.master;

  const mw = (g, pid) => {
    const cspec = spec[pid];
    const onCh = (v) => { P[pid] = v; send({ op: "set_master", param: pid, value: v }); };
    let w;
    if (cspec.type === "select") w = makeSelector(cspec, P[pid], onCh);
    else if (cspec.type === "toggle") w = makeToggle(cspec, P[pid], onCh);
    else w = makeKnob(cspec, P[pid], onCh);
    w._autoKey = "-1:" + pid;
    w.dataset.autokey = "-1:" + pid;
    g.row.appendChild(w);
    return w;
  };

  let g = makeGroup("GLOBAL DELAY", body);
  ["dly_bypass", "dly_loop", "dly_sync", "dly_first_tap", "dly_steps",
   "dly_time", "dly_feedback", "dly_damping", "dly_wet", "dly_pan1", "dly_pan2"]
    .forEach(p => mw(g, p));

  g = makeGroup("GLOBAL REVERB", body);
  ["rev_bypass", "rev_predelay", "rev_room", "rev_damping", "rev_diffuse",
   "rev_dither", "rev_early", "rev_er_decay", "rev_stereo_delay",
   "rev_stereo_spread", "rev_wet"].forEach(p => mw(g, p));

  // master insert slots
  const gfx = makeGroup("MASTER INSERTS", body);
  gfx.box.style.flex = "1 1 100%";
  gfx.row.style.alignItems = "stretch";
  for (let s = 0; s < 2; s++) {
    const holder = el("div", "", gfx.row);
    holder.style.flex = "1";
    buildFxSlot(holder, { target: "master" }, App.doc.master.effects[s], s);
  }

  g = makeGroup("EQUALIZER", body);
  const eqCurve = el("canvas", "harm-canvas", g.row);
  eqCurve.width = 260; eqCurve.height = 80;
  drawEqCurve(eqCurve, P);
  ["eq_bypass", "eq_bass", "eq_bass_freq", "eq_mid", "eq_mid_freq", "eq_high"]
    .forEach(p => {
      const w = mw(g, p);
      const orig = w._set;
      // redraw curve when any EQ knob moves
      w.addEventListener("pointerup", () => drawEqCurve(eqCurve, P));
    });

  g = makeGroup("LIMITER", body);
  ["lim_bypass", "lim_pre", "lim_attack", "lim_release", "lim_post"].forEach(p => mw(g, p));
  const grVu = makeVU();
  g.row.appendChild(grVu);

  g = makeGroup("MASTER OUT", body);
  mw(g, "volume");
  const vuL = makeVU(), vuR = makeVU();
  g.row.appendChild(vuL); g.row.appendChild(vuR);

  const oldHook = window._statusHook;
  window._statusHook = (s) => {
    if (oldHook) oldHook(s);
    vuL._set(s.master_vu?.[0] ?? 0);
    vuR._set(s.master_vu?.[1] ?? 0);
    grVu._set(s.lim_gr ?? 0);
  };
}

function drawEqCurve(cv, P) {
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height;
  ctx.fillStyle = "#221a12"; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "#4a3b28";
  for (let i = 1; i < 4; i++) {
    ctx.beginPath(); ctx.moveTo(0, H * i / 4); ctx.lineTo(W, H * i / 4); ctx.stroke();
  }
  const bassF = 60 + P.eq_bass_freq * 440;
  const midF = 500 + P.eq_mid_freq * 4500;
  ctx.strokeStyle = "#5a6cd0";
  [bassF, midF].forEach(f => {
    const x = W * Math.log(f / 20) / Math.log(20000 / 20);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  });
  ctx.strokeStyle = "#e8e8f0"; ctx.lineWidth = 2;
  ctx.beginPath();
  for (let px = 0; px < W; px++) {
    const f = 20 * Math.pow(20000 / 20, px / W);
    let g = 0;
    if (f < bassF) g = P.eq_bass;
    else if (f < midF) g = P.eq_mid;
    else g = P.eq_high;
    // soft transitions
    const smooth = (a, b, fa) => a + (b - a) * fa;
    if (f > bassF * 0.6 && f < bassF * 1.6) {
      const fa = (Math.log(f) - Math.log(bassF * 0.6)) / (Math.log(bassF * 1.6) - Math.log(bassF * 0.6));
      g = smooth(P.eq_bass, P.eq_mid, Math.min(1, Math.max(0, fa)));
    }
    if (f > midF * 0.6 && f < midF * 1.6) {
      const fa = (Math.log(f) - Math.log(midF * 0.6)) / (Math.log(midF * 1.6) - Math.log(midF * 0.6));
      g = smooth(P.eq_mid, P.eq_high, Math.min(1, Math.max(0, fa)));
    }
    const y = H / 2 - g * H * 0.4;
    if (px === 0) ctx.moveTo(px, y); else ctx.lineTo(px, y);
  }
  ctx.stroke();
  ctx.lineWidth = 1;
  ctx.fillStyle = "#7a6a50"; ctx.font = "9px sans-serif";
  ctx.fillText("200", W * 0.25, H - 4);
  ctx.fillText("1K", W * 0.45, H - 4);
  ctx.fillText("10K", W * 0.8, H - 4);
}
