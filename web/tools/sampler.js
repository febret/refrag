/* Sampler machine panel + dedicated "SAMPLE EDITOR" (replaces the piano
   roll / drum grid for this machine type — see renderSamplerEditor). */
"use strict";

const SAMPLER_BANKS = ["A", "B", "C", "D"];
const SAMPLER_PATTERNS_PER_BANK = 16;
const SAMPLER_DEPTH_RANGES = { tone: [-1, 1], distortion: [-1, 1], pitch: [-24, 24] };
const SAMPLER_ENV_NAMES = ["volume", "tone", "distortion", "pitch"];

function samplerKey(m) { return SAMPLER_BANKS[m.bank] + (m.pattern + 1); }

function defaultSamplerSettings() {
  const envelopes = {};
  SAMPLER_ENV_NAMES.forEach((name) => {
    envelopes[name] = { attack: 0, decay: 0, sustain: 1, release: 0 };
    if (name !== "volume") envelopes[name].depth = 0;
  });
  return {
    sample: "", start: 0, end: 1, gain: 1, tone: 0, bass: 0, mid: 0, high: 0,
    distortion: 0, pitch: 0, envelopes,
  };
}

function samplerSettingsFor(m, key) {
  return ensureSamplerPattern(m, key).sampler;
}

/* Attach a real pattern + sampler-settings object onto the live App.doc
   machine (mirrors the server's get_pattern(..., create=True) /
   setdefault("sampler", ...) behavior) so any later local mutation
   (knob drags, crop handles, sample assignment) sticks even before the
   op round-trips through the server. */
function ensureSamplerPattern(m, key) {
  let pat = m.patterns[key];
  if (!pat) {
    pat = { length: 1, notes: [], sampler: defaultSamplerSettings() };
    m.patterns[key] = pat;
  } else if (!pat.sampler) {
    pat.sampler = defaultSamplerSettings();
  }
  return pat;
}

function samplerPreview(slot, note) {
  let active = true;
  let started = false;
  ensureAudio().then(() => {
    if (!active) return;
    started = true;
    send({ op: "note", slot, note, on: true, vel: 1 });
  });
  return () => {
    active = false;
    if (started) send({ op: "note", slot, note, on: false, vel: 1 });
  };
}

/* ---------------- compact machine panel ---------------- */

function buildSampler(body, slot, m) {
  const key = samplerKey(m);
  const s = samplerSettingsFor(m, key);
  const g = makeGroup("SAMPLE", body);
  g.box.style.flex = "1 1 100%";
  const row = el("div", "bb-channel", g.row);
  row.style.flex = "1";
  const info = el("div", "bb-lcd", row);
  info.style.flex = "1"; info.style.height = "40px"; info.style.fontSize = "12px";
  info.textContent = key + "  " + (s.sample || "(empty)");
  info.title = "Open the SAMPLE EDITOR (header button) to manage banks and patterns";
  const play = el("button", "bb-play", row);
  play.innerHTML = "&#9654;";
  play.title = s.sample ? "Hold to preview " + key : "Assign a sample to preview";
  play.disabled = !s.sample;
  const note = m.bank * SAMPLER_PATTERNS_PER_BANK + m.pattern;
  let stopPreview = null;
  play.addEventListener("pointerdown", () => {
    stopPreview = samplerPreview(slot, note);
  });
  const releasePreview = () => {
    if (stopPreview) stopPreview();
    stopPreview = null;
  };
  play.addEventListener("pointerup", releasePreview);
  play.addEventListener("pointerleave", releasePreview);
  outGroup(body, slot, m);
}

/* ---------------- dedicated sample editor ---------------- */

