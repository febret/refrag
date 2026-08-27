/* Pattern editor (piano roll / drum grid) and song sequencer views. */
"use strict";

const BANK_NAMES = ["A", "B", "C", "D"];
const CHORD_KEYS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const CHORD_ROOT_TO_PC = {
  C: 0, "B#": 0,
  "C#": 1, Db: 1,
  D: 2,
  "D#": 3, Eb: 3,
  E: 4, Fb: 4,
  F: 5, "E#": 5,
  "F#": 6, Gb: 6,
  G: 7,
  "G#": 8, Ab: 8,
  A: 9,
  "A#": 10, Bb: 10,
  B: 11, Cb: 11,
};
const PROGRESSION_TEMPLATES = [
  { id: "pop", label: "Pop (I-V-vi-IV)", degrees: [0, 4, 5, 3] },
  { id: "fifties", label: "50s (I-vi-IV-V)", degrees: [0, 5, 3, 4] },
  { id: "turnaround", label: "Turnaround (ii-V-I)", degrees: [1, 4, 0] },
  { id: "axis", label: "Axis (vi-IV-I-V)", degrees: [5, 3, 0, 4] },
  { id: "minor-arc", label: "Minor Arc (i-VI-III-VII)", degrees: [0, 5, 2, 6] },
];

function patKey(m) { return BANK_NAMES[m.bank] + (m.pattern + 1); }

function getPattern(m) {
  return m.patterns[patKey(m)] || { length: 1, notes: [] };
}

function clonePatternNotes(notes) {
  return (notes || []).map((n) => [
    Math.round(+n[0] || 0),
    +n[1] || 0,
    Math.max(1 / 16, +n[2] || 1 / 16),
    Math.max(0.05, Math.min(1, +(n[3] ?? 1))),
    Math.round(+n[4] || 0),
  ]);
}

function infoBox(title, text) {
  showModal(title, (b) => { el("div", "", b).textContent = text; }, [
    { label: "OK", primary: true },
  ]);
}