function renderSamplerEditor(mv, slot, m) {
  const panel = el("div", "machine editor-panel sampler-editor-panel", mv);
  const tb = el("div", "editor-toolbar", panel);

  const state = App._samplerEd = App._samplerEd || {};
  const es = state[slot] = state[slot] || { waveform: null, waveformName: null, loadingName: null };

  // bank buttons
  let grp = el("div", "tb-group", tb);
  SAMPLER_BANKS.forEach((b, bi) => {
    const bt = el("button", m.bank === bi ? "bank-on" : "", grp);
    bt.textContent = b;
    bt.addEventListener("click", () => send({ op: "select_pattern", slot, bank: bi }));
  });

  // pattern buttons 1-16, filled based on sampler.sample (not notes)
  grp = el("div", "tb-group", tb);
  for (let i = 0; i < SAMPLER_PATTERNS_PER_BANK; i++) {
    const k = SAMPLER_BANKS[m.bank] + (i + 1);
    const p = m.patterns[k];
    const filled = !!(p && p.sampler && p.sampler.sample);
    const bt = el("button", m.pattern === i ? "on" : "", grp);
    bt.textContent = i + 1;
    if (filled) bt.style.color = "#7be87b";
    bt.addEventListener("click", () => send({ op: "select_pattern", slot, pattern: i }));
  }

  const key = samplerKey(m);
  const pat = ensureSamplerPattern(m, key);
  const s = pat.sampler;

  // measures / length
  grp = el("div", "tb-group", tb);
  el("div", "tb-label", grp).textContent = "LENGTH";
  [1, 2, 4, 8].forEach((L) => {
    const bt = el("button", pat.length === L ? "on" : "", grp);
    bt.textContent = L;
    bt.addEventListener("click", () => send({ op: "set_pattern_length", slot, key, length: L }));
  });

  // clear / copy / paste (preserves the full pattern: length + sampler settings)
  grp = el("div", "tb-group", tb);
  const clr = el("button", "", grp); clr.textContent = "CLEAR";
  clr.addEventListener("click", () =>
    confirmBox("Clear pattern", "Remove the sample assignment from " + key + "?",
      () => send({ op: "clear_pattern", slot, key })));
  const cpy = el("button", "", grp); cpy.textContent = "COPY";
  cpy.title = "Copy full pattern (length + sample settings)";
  const pst = el("button", "", grp); pst.textContent = "PASTE";
  pst.title = "Paste the copied pattern into " + key;
  pst.disabled = !App._samplerClipboard;
  cpy.addEventListener("click", () => {
    App._samplerClipboard = { length: pat.length, sampler: JSON.parse(JSON.stringify(s)) };
    pst.disabled = false;
  });
  pst.addEventListener("click", () => {
    const clip = App._samplerClipboard;
    if (!clip) { infoBox("Paste pattern", "No copied pattern is available yet."); return; }
    pasteSamplerPattern(slot, key, clip);
  });

  // multi-file ordered import into consecutive slots of the current bank
  grp = el("div", "tb-group", tb);
  const imp = el("button", "", grp); imp.textContent = "IMPORT FILES\u2026";
  imp.title = "Upload multiple files into consecutive slots starting at " + key;
  imp.addEventListener("click", () => importSamplerFiles(slot, m));

  // preview (held while pointer is down)
  grp = el("div", "tb-group", tb);
  const prev = el("button", "", grp);
  prev.textContent = "\u25B6 PREVIEW";
  prev.disabled = !s.sample;
  prev.title = s.sample ? "Hold to preview " + key : "Assign a sample to preview";
  const noteNum = m.bank * SAMPLER_PATTERNS_PER_BANK + m.pattern;
  let stopPreview = null;
  prev.addEventListener("pointerdown", () => {
    stopPreview = samplerPreview(slot, noteNum);
  });
  const releasePreview = () => {
    if (stopPreview) stopPreview();
    stopPreview = null;
  };
  prev.addEventListener("pointerup", releasePreview);
  prev.addEventListener("pointerleave", releasePreview);

  const wrap = el("div", "sampler-ed-wrap", panel);
  buildSamplerWaveform(wrap, slot, key, s, es);
  buildSamplerControls(wrap, slot, key, s);

  const envRow = el("div", "sampler-env-row", panel);
  SAMPLER_ENV_NAMES.forEach((name) => buildEnvelopeSection(envRow, slot, key, name, s));
}

/* Paste as one atomic op (server-provided set_sampler_pattern) rather than
   a burst of individual set_sampler_param messages: the individual-op
   approach could have each crop value clamp against the destination
   pattern's *current* (not yet fully-pasted) start/end, and — since
   set_sampler_param is a lightweight echo excluded from the sender —
   this client would never see the canonical merged result. A single
   full-document-broadcast op avoids both problems. */