function parseChordSymbol(token) {
  const m = token.match(/^([A-Ga-g])([#b]?)(.*)$/);
  if (!m) return null;
  const root = m[1].toUpperCase() + (m[2] || "");
  const rootPc = CHORD_ROOT_TO_PC[root];
  if (rootPc === undefined) return null;
  const q = (m[3] || "").trim().toLowerCase();
  let intervals = [0, 4, 7];
  if (q === "" || q === "maj") intervals = [0, 4, 7];
  else if (q === "m" || q === "min") intervals = [0, 3, 7];
  else if (q === "7") intervals = [0, 4, 7, 10];
  else if (q === "maj7") intervals = [0, 4, 7, 11];
  else if (q === "m7" || q === "min7") intervals = [0, 3, 7, 10];
  else if (q === "dim" || q === "o") intervals = [0, 3, 6];
  else if (q === "aug" || q === "+") intervals = [0, 4, 8];
  else if (q === "sus2") intervals = [0, 2, 7];
  else if (q === "sus4" || q === "sus") intervals = [0, 5, 7];
  else return null;
  return { rootPc, intervals };
}

function nextPatternLengthForBeats(beats) {
  const neededMeasures = Math.max(1, Math.ceil(beats / 4));
  for (const len of [1, 2, 4, 8]) {
    if (neededMeasures <= len) return len;
  }
  return null;
}

function parseChordGridText(text, stepBeats, octave, velocity) {
  const tokens = (text || "").trim().split(",");
  const notes = [];
  let maxEnd = 0;
  for (let i = 0; i < tokens.length; i++) {
    const raw = tokens[i].trim();
    if (!raw) continue;
    const tm = raw.match(/^(.+?)(?:\*(\d+))?$/);
    if (!tm) return { error: "Invalid chord token: " + raw };
    const chordName = tm[1].trim();
    const holdSteps = tm[2] ? parseInt(tm[2], 10) : 1;
    if (!chordName || !Number.isFinite(holdSteps) || holdSteps < 1) {
      return { error: "Invalid hold length in token: " + raw };
    }
    const chord = parseChordSymbol(chordName);
    if (!chord) return { error: "Unsupported chord token: " + chordName };
    const start = i * stepBeats;
    const dur = holdSteps * stepBeats;
    maxEnd = Math.max(maxEnd, start + dur);
    const base = ((octave ?? 4) + 1) * 12 + chord.rootPc;
    chord.intervals.forEach((iv) => {
      notes.push([
        Math.max(0, Math.min(127, base + iv)),
        start,
        dur,
        velocity,
        0,
      ]);
    });
  }
  notes.sort((a, b) => (a[1] - b[1]) || (a[0] - b[0]));
  const totalBeats = Math.max(tokens.length * stepBeats, maxEnd, 4 / 16);
  return { notes, totalBeats };
}

function buildDiatonicProgressionText(keyPc, mode, template, stepsPerBeat) {
  const majorScale = [0, 2, 4, 5, 7, 9, 11];
  const minorScale = [0, 2, 3, 5, 7, 8, 10];
  const majorQual = ["", "m", "m", "", "", "m", "dim"];
  const minorQual = ["m", "dim", "", "m", "m", "", ""];
  const scale = mode === "minor" ? minorScale : majorScale;
  const qual = mode === "minor" ? minorQual : majorQual;
  const chords = scale.map((s, i) => CHORD_KEYS[(keyPc + s) % 12] + qual[i]);
  const span = Math.max(1, stepsPerBeat | 0);
  const hold = "*" + span;
  const sep = ",".repeat(Math.max(0, span - 1));
  return template.degrees.map((deg) => chords[deg] + hold).join(sep);
}

/* =====================================================================
   Per-machine pattern editor (lives under the machine panel)
   ===================================================================== */

function renderPatternEditor(mv, slot, m) {
  const panel = el("div", "machine editor-panel", mv);
  const tb = el("div", "editor-toolbar", panel);

  const state = App._edState = App._edState || {};
  const es = state[slot] = state[slot] || { grid: 16, vel: 1.0, sel: -1, drum: m.type === "beatbox" };
  es.drum = m.type === "beatbox";

  // bank buttons
  let grp = el("div", "tb-group", tb);
  el("div", "tb-label", tb);
  BANK_NAMES.forEach((b, bi) => {
    const bt = el("button", m.bank === bi ? "bank-on" : "", grp);
    bt.textContent = b;
    bt.addEventListener("click", () => send({ op: "select_pattern", slot, bank: bi }));
  });
  // pattern buttons 1-16
  grp = el("div", "tb-group", tb);
  for (let i = 0; i < 16; i++) {
    const bt = el("button", m.pattern === i ? "on" : "", grp);
    bt.textContent = i + 1;
    const hasNotes = (m.patterns[BANK_NAMES[m.bank] + (i + 1)]?.notes?.length || 0) > 0;
    if (hasNotes) bt.style.color = "#7be87b";
    bt.addEventListener("click", () => send({ op: "select_pattern", slot, pattern: i }));
    bt.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      patternOptions(slot, m, BANK_NAMES[m.bank] + (i + 1));
    });
  }
  // measures
  grp = el("div", "tb-group", tb);
  el("div", "tb-label", grp).textContent = "MEASURES";
  const pat = getPattern(m);
  [1, 2, 4, 8].forEach(L => {
    const bt = el("button", pat.length === L ? "on" : "", grp);
    bt.textContent = L;
    bt.addEventListener("click", () =>
      send({ op: "set_pattern_length", slot, length: L }));
  });
  // grid size
  grp = el("div", "tb-group", tb);
  el("div", "tb-label", grp).textContent = "GRID";
  [8, 16, 32, 64].forEach(gs => {
    const bt = el("button", es.grid === gs ? "on" : "", grp);
    bt.textContent = "1/" + gs;
    bt.addEventListener("click", () => { es.grid = gs; renderAll(); });
  });
  // actions
  grp = el("div", "tb-group", tb);
  const clr = el("button", "", grp); clr.textContent = "CLEAR";
  clr.addEventListener("click", () =>
    confirmBox("Clear pattern", "Remove all notes from " + patKey(m) + "?",
      () => send({ op: "clear_pattern", slot })));
  const shl = el("button", "", grp); shl.textContent = "◀ SHIFT";
  shl.addEventListener("click", () => send({ op: "shift_pattern", slot, beats: -0.25 }));
  const shr = el("button", "", grp); shr.textContent = "SHIFT ▶";
  shr.addEventListener("click", () => send({ op: "shift_pattern", slot, beats: 0.25 }));
  const trd = el("button", "", grp); trd.textContent = "−12";
  trd.addEventListener("click", () => send({ op: "shift_pattern", slot, semis: -12 }));
  const tru = el("button", "", grp); tru.textContent = "+12";
  tru.addEventListener("click", () => send({ op: "shift_pattern", slot, semis: 12 }));
  const cpy = el("button", "", grp); cpy.textContent = "COPY";
  cpy.title = "Copy full pattern (length + notes)";
  cpy.addEventListener("click", () => {
    App._patternClipboard = {
      length: pat.length,
      notes: clonePatternNotes(pat.notes),
    };
    pst.disabled = false;
  });
  const pst = el("button", "", grp); pst.textContent = "PASTE";
  pst.title = "Paste copied pattern into this preset";
  pst.disabled = !App._patternClipboard;
  pst.addEventListener("click", () => {
    const clip = App._patternClipboard;
    if (!clip || !Array.isArray(clip.notes)) {
      infoBox("Paste pattern", "No copied pattern is available yet.");
      return;
    }
    send({ op: "set_pattern_notes", slot, length: clip.length, notes: clonePatternNotes(clip.notes) });
  });

  // flourish / AI match tools
  grp = el("div", "tb-group", tb);
  const flb = el("button", "fl-btn", grp); flb.textContent = "✦ FLOURISH";
  flb.title = "Add generated notes matching selected themes";
  flb.addEventListener("click", () => flourishDialog(slot, m));
  if (pat.flourish) {
    const flOn = !!pat.flourish.on;
    const tg = el("button", flOn ? "fl-on" : "", grp);
    tg.textContent = flOn ? "FL ON" : "FL OFF";
    tg.title = "Toggle whether flourish notes play";
    tg.addEventListener("click", () =>
      send({ op: "flourish_toggle", slot, on: flOn ? 0 : 1 }));
  }
  const chb = el("button", "ch-btn", grp); chb.textContent = "CHORDS";
  chb.title = "Build chords from text or standard progressions";
  chb.addEventListener("click", () => chordDialog(slot, m, es));
  const aib = el("button", "", grp); aib.textContent = "AI MATCH";
  aib.title = "Fill the pattern from a recorded or uploaded sound clip";
  aib.addEventListener("click", () => aiMatchDialog(slot, m));

  const wrap = el("div", "editor-canvas-wrap", panel);
  wrap.style.display = "flex";
  const cvBox = el("div", "", wrap);
  cvBox.style.flex = "1";
  const cv = el("canvas", "", cvBox);
  if (es.drum) buildDrumGrid(cv, slot, m, es);
  else buildPianoRoll(cv, slot, m, es);

  // velocity side panel
  const side = el("div", "vel-slider-wrap", wrap);
  el("div", "", side).textContent = "VEL";
  const vel = makeSlider({ label: "", min: 0.05, max: 1, default: 1 }, es.vel, (v) => {
    es.vel = v;
    if (es.sel >= 0) send({ op: "update_note", slot, index: es.sel, vel: v });
  }, { height: 120 });
  es.velCtl = vel;
  side.appendChild(vel);
  const del = el("button", "pattern-btn", side);
  del.textContent = "✕";
  del.title = "Delete selected note";
  del.addEventListener("click", () => {
    if (es.sel >= 0) { send({ op: "remove_note", slot, index: es.sel }); es.sel = -1; }
  });
}

/* ---------------- piano roll ---------------- */

function buildPianoRoll(cv, slot, m, es) {
  const pat = getPattern(m);
  const beats = pat.length * 4;
  const KEYS = 24;                    // 2 octaves visible (matches keyboard footer)
  const lowKey = Math.max(0, Math.min(127 - KEYS + 1, ((m.octave ?? 4) + 1) * 12));
  const KW = 42;                      // key column width
  const RH = 14;                      // row height
  const W = 1400, H = KEYS * RH;
  cv.width = W; cv.height = H;
  cv.style.height = Math.min(420, H) + "px";
  const ctx = cv.getContext("2d");
  const gw = (W - KW) / beats;        // pixels per beat
  const stepB = 4 / es.grid;          // grid step in beats

  const isBlack = (n) => [1, 3, 6, 8, 10].includes(n % 12);
  const y4note = (n) => H - (n - lowKey + 1) * RH;
  const note4y = (y) => lowKey + Math.floor((H - y) / RH);
  const x4beat = (b) => KW + b * gw;
  const beat4x = (x) => (x - KW) / gw;

  function draw() {
    ctx.fillStyle = "#d8dae2"; ctx.fillRect(0, 0, W, H);
    // rows
    for (let k = 0; k < KEYS; k++) {
      const note = lowKey + k;
      const y = y4note(note);
      ctx.fillStyle = isBlack(note) ? "#c5c8d4" : "#dcdee6";
      ctx.fillRect(KW, y, W - KW, RH);
      ctx.strokeStyle = "#b6b9c6";
      ctx.strokeRect(KW, y + 0.5, W - KW, RH);
      // key
      ctx.fillStyle = isBlack(note) ? "#20222c" : "#f6f7fb";
      ctx.fillRect(0, y, KW, RH);
      ctx.strokeStyle = "#888";
      ctx.strokeRect(0.5, y + 0.5, KW, RH);
      if (note % 12 === 0) {
        ctx.fillStyle = isBlack(note) ? "#eee" : "#444";
        ctx.font = "9px sans-serif";
        ctx.fillText("C" + (note / 12 - 1), 4, y + 10);
      }
    }
    // grid lines
    for (let b = 0; b <= beats; b += stepB) {
      const x = x4beat(b);
      ctx.strokeStyle = b % 4 === 0 ? "#7a7f92" : (b % 1 === 0 ? "#a6aaba" : "#c2c5d2");
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    // notes
    const flOn = !pat.flourish || !!pat.flourish.on;
    pat.notes.forEach((n, i) => {
      const [key, start, dur, vel, flags] = n;
      if (key < lowKey || key >= lowKey + KEYS) return;
      const x = x4beat(start), y = y4note(key);
      const w = Math.max(4, dur * gw - 2);
      if (flags & 4) {               // flourish note: glowing blue
        ctx.globalAlpha = flOn ? 0.4 + vel * 0.6 : 0.15;
        ctx.shadowColor = "#4dc3ff";
        ctx.shadowBlur = flOn ? 9 : 0;
        ctx.fillStyle = i === es.sel ? "#e8811d" : "#2f9df5";
        ctx.fillRect(x + 1, y + 1.5, w, RH - 3);
        ctx.shadowBlur = 0;
      } else {
        const v = Math.max(0.05, Math.min(1, vel ?? 1));
        const shade = Math.round(255 * (1 - v));
        ctx.globalAlpha = 1;
        ctx.fillStyle = `rgb(${shade},${shade},${shade})`;
        ctx.fillRect(x + 1, y + 1.5, w, RH - 3);
        if (i === es.sel) {
          ctx.strokeStyle = "#e8811d";
          ctx.lineWidth = 2;
          ctx.strokeRect(x + 1.5, y + 2, Math.max(2, w - 1), RH - 4);
          ctx.lineWidth = 1;
        }
      }
      ctx.globalAlpha = 1;
      if (flags & 1) { ctx.fillStyle = "#ffd23d"; ctx.fillRect(x + 2, y + 3, 3, RH - 6); }
      if (flags & 2) { ctx.fillStyle = "#4dc3ff"; ctx.fillRect(x + w - 4, y + 3, 3, RH - 6); }
    });
    // playhead
    drawPlayhead();
  }
  let playX = -1;
  function drawPlayhead() {
    if (!App.doc.transport.playing || App.doc.transport.mode !== "pattern") return;
    const pos = App.status.pos % beats;
    const x = x4beat(pos);
    ctx.strokeStyle = "#d3231c"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    ctx.lineWidth = 1;
  }
  const oldHook = window._statusHook;
  window._statusHook = (st) => { if (oldHook) oldHook(st); draw(); };

  function hitNote(bx, ny) {
    for (let i = pat.notes.length - 1; i >= 0; i--) {
      const [key, start, dur] = pat.notes[i];
      if (key === ny && bx >= start && bx < start + Math.max(dur, 0.1)) return i;
    }
    return -1;
  }

  let drag = null;
  cv.addEventListener("pointerdown", (e) => {
    cv.setPointerCapture(e.pointerId);
    const r = cv.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const py = (e.clientY - r.top) * (H / r.height);
    if (px < KW) {   // side keyboard preview
      const note = note4y(py);
      sendNote(slot, note, true);
      setTimeout(() => sendNote(slot, note, false), 250);
      return;
    }
    const bx = beat4x(px);
    const ny = note4y(py);
    const hit = hitNote(bx, ny);
    if (hit >= 0) {
      const n = pat.notes[hit];
      if ((n[4] || 0) & 4) {     // clicking a flourish note commits it
        n[4] &= ~4;
        es.justCommitted = Date.now();
        send({ op: "flourish_commit", slot, index: hit });
        draw();
        return;
      }
      es.sel = hit;
      const nearEnd = bx > n[1] + n[2] - Math.max(stepB, n[2] * 0.3);
      drag = { kind: nearEnd ? "resize" : "move", idx: hit,
               offB: bx - n[1], orig: [...n], moved: false };
      draw();
    } else {
      // add new note snapped to grid
      const start = Math.floor(bx / stepB) * stepB;
      if (start >= 0 && start < beats) {
        send({ op: "add_note", slot, note: ny, start, dur: stepB, vel: es.vel });
        es.sel = pat.notes.length;   // will select the new note after refresh
        pat.notes.push([ny, start, stepB, es.vel, 0]);
        drag = { kind: "draw", idx: pat.notes.length - 1, offB: 0,
                 startY: py, baseVel: es.vel, orig: [ny, start, stepB, es.vel, 0], moved: false };
        draw();
      }
    }
  });
  cv.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const r = cv.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const py = (e.clientY - r.top) * (H / r.height);
    const bx = beat4x(px);
    const n = pat.notes[drag.idx];
    if (!n) return;
    if (drag.kind === "move") {
      let ns = Math.round((bx - drag.offB) / stepB) * stepB;
      ns = Math.max(0, Math.min(beats - n[2], ns));
      n[1] = ns;
      n[0] = note4y(py);
      drag.moved = true;
    } else if (drag.kind === "resize" || drag.kind === "draw") {
      let nd = Math.max(stepB, Math.round((bx - n[1]) / stepB) * stepB);
      nd = Math.min(nd, beats - n[1]);
      if (nd !== n[2]) {
        n[2] = nd;
        drag.moved = true;
      }
      if (drag.kind === "draw") {
        const dy = py - drag.startY;
        const nv = Math.max(0.05, Math.min(1, drag.baseVel - dy / (RH * 8)));
        if (Math.abs(nv - n[3]) > 0.001) {
          n[3] = nv;
          es.vel = nv;
          if (es.velCtl && es.velCtl._set) es.velCtl._set(nv);
          drag.moved = true;
        }
      }
    }
    draw();
  });
  cv.addEventListener("pointerup", () => {
    if (drag && (drag.kind === "move" || drag.kind === "resize" || drag.kind === "draw")) {
      const n = pat.notes[drag.idx];
      if (n && drag.moved) {
        const upd = { op: "update_note", slot, index: drag.idx,
                      note: n[0], start: n[1], dur: n[2] };
        if (drag.kind === "draw") upd.vel = n[3];
        send(upd);
      }
    }
    drag = null;
  });
  cv.addEventListener("dblclick", (e) => {
    const r = cv.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const py = (e.clientY - r.top) * (H / r.height);
    if (px < KW) return;
    if (Date.now() - (es.justCommitted || 0) < 500) return;  // don't delete a just-committed note
    const hit = hitNote(beat4x(px), note4y(py));
    if (hit >= 0) { send({ op: "remove_note", slot, index: hit }); es.sel = -1; }
  });
  cv.addEventListener("contextmenu", (e) => {
    // right-click toggles accent (with shift: glide)
    e.preventDefault();
    const r = cv.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const py = (e.clientY - r.top) * (H / r.height);
    const hit = hitNote(beat4x(px), note4y(py));
    if (hit >= 0) {
      const n = pat.notes[hit];
      const bit = e.shiftKey ? 2 : 1;
      const flags = (n[4] || 0) ^ bit;
      n[4] = flags;
      send({ op: "update_note", slot, index: hit, flags });
      draw();
    }
  });
  draw();
}

/* ---------------- drum grid (BeatBox) ---------------- */

function buildDrumGrid(cv, slot, m, es) {
  const pat = getPattern(m);
  const beats = pat.length * 4;
  const steps = beats * 4;            // 16th note steps
  const CH = 8, LW = 90, RH = 26;
  const W = 1400, H = CH * RH;
  cv.width = W; cv.height = H;
  cv.style.height = "230px";
  const ctx = cv.getContext("2d");
  const sw = (W - LW) / steps;

  function draw() {
    ctx.fillStyle = "#d8dae2"; ctx.fillRect(0, 0, W, H);
    for (let c = 0; c < CH; c++) {
      const y = c * RH;
      ctx.fillStyle = c % 2 ? "#cfd2dd" : "#d9dbe4";
      ctx.fillRect(LW, y, W - LW, RH);
      ctx.fillStyle = "#20222c";
      ctx.fillRect(0, y, LW, RH);
      ctx.fillStyle = "#9fb4e8";
      ctx.font = "10px Consolas, monospace";
      ctx.fillText((m.channels[c]?.sample || "ch" + (c + 1)).slice(0, 11), 5, y + 16);
      ctx.strokeStyle = "#b6b9c6";
      ctx.strokeRect(0, y + 0.5, W, RH);
    }
    for (let s = 0; s <= steps; s++) {
      const x = LW + s * sw;
      ctx.strokeStyle = s % 16 === 0 ? "#6a6f82" : (s % 4 === 0 ? "#9a9eb0" : "#c2c5d2");
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    const flOn = !pat.flourish || !!pat.flourish.on;
    pat.notes.forEach((n, i) => {
      const [key, start, , vel, flags] = n;
      const ch = key % 8;
      const x = LW + (start / 0.25) * sw;
      const y = ch * RH;
      if (flags & 4) {             // flourish hit: glowing blue
        ctx.globalAlpha = flOn ? 0.5 + vel * 0.5 : 0.15;
        ctx.shadowColor = "#4dc3ff";
        ctx.shadowBlur = flOn ? 8 : 0;
        ctx.fillStyle = i === es.sel ? "#e8811d" : "#2f9df5";
        ctx.fillRect(x + 1, y + 3, sw - 2, RH - 6);
        ctx.shadowBlur = 0;
      } else {
        ctx.globalAlpha = 0.4 + vel * 0.6;
        ctx.fillStyle = i === es.sel ? "#e8811d" : "#a3502a";
        ctx.fillRect(x + 1, y + 3, sw - 2, RH - 6);
      }
      ctx.globalAlpha = 1;
    });
    if (App.doc.transport.playing && App.doc.transport.mode === "pattern") {
      const pos = App.status.pos % beats;
      const x = LW + (pos / 0.25) * sw;
      ctx.strokeStyle = "#d3231c"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      ctx.lineWidth = 1;
    }
  }
  const oldHook = window._statusHook;
  window._statusHook = (st) => { if (oldHook) oldHook(st); draw(); };

  cv.addEventListener("pointerdown", (e) => {
    const r = cv.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / r.width);
    const py = (e.clientY - r.top) * (H / r.height);
    const ch = Math.floor(py / RH);
    if (px < LW) {                       // preview channel
      sendNote(slot, ch, true);
      setTimeout(() => sendNote(slot, ch, false), 200);
      return;
    }
    const step = Math.floor((px - LW) / sw);
    const start = step * 0.25;
    const hit = pat.notes.findIndex(n => (n[0] % 8) === ch && Math.abs(n[1] - start) < 0.12);
    if (hit >= 0) {
      if ((pat.notes[hit][4] || 0) & 4)   // clicking a flourish hit commits it
        send({ op: "flourish_commit", slot, index: hit });
      else send({ op: "remove_note", slot, index: hit });
    }
    else send({ op: "add_note", slot, note: ch, start, dur: 0.25, vel: es.vel });
  });
  draw();
}