function pasteSamplerPattern(slot, key, clip) {
  send({
    op: "set_sampler_pattern",
    slot, key,
    length: clip.length,
    sampler: JSON.parse(JSON.stringify(clip.sampler)),
  });
}

/* ---------------- ordered multi-file import ---------------- */

function importSamplerFiles(slot, m) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.multiple = true;
  inp.accept = "audio/*,.wav,.mp3,.m4a,.aac,.ogg,.webm,.flac";
  inp.addEventListener("change", async () => {
    const files = Array.from(inp.files || []);
    if (!files.length) return;
    const bank = m.bank;
    const startPattern = m.pattern;
    const capacity = SAMPLER_PATTERNS_PER_BANK - startPattern;
    const toImport = files.slice(0, capacity);
    const skipped = files.length - toImport.length;
    const names = [];
    const failed = [];
    for (const file of toImport) {
      const base = (file.name || "sample").replace(/\.[^.]*$/, "")
        .replace(/[^A-Za-z0-9 _\-]/g, "").slice(0, 40) || "sample";
      try {
        const isWav = /\.wav$/i.test(file.name || "") || (file.type || "").includes("wav");
        const blob = await audioDataToWavBlob(await file.arrayBuffer(), isWav);
        const name = await uploadWavBlob(blob, base);
        names.push(name);
      } catch (e) {
        failed.push((file.name || "file") + ": " + (e.message || "upload failed"));
      }
    }
    const startKey = SAMPLER_BANKS[bank] + (startPattern + 1);
    if (names.length) {
      send({ op: "assign_sampler_bank", slot, bank, start: startPattern, samples: names });
    }
    if (failed.length || skipped > 0) {
      showModal("IMPORT FILES", (b) => {
        if (names.length) {
          el("div", "menu-row", b).textContent =
            names.length + " file(s) assigned starting at " + startKey + ".";
        }
        if (failed.length) {
          el("div", "menu-row", b).textContent = failed.length + " file(s) failed to upload:";
          const list = el("div", "file-list", b);
          failed.forEach((msg) => { el("div", "fitem", list).textContent = msg; });
        }
        if (skipped > 0) {
          el("div", "menu-row", b).textContent = skipped + " file(s) skipped \u2014 only " +
            capacity + " consecutive slot(s) available from " + startKey + ".";
        }
      });
    } else {
      showToast(names.length + " file(s) assigned starting at " + startKey);
    }
  });
  inp.click();
}

/* ---------------- waveform crop view ---------------- */

function ensureSamplerWaveform(s, es, onLoaded) {
  if (!s.sample) { es.waveform = null; es.waveformName = null; return; }
  if (es.waveformName === s.sample && es.waveform) return;
  if (es.loadingName === s.sample) return;
  es.loadingName = s.sample;
  fetch("/api/samples/waveform?name=" + encodeURIComponent(s.sample) + "&points=1000")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("waveform unavailable"))))
    .then((wf) => {
      es.loadingName = null;
      es.waveform = wf;
      es.waveformName = wf.name;
      onLoaded();
    })
    .catch(() => { es.loadingName = null; });
}