/* ---------------- pattern options popup ---------------- */

function patternOptions(slot, m, key) {
  showModal("PATTERN " + key, (b) => {
    const row = el("div", "menu-row", b);
    [["Copy to…", () => {
        promptText("Copy pattern " + key + " to (e.g. B3)", "", (dst) => {
          dst = dst.toUpperCase().trim();
          if (/^[A-D](1[0-6]|[1-9])$/.test(dst))
            send({ op: "copy_pattern", slot, src: key, dst });
        });
      }],
     ["Clear", () => send({ op: "clear_pattern", slot, key })],
     ["Transpose +1", () => send({ op: "shift_pattern", slot, key, semis: 1 })],
     ["Transpose −1", () => send({ op: "shift_pattern", slot, key, semis: -1 })],
    ].forEach(([lab, fn]) => {
      const bt = el("button", "", row);
      bt.textContent = lab;
      bt.addEventListener("click", () => { closeModal(); fn(); });
    });
  });
}

function chordDialog(slot, m, es) {
  const keyName = App._chordKey || "C";
  const modeName = App._chordMode || "major";
  const templateId = App._chordTemplate || PROGRESSION_TEMPLATES[0].id;
  const stepsPerBeat = Math.max(1, Math.round(es.grid / 4));
  showModal("CHORDS " + patKey(m), (b) => {
    const info = el("div", "fl-info", b);
    info.textContent =
      "Use comma-separated steps (empty steps are rests). Example: Eb*2,,,Bb,,,Cm,,,Ab,,,. " +
      "*n sets hold length in grid steps.";
    const inp = el("input", "chord-input", b);
    inp.type = "text";
    inp.value = App._chordText || "";
    inp.placeholder = "Eb*2,,,Bb,,,Cm,,,Ab,,,";
    const err = el("div", "ai-status err", b);
    err.textContent = "";

    const row = el("div", "menu-row chord-tools-row", b);
    const keySel = el("select", "chord-sel", row);
    CHORD_KEYS.forEach((k) => {
      const opt = document.createElement("option");
      opt.value = k; opt.textContent = k;
      if (k === keyName) opt.selected = true;
      keySel.appendChild(opt);
    });
    const modeSel = el("select", "chord-sel", row);
    ["major", "minor"].forEach((mode) => {
      const opt = document.createElement("option");
      opt.value = mode; opt.textContent = mode.toUpperCase();
      if (mode === modeName) opt.selected = true;
      modeSel.appendChild(opt);
    });
    const tplSel = el("select", "chord-sel", row);
    PROGRESSION_TEMPLATES.forEach((tpl) => {
      const opt = document.createElement("option");
      opt.value = tpl.id; opt.textContent = tpl.label;
      if (tpl.id === templateId) opt.selected = true;
      tplSel.appendChild(opt);
    });
    const insBtn = el("button", "", row); insBtn.textContent = "Insert preset";
    const genBtn = el("button", "", row); genBtn.textContent = "Generate preset";
    const buildPreset = () => {
      const pc = CHORD_ROOT_TO_PC[keySel.value];
      const tpl = PROGRESSION_TEMPLATES.find((t) => t.id === tplSel.value) || PROGRESSION_TEMPLATES[0];
      return buildDiatonicProgressionText(pc, modeSel.value, tpl, stepsPerBeat);
    };
    genBtn.addEventListener("click", () => { inp.value = buildPreset(); });
    insBtn.addEventListener("click", () => {
      const txt = buildPreset();
      if (!inp.value.trim()) inp.value = txt;
      else inp.value += (inp.value.endsWith(",") ? "" : ",") + txt;
    });
    b._chInp = inp;
    b._chKeySel = keySel;
    b._chModeSel = modeSel;
    b._chTplSel = tplSel;
    b._chErr = err;
  }, [
    { label: "Cancel" },
    { label: "Apply", primary: true, onClick: () => {
        const modalBody = document.querySelector("#modal-root .modal .modal-body");
        if (!modalBody || !modalBody._chInp) return false;
        modalBody._chErr.textContent = "";
        const text = modalBody._chInp.value.trim();
        const parsed = parseChordGridText(text, 4 / es.grid, m.octave ?? 4, es.vel);
        if (parsed.error) {
          modalBody._chErr.textContent = parsed.error;
          return false;
        }
        const len = nextPatternLengthForBeats(parsed.totalBeats);
        if (!len) {
          modalBody._chErr.textContent = "This progression exceeds 8 measures and cannot fit in one pattern.";
          return false;
        }
        App._chordText = text;
        App._chordKey = modalBody._chKeySel.value;
        App._chordMode = modalBody._chModeSel.value;
        App._chordTemplate = modalBody._chTplSel.value;
        send({ op: "set_pattern_notes", slot, length: len, notes: parsed.notes });
      } },
  ]);
}

/* ---------------- flourish ---------------- */

const FLOURISH_THEMES = [
  ["major", "MAJOR"], ["minor", "MINOR"], ["jazzy", "JAZZY"],
  ["fast", "FAST"], ["mellow", "MELLOW"], ["syncopated", "SYNCOPATED"],
  ["arp", "ARP"], ["octaves", "OCTAVES"],
];

function flourishDialog(slot, m) {
  const pat = getPattern(m);
  const sel = new Set((pat.flourish && pat.flourish.themes) || App._flThemes || []);
  showModal("FLOURISH " + patKey(m), (b) => {
    const info = el("div", "fl-info", b);
    info.textContent =
      "Pick one or more themes. Flourish adds notes around your existing " +
      "ones to match them — it never removes or moves your notes. Added " +
      "notes glow blue in the editor; click one to keep it for good. " +
      "Reroll for a different take on the same themes.";
    const grid = el("div", "fl-themes", b);
    FLOURISH_THEMES.forEach(([id, label]) => {
      const bt = el("button", sel.has(id) ? "on" : "", grid);
      bt.textContent = label;
      bt.addEventListener("click", () => {
        if (sel.has(id)) sel.delete(id); else sel.add(id);
        bt.className = sel.has(id) ? "on" : "";
      });
    });
  }, [
    { label: "Remove all", onClick: () => send({ op: "flourish_clear", slot }) },
    { label: pat.flourish ? "Reroll" : "Generate", primary: true, onClick: () => {
        App._flThemes = [...sel];
        send({ op: "flourish", slot, themes: [...sel],
               seed: (Math.random() * 0x7fffffff) | 0 });
      } },
  ]);
}