function buildSamplerWaveform(parent, slot, key, s, es) {
  const box = el("div", "sampler-wave-box", parent);
  el("div", "tb-label", box).textContent = "WAVEFORM \u2014 drag the green handles to crop";
  const cvWrap = el("div", "editor-canvas-wrap sampler-wave-wrap", box);
  const cv = el("canvas", "", cvWrap);
  const W = 1000, H = 140;
  cv.width = W; cv.height = H;
  cv.style.height = H + "px";
  const ctx = cv.getContext("2d");
  const info = el("div", "sampler-wave-info", box);

  function render() {
    ctx.fillStyle = "#10142e"; ctx.fillRect(0, 0, W, H);
    const wf = es.waveform;
    if (wf && s.sample && wf.name === s.sample) {
      const n = wf.min.length;
      const mid = H / 2;
      ctx.strokeStyle = "#5ad1ff";
      for (let i = 0; i < n; i++) {
        const x = (i / Math.max(1, n - 1)) * W;
        const yMin = mid - wf.min[i] * mid * 0.95;
        const yMax = mid - wf.max[i] * mid * 0.95;
        ctx.beginPath(); ctx.moveTo(x, yMin); ctx.lineTo(x, yMax); ctx.stroke();
      }
      info.textContent = wf.name + "  " + wf.duration.toFixed(2) + "s  peak " + wf.peak.toFixed(3);
    } else {
      ctx.fillStyle = "#667"; ctx.font = "13px sans-serif";
      ctx.fillText(s.sample ? "Loading waveform\u2026" : "No sample assigned", 12, H / 2);
      info.textContent = s.sample || "";
    }
    const x0 = s.start * W, x1 = s.end * W;
    ctx.fillStyle = "rgba(0,0,0,0.55)";
    if (x0 > 0) ctx.fillRect(0, 0, x0, H);
    if (x1 < W) ctx.fillRect(x1, 0, W - x1, H);
    ctx.strokeStyle = "#7be87b"; ctx.lineWidth = 2;
    [x0, x1].forEach((x) => { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); });
    ctx.lineWidth = 1;
    ctx.fillStyle = "#7be87b";
    [x0, x1].forEach((x) => { ctx.fillRect(x - 5, 0, 10, 12); ctx.fillRect(x - 5, H - 12, 10, 12); });
  }

  ensureSamplerWaveform(s, es, render);
  render();

  let dragHandle = null;
  const HIT = 16;
  function toX(clientX) {
    const r = cv.getBoundingClientRect();
    return (clientX - r.left) * (W / Math.max(1, r.width));
  }
  cv.addEventListener("pointerdown", (e) => {
    if (!s.sample) return;
    const x = toX(e.clientX);
    const x0 = s.start * W, x1 = s.end * W;
    const dStart = Math.abs(x - x0), dEnd = Math.abs(x - x1);
    if (dStart <= HIT && dStart <= dEnd) dragHandle = "start";
    else if (dEnd <= HIT) dragHandle = "end";
    else dragHandle = null;
    if (dragHandle) cv.setPointerCapture(e.pointerId);
  });
  cv.addEventListener("pointermove", (e) => {
    if (!dragHandle) return;
    const f = Math.max(0, Math.min(1, toX(e.clientX) / W));
    if (dragHandle === "start") s.start = Math.min(f, s.end - 0.001);
    else s.end = Math.max(f, s.start + 0.001);
    render();
  });
  const commit = () => {
    if (!dragHandle) return;
    const field = dragHandle;
    dragHandle = null;
    send({ op: "set_sampler_param", slot, key, param: field, value: s[field] });
  };
  cv.addEventListener("pointerup", commit);
  cv.addEventListener("pointercancel", commit);
}

/* ---------------- source picker + tone/gain/pitch controls ---------------- */

/* set_sampler_param is a "lightweight echo" op: the server excludes the
   sender from its opecho broadcast, so the client that made the change
   must apply it locally and re-render itself rather than waiting on an
   echo that will never arrive for this tab. */
function assignSamplerSample(slot, key, s, name) {
  s.sample = name;
  send({ op: "set_sampler_param", slot, key, param: "sample", value: name });
  renderAll();
}