/* =====================================================================
   Song sequencer
   ===================================================================== */

function renderSequencer(mv) {
  const wrap = el("div", "machine seq-wrap", mv);
  const head = el("div", "machine-head", wrap);
  el("div", "machine-title", head).textContent = "SEQUENCER";
  el("div", "spacer", head);

  const st = App._seqState = App._seqState || { measures: 32, follow: true, scroll: 0 };
  const zoomOut = el("button", "pattern-btn", head); zoomOut.textContent = "🔍−";
  zoomOut.addEventListener("click", () => { st.measures = Math.min(128, st.measures * 2); renderAll(); });
  const zoomIn = el("button", "pattern-btn", head); zoomIn.textContent = "🔍+";
  zoomIn.addEventListener("click", () => { st.measures = Math.max(8, st.measures / 2); renderAll(); });
  const follow = el("button", "pattern-btn" + (st.follow ? " on" : ""), head);
  follow.textContent = "FOLLOW";
  follow.addEventListener("click", () => { st.follow = !st.follow; renderAll(); });
  const clearB = el("button", "pattern-btn", head); clearB.textContent = "CLEAR SONG";
  clearB.addEventListener("click", () =>
    confirmBox("Clear song", "Remove all pattern blocks from the song?",
      () => send({ op: "song_clear" })));
  const hint = el("div", "", wrap);
  hint.style.cssText = "font-size:10px;color:#39405a;padding:0 6px 4px";
  hint.textContent = "Click a row to place the machine's current pattern · drag blocks to move · drag right edge to stretch · double-click removes · drag in the timeline to set a loop · click timeline to set play position.";

  const machines = App.doc.machines;
  const rows = machines.map((m, i) => ({ m, i })).filter(x => x.m);
  const RH = 34, LW = 110, TL = 22;
  const W = 1400, H = Math.max(rows.length, 4) * RH + TL;
  const cwrap = el("div", "seq-canvas-wrap", wrap);
  const cv = el("canvas", "", cwrap);
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  const mw = (W - LW) / st.measures;    // pixels per measure

  const colors = ["#8d9bd0", "#a4c58b", "#c5a48b", "#b98bc5", "#8bc5c0", "#c58b8b", "#c5bb8b"];

  function draw() {
    ctx.fillStyle = "#cfd2dc"; ctx.fillRect(0, 0, W, H);
    rows.forEach((row, r) => {
      const y = r * RH;
      ctx.fillStyle = r % 2 ? "#c6c9d5" : "#cfd2dc";
      ctx.fillRect(LW, y, W - LW, RH);
      ctx.fillStyle = "#20222c";
      ctx.fillRect(0, y, LW, RH);
      ctx.fillStyle = "#9fb4e8"; ctx.font = "bold 10px sans-serif";
      ctx.fillText(row.m.name.slice(0, 13), 6, y + 14);
      ctx.fillStyle = "#667";
      ctx.font = "8px sans-serif";
      ctx.fillText(App.catalog.machines[row.m.type].name, 6, y + 26);
      // ghost machine name in the row
      ctx.font = "bold 22px sans-serif";
      ctx.fillStyle = "rgba(90,95,115,0.12)";
      ctx.fillText(row.m.name, LW + 10, y + 25);
    });
    for (let mm = 0; mm <= st.measures; mm++) {
      const x = LW + mm * mw;
      ctx.strokeStyle = mm % 4 === 0 ? "#8a8fa2" : "#b6b9c6";
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H - TL); ctx.stroke();
    }
    // blocks
    App.doc.song.forEach(blk => {
      const r = rows.findIndex(x => x.i === blk.machine);
      if (r < 0) return;
      const x = LW + blk.start * mw, y = r * RH;
      const w = blk.length * mw;
      ctx.fillStyle = colors[blk.machine % colors.length];
      ctx.fillRect(x + 1, y + 2, w - 2, RH - 4);
      ctx.strokeStyle = "#464a5c";
      ctx.strokeRect(x + 1, y + 2, w - 2, RH - 4);
      ctx.fillStyle = "#1d1f29"; ctx.font = "bold 11px sans-serif";
      ctx.fillText(BANK_NAMES[blk.bank] + (blk.pattern + 1), x + 6, y + RH / 2 + 4);
      // stretch handle
      ctx.fillStyle = "#464a5c";
      ctx.fillRect(x + w - 5, y + 6, 3, RH - 12);
    });
    // timeline
    ctx.fillStyle = "#9ba0b2";
    ctx.fillRect(0, H - TL, W, TL);
    ctx.fillStyle = "#31343f"; ctx.font = "10px Consolas, monospace";
    for (let mm = 0; mm < st.measures; mm += (st.measures > 48 ? 4 : 1)) {
      ctx.fillText(mm + 1, LW + mm * mw + 3, H - 7);
    }
    // loop cursors
    const loop = App.doc.transport.loop;
    if (loop && loop[1] > loop[0]) {
      const x1 = LW + loop[0] * mw, x2 = LW + loop[1] * mw;
      ctx.fillStyle = "rgba(232,163,61,0.25)";
      ctx.fillRect(x1, H - TL, x2 - x1, TL);
      ctx.fillStyle = "#e8811d";
      ctx.fillRect(x1, H - TL, 3, TL);
      ctx.fillRect(x2 - 3, H - TL, 3, TL);
    }
    // playhead
    if (App.doc.transport.mode === "song") {
      const x = LW + (App.status.pos / 4) * mw;
      ctx.strokeStyle = "#16181f"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      ctx.lineWidth = 1;
    }
  }
  const oldHook = window._statusHook;
  window._statusHook = (s) => { if (oldHook) oldHook(s); draw(); };

  function blockAt(meas, r) {
    return App.doc.song.find(b => {
      const br = rows.findIndex(x => x.i === b.machine);
      return br === r && meas >= b.start && meas < b.start + b.length;
    });
  }

  let drag = null;
  cv.addEventListener("pointerdown", (e) => {
    cv.setPointerCapture(e.pointerId);
    const rct = cv.getBoundingClientRect();
    const px = (e.clientX - rct.left) * (W / rct.width);
    const py = (e.clientY - rct.top) * (H / rct.height);
    if (py > H - TL) {   // timeline: loop drag or seek
      const meas = Math.floor((px - LW) / mw);
      drag = { kind: "timeline", startMeas: meas, moved: false };
      return;
    }
    const r = Math.floor(py / RH);
    if (r < 0 || r >= rows.length || px < LW) {
      if (px < LW && r >= 0 && r < rows.length) {
        setView({ kind: "machine", slot: rows[r].i });
      }
      return;
    }
    const meas = Math.floor((px - LW) / mw);
    const blk = blockAt(meas, r);
    if (blk) {
      const bx = LW + blk.start * mw, bw = blk.length * mw;
      const nearEnd = px > bx + bw - 12;
      drag = { kind: nearEnd ? "stretch" : "moveblk", blk, offMeas: meas - blk.start, moved: false };
    } else {
      drag = { kind: "placed", meas, row: r, moved: false };
    }
  });
  cv.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const rct = cv.getBoundingClientRect();
    const px = (e.clientX - rct.left) * (W / rct.width);
    const meas = Math.floor((px - LW) / mw);
    if (drag.kind === "timeline") {
      if (meas !== drag.startMeas) {
        drag.moved = true;
        const lo = Math.min(meas, drag.startMeas), hi = Math.max(meas, drag.startMeas) + 1;
        App.doc.transport.loop = [Math.max(0, lo), hi];
        draw();
      }
    } else if (drag.kind === "moveblk") {
      const ns = Math.max(0, meas - drag.offMeas);
      if (ns !== drag.blk.start) { drag.blk.start = ns; drag.moved = true; draw(); }
    } else if (drag.kind === "stretch") {
      const nl = Math.max(1, meas - drag.blk.start + 1);
      if (nl !== drag.blk.length) { drag.blk.length = nl; drag.moved = true; draw(); }
    }
  });
  cv.addEventListener("pointerup", (e) => {
    if (!drag) return;
    if (drag.kind === "timeline") {
      if (drag.moved) {
        const loop = App.doc.transport.loop;
        if (loop[1] - loop[0] <= 1 && loop[0] === drag.startMeas) {
          send({ op: "transport", loop: null });
        } else send({ op: "transport", loop });
      } else {
        // seek + clear loop on plain click
        send({ op: "transport", pos: Math.max(0, drag.startMeas) * 4 });
      }
    } else if (drag.kind === "moveblk" || drag.kind === "stretch") {
      if (drag.moved) {
        send({ op: "song_update", id: drag.blk.id, start: drag.blk.start, length: drag.blk.length });
      }
    } else if (drag.kind === "placed" && !drag.moved) {
      const placed = { meas: drag.meas, row: drag.row };
      const row = rows[placed.row];
      pickPatternFor(row.i, row.m, (bank, pattern) => {
        send({ op: "song_add", machine: row.i, bank, pattern, start: placed.meas, length: 1 });
      });
    }
    drag = null;
  });
  cv.addEventListener("dblclick", (e) => {
    const rct = cv.getBoundingClientRect();
    const px = (e.clientX - rct.left) * (W / rct.width);
    const py = (e.clientY - rct.top) * (H / rct.height);
    const r = Math.floor(py / RH);
    if (r < 0 || r >= rows.length || py > H - TL) return;
    const meas = Math.floor((px - LW) / mw);
    const blk = blockAt(meas, r);
    if (blk) send({ op: "song_remove", id: blk.id });
  });
  draw();
}

function pickPatternFor(slot, m, onPick) {
  showModal("SELECT PATTERN — " + m.name, (b) => {
    BANK_NAMES.forEach((bn, bi) => {
      const row = el("div", "menu-row", b);
      el("label", "", row).textContent = "Bank " + bn;
      const grid = el("div", "tb-group", row);
      for (let i = 0; i < 16; i++) {
        const bt = el("button", "", grid);
        bt.textContent = i + 1;
        const has = (m.patterns[bn + (i + 1)]?.notes?.length || 0) > 0;
        bt.style.color = has ? "#7be87b" : "#778";
        bt.addEventListener("click", () => { closeModal(); onPick(bi, i); });
      }
    });
  });
}