function buildSamplerControls(parent, slot, key, s) {
  const g0 = makeGroup("SAMPLE SOURCE", parent);
  const lcd = el("div", "bb-lcd", g0.row);
  lcd.style.flex = "1"; lcd.style.height = "40px"; lcd.style.fontSize = "12px";
  lcd.textContent = s.sample || "(no sample assigned)";
  lcd.title = "Click to choose a sample";
  lcd.addEventListener("click", () => {
    pickSample("SELECT SAMPLE \u2014 " + key, (name) => assignSamplerSample(slot, key, s, name));
  });
  const upBtn = el("button", "pattern-btn", g0.row);
  upBtn.textContent = "UPLOAD"; upBtn.style.height = "40px";
  upBtn.addEventListener("click", () => pickAndUploadSample((name) =>
    assignSamplerSample(slot, key, s, name)));
  const recBtn = el("button", "pattern-btn", g0.row);
  recBtn.textContent = "RECORD"; recBtn.style.height = "40px";
  recBtn.addEventListener("click", () => recordSampleModal((name) =>
    assignSamplerSample(slot, key, s, name)));

  const g1 = makeGroup("TONE / GAIN", parent);
  const mkKnob = (label, field, min, max, curve) => {
    const w = makeKnob({ label, min, max, default: s[field], curve }, s[field], (v) => {
      s[field] = v;
      send({ op: "set_sampler_param", slot, key, param: field, value: v });
    });
    g1.row.appendChild(w);
    return w;
  };
  mkKnob("Gain", "gain", 0, 16);
  mkKnob("Tone", "tone", -1, 1);
  mkKnob("Bass", "bass", -12, 12);
  mkKnob("Mid", "mid", -12, 12);
  mkKnob("High", "high", -12, 12);
  mkKnob("Dist", "distortion", 0, 1);
  mkKnob("Pitch", "pitch", -24, 24, "int");

  const normBtn = el("button", "pattern-btn", g1.row);
  normBtn.textContent = "NORMALIZE"; normBtn.style.height = "40px";
  normBtn.title = "Boost gain so the cropped region peaks near 0 dBFS";
  normBtn.addEventListener("click", async () => {
    if (!s.sample) { showToast("Assign a sample first", true); return; }
    normBtn.disabled = true;
    try {
      const r = await fetch("/api/sampler/normalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room: App.room, slot, key }),
      });
      const res = await r.json();
      if (!r.ok) throw new Error(res.error || "normalize failed");
      showToast("Normalized \u2014 gain " + res.gain.toFixed(2) + "x (peak " + res.peak.toFixed(3) + ")");
    } catch (e) {
      showToast(e.message, true);
    } finally {
      normBtn.disabled = false;
    }
  });
}

/* ---------------- fixed-span ADSR envelope sections ---------------- */

function buildEnvelopeSection(parent, slot, key, name, s) {
  const env = s.envelopes[name];
  const g = makeGroup(name.toUpperCase() + " ENV", parent);
  g.box.classList.add("sampler-env-box");

  const cv = el("canvas", "sampler-env-canvas", g.box);
  const W = 210, H = 64;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");

  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#10142e"; ctx.fillRect(0, 0, W, H);
    const a = env.attack, d = env.decay, sus = env.sustain, r = env.release;
    const top = 4, bottom = H - 4;
    const ampY = (v) => bottom - v * (bottom - top);
    const relStart = Math.max(a + d, 1 - r);
    const pts = [
      [0, ampY(0)],
      [a * W, ampY(1)],
      [(a + d) * W, ampY(sus)],
      [relStart * W, ampY(sus)],
      [W, ampY(0)],
    ];
    ctx.beginPath();
    ctx.moveTo(0, bottom);
    pts.forEach((p) => ctx.lineTo(p[0], p[1]));
    ctx.lineTo(W, bottom);
    ctx.closePath();
    ctx.fillStyle = "rgba(232,163,61,0.35)";
    ctx.fill();
    ctx.strokeStyle = "#e8a33d"; ctx.lineWidth = 2;
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1])));
    ctx.stroke();
    ctx.lineWidth = 1;
  }
  draw();

  const TIMING_FIELDS = ["attack", "decay", "release"];
  const mkKnob = (label, field, min, max, curve) => {
    let w;
    w = makeKnob({ label, min, max, default: env[field], curve }, env[field], (v) => {
      if (TIMING_FIELDS.includes(field)) {
        // Mirror the server's _op_set_sampler_param timing clamp so the
        // initiating browser can't diverge from the canonical state: the
        // opecho for set_sampler_param excludes the sender, so this
        // client must apply the same "attack + decay + release <= 1"
        // clamp itself rather than waiting on an echo that never arrives.
        const others = TIMING_FIELDS.filter((f) => f !== field)
          .reduce((sum, f) => sum + env[f], 0);
        v = Math.min(v, Math.max(0, 1 - others));
        w._set(v);
      }
      env[field] = v;
      draw();
      send({ op: "set_sampler_param", slot, key, param: field, envelope: name, value: v });
    });
    g.row.appendChild(w);
    return w;
  };
  mkKnob("Attack", "attack", 0, 1);
  mkKnob("Decay", "decay", 0, 1);
  mkKnob("Sustain", "sustain", 0, 1);
  mkKnob("Release", "release", 0, 1);
  if (name !== "volume") {
    const [lo, hi] = SAMPLER_DEPTH_RANGES[name];
    mkKnob("Depth", "depth", lo, hi, name === "pitch" ? "int" : undefined);
  }
}
