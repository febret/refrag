/* Refrag client application core: WS sync, view routing, control panel. */
"use strict";

const App = {
  ws: null,
  doc: null,
  catalog: null,
  sampleLib: { factory: [], user: [] },
  room: new URLSearchParams(location.search).get("room") || "default",
  view: { kind: "machine", slot: 0 },   // machine | fx | mixer | master | seq | looper
  editorOpen: {},                        // slot -> bool (pattern editor shown)
  status: { pos: 0, vu: [], master_vu: [0, 0], auto: {}, looper: {} },
  sr: 44100,
  block: 2048,
  suppress: 0,
};
const AUDIO_SAMPLE_RATES = [22050, 32000, 44100, 48000, 88200, 96000];
const AUDIO_BLOCK_SIZES = [256, 512, 1024, 2048, 4096];

/* ---------------- websocket ---------------- */

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws?room=${encodeURIComponent(App.room)}`);
  ws.binaryType = "arraybuffer";
  App.ws = ws;
  ws.onmessage = (ev) => {
    if (ev.data instanceof ArrayBuffer) { window.streamPlayer.push(ev.data); return; }
    const msg = JSON.parse(ev.data);
    if (msg.type === "hello") {
      const changed = syncAudioConfig({ sample_rate: msg.sr, block_size: msg.block });
      if (changed && window.streamPlayer.enabled) ensureAudio();
    }
    else if (msg.type === "doc") {
      App.doc = msg.doc;
      syncAudioConfig(msg.doc.audio);
      renderAll();
    } else if (msg.type === "opecho") {
      applyEcho(msg.req);
    } else if (msg.type === "status") {
      const changed = syncAudioConfig(msg.audio || msg.audio_config);
      App.status = msg;
      updateStatusUI();
      if (changed && window.streamPlayer.enabled) ensureAudio();
    } else if (msg.type === "users") {
      document.getElementById("cp-users").innerHTML = "&#128101; " + msg.count;
    } else if (msg.type === "note") {
      flashRemoteNote(msg.slot, msg.note, msg.on);
    }
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

function send(op) {
  if (App.ws && App.ws.readyState === 1) App.ws.send(JSON.stringify(op));
}

function syncAudioConfig(audio) {
  if (!audio) return false;
  const prevSr = App.sr;
  const prevBlock = App.block;
  if (!App.doc) App.doc = {};
  App.doc.audio = App.doc.audio || {};
  if (audio.sample_rate) {
    App.doc.audio.sample_rate = audio.sample_rate;
    App.sr = audio.sample_rate;
  }
  if (audio.block_size) {
    App.doc.audio.block_size = audio.block_size;
    App.block = audio.block_size;
  }
  return prevSr !== App.sr || prevBlock !== App.block;
}

function estimateLatencyMs(sampleRate, blockSize) {
  if (!sampleRate || !blockSize) return 0;
  return 1000 * blockSize / sampleRate;
}

function closestOptionIndex(values, value) {
  let best = 0;
  let bestDist = Infinity;
  values.forEach((v, i) => {
    const d = Math.abs(v - value);
    if (d < bestDist) { bestDist = d; best = i; }
  });
  return best;
}

/* Apply a remote continuous-control echo to our local doc without rebuild. */
function applyEcho(op) {
  const d = App.doc;
  if (!d) return;
  try {
    if (op.op === "set_param") d.machines[op.slot].params[op.param] = op.value;
    else if (op.op === "set_mixer") {
      if (op.param === "mute" || op.param === "solo") d.machines[op.slot][op.param] = op.value;
      else d.machines[op.slot].mixer[op.param] = op.value;
    }
    else if (op.op === "set_master") d.master.params[op.param] = op.value;
    else if (op.op === "set_effect_param") {
      const fx = op.target === "master" ? d.master.effects : d.machines[op.slot].effects;
      if (op.param === "bypass") fx[op.index].bypass = op.value;
      else fx[op.index].params[op.param] = op.value;
    }
    else if (op.op === "mod_param") d.machines[op.slot].components[op.bay].params[op.param] = op.value;
    else if (op.op === "set_channel_param") {
      const ch = d.machines[op.slot].channels[op.channel];
      if (["mute", "solo", "mute_group", "sample"].includes(op.param)) ch[op.param] = op.value;
      else ch.params[op.param] = op.value;
    }
    else if (op.op === "set_harmonic") d.machines[op.slot][op.table][op.index] = op.value;
    else if (op.op === "set_sample_param" && !["add", "remove", "select"].includes(op.param))
      d.machines[op.slot].samples[op.index][op.param] = op.value;
  } catch (e) { /* stale echo */ }
  // update widget positions on the open view
  if (window._echoRefresh) window._echoRefresh(op);
}

/* ---------------- fixed rack views ---------------- */

const FIXED_VIEWS = [
  { kind: "fx", label: "EFFECTS" },
  { kind: "mixer", label: "MIXER" },
  { kind: "master", label: "MASTER" },
  { kind: "seq", label: "SEQUENCER" },
  { kind: "looper", label: "LOOPER" },
];

function renderRackbar() {
  const bar = document.getElementById("rackbar");
  bar.innerHTML = "";
  App.doc.machines.forEach((m, i) => {
    const d = el("div", "rack-dot" + (m ? " filled" : "") +
      (App.view.kind === "machine" && App.view.slot === i ? " sel" : ""), bar);
    d.title = m ? m.name : "empty slot " + (i + 1);
    d.addEventListener("click", () => {
      if (m) setView({ kind: "machine", slot: i });
      else showMachineMgmt();
    });
  });
  el("div", "rack-spacer", bar);
  FIXED_VIEWS.forEach(v => {
    const d = el("div", "rack-dot fixed" + (App.view.kind === v.kind ? " sel" : ""), bar);
    d.title = v.label;
    d.addEventListener("click", () => setView({ kind: v.kind }));
  });
}

function setView(v) {
  App.view = v;
  renderAll();
}

function renderAll() {
  if (!App.doc || !App.catalog) return;
  renderRackbar();
  updateTransportUI();
  const mv = document.getElementById("machineview");
  mv.innerHTML = "";
  window._echoRefresh = null;
  window._statusHook = null;
  const v = App.view;
  if (v.kind === "machine") {
    const m = App.doc.machines[v.slot];
    if (!m) {
      const empty = el("div", "seq-wrap", mv);
      empty.innerHTML = "<div style='text-align:center;padding:60px;color:#667'>" +
        "Empty slot — open Machine Management (grid button, lower left) to add a machine.</div>";
      return;
    }
    renderMachine(mv, v.slot, m);
    if (App.editorOpen[v.slot]) renderPatternEditor(mv, v.slot, m);
  } else if (v.kind === "fx") renderEffectsRack(mv);
  else if (v.kind === "mixer") renderMixer(mv);
  else if (v.kind === "master") renderMaster(mv);
  else if (v.kind === "seq") renderSequencer(mv);
  else if (v.kind === "looper") renderLooper(mv);
}

/* ---------------- transport / control panel ---------------- */

function updateTransportUI() {
  const t = App.doc.transport;
  document.getElementById("btn-play").classList.toggle("on", t.playing);
  document.getElementById("btn-rec").classList.toggle("on", t.record);
  document.getElementById("rec-outline").classList.toggle("on", t.record);
  const mode = document.getElementById("btn-mode");
  mode.textContent = t.mode.toUpperCase();
  mode.classList.toggle("song", t.mode === "song");
  document.getElementById("cp-song").textContent = App.doc.name;
}

function updateStatusUI() {
  const pos = App.status.pos || 0;
  const meas = Math.floor(pos / 4) + 1;
  const beat = Math.floor(pos % 4) + 1;
  const six = Math.floor((pos % 1) * 4) + 1;
  document.getElementById("cp-pos").textContent = `${meas}.${beat}.${six}`;
  const perf = App.status.perf || {};
  const xrun = perf.render_drops ?? perf.overruns ?? 0;
  const netDrops = perf.audio_drops ?? 0;
  const dropEl = document.getElementById("cp-drop");
  if (dropEl) {
    dropEl.textContent = `XRUN ${xrun}`;
    dropEl.title = `Render overruns: ${xrun} · Stream queue drops: ${netDrops}`;
  }
  if (window._statusHook) window._statusHook(App.status);
  // automated control outlines
  document.querySelectorAll(".knob, .vslider").forEach(k => {
    if (!k._autoKey) return;
    k.classList.toggle("automated-pattern", !!App._patAuto?.has(k._autoKey));
    k.classList.toggle("automated-song", !!App._songAuto?.has(k._autoKey));
  });
  // live automation playback: move widgets
  const auto = App.status.auto || {};
  for (const key in auto) {
    const w = document.querySelector(`[data-autokey="${key}"]`);
    if (w && w._set && !w.classList.contains("dragging")) w._set(auto[key]);
  }
}

function computeAutoSets() {
  App._patAuto = new Set();
  App._songAuto = new Set();
  const a = App.doc.automation || {};
  for (const k in (a.pattern || {})) {
    const [slot, , param] = k.split(":");
    App._patAuto.add(slot + ":" + param);
  }
  for (const k in (a.song || {})) App._songAuto.add(k);
}

function bindControlPanel() {
  const play = document.getElementById("btn-play");
  const stop = document.getElementById("btn-stop");
  const rec = document.getElementById("btn-rec");
  const mode = document.getElementById("btn-mode");
  play.addEventListener("click", () => {
    ensureAudio();   // best-effort: transport must not depend on audio init
    send({ op: "transport", playing: true });
  });
  let stopCount = 0;
  stop.addEventListener("click", () => {
    const t = App.doc.transport;
    if (t.playing) {
      send({ op: "transport", playing: false, record: false });
      stopCount = 0;
    } else {
      stopCount++;
      const loop = t.loop;
      if (loop && stopCount % 2 === 1) send({ op: "transport", pos: loop[0] * 4 });
      else send({ op: "transport", pos: 0 });
    }
  });
  rec.addEventListener("click", () => {
    send({ op: "transport", record: !App.doc.transport.record });
  });
  mode.addEventListener("click", () => {
    send({ op: "transport", mode: App.doc.transport.mode === "pattern" ? "song" : "pattern" });
  });
  document.getElementById("btn-mgmt").addEventListener("click", showMachineMgmt);
  document.getElementById("btn-menu").addEventListener("click", showAppMenu);
  document.getElementById("btn-audio").addEventListener("click", ensureAudio);
}

async function ensureAudio() {
  // Single-flight and non-throwing: a failed/hung audio init (common on
  // touch devices over plain HTTP, where AudioWorklet is unavailable) must
  // never break the UI action that triggered it. Failures allow a retry
  // on the next user gesture.
  if (window.streamPlayer.enabled) {
    try {
      await window.streamPlayer.enable(App.sr);
      document.getElementById("btn-audio").style.opacity =
        window.streamPlayer.ctx.state === "running" ? 0.4 : 1;
    } catch (err) {
      console.error("Could not resume audio output", err);
      document.getElementById("btn-audio").style.opacity = 1;
    }
    return;
  }
  if (App._audioInit) return App._audioInit;
  App._audioInit = window.streamPlayer.enable(App.sr).then(() => {
    const button = document.getElementById("btn-audio");
    button.style.opacity =
      window.streamPlayer.ctx.state === "running" ? 0.4 : 1;
    window.streamPlayer.ctx.onstatechange = () => {
      button.style.opacity =
        window.streamPlayer.ctx.state === "running" ? 0.4 : 1;
    };
  }).catch((err) => {
    console.error("Could not enable audio output", err);
    document.getElementById("btn-audio").style.opacity = 1;
    App._audioInit = null;
  });
  return App._audioInit;
}

/* ---------------- machine management ---------------- */

function showMachineMgmt() {
  showModal("MACHINE MANAGEMENT", (body) => {
    const grid = el("div", "mgmt-grid", body);
    App.doc.machines.forEach((m, i) => {
      const s = el("div", "mgmt-slot" + (m ? " filled" : ""), grid);
      el("div", "slot-num", s).textContent = "SLOT " + (i + 1);
      if (m) {
        el("div", "", s).textContent = m.name;
        el("div", "slot-num", s).textContent = App.catalog.machines[m.type].name;
        const x = el("div", "mgmt-x", s); x.textContent = "remove";
        x.addEventListener("click", (e) => {
          e.stopPropagation();
          confirmBox("Remove machine", `Remove ${m.name}? All its patterns will be lost.`,
            () => send({ op: "remove_machine", slot: i }));
        });
        const r = el("div", "mgmt-x", s); r.textContent = "replace";
        r.style.color = "#7db4e8";
        r.addEventListener("click", (e) => {
          e.stopPropagation();
          pickMachineType((mtype) => send({ op: "replace_machine", slot: i, mtype }));
        });
        s.addEventListener("click", () => { closeModal(); setView({ kind: "machine", slot: i }); });
      } else {
        el("div", "", s).textContent = "+ add";
        s.addEventListener("click", () => {
          pickMachineType((mtype) => {
            send({ op: "add_machine", slot: i, mtype });
            setTimeout(() => setView({ kind: "machine", slot: i }), 150);
          });
        });
      }
    });
  });
}

function pickMachineType(onPick) {
  showModal("SELECT MACHINE", (body) => {
    const grid = el("div", "choice-grid", body);
    App.catalog.machineOrder.forEach(mt => {
      const c = el("div", "citem", grid);
      c.textContent = App.catalog.machines[mt].name;
      c.addEventListener("click", () => { closeModal(); onPick(mt); });
    });
  });
}

/* ---------------- app menu ---------------- */

function showAppMenu() {
  let tab = "song";
  const { body } = showModal("MENU", (b) => {
    const tabs = el("div", "menu-tabs", b);
    const content = el("div", "", b);
    const tabDefs = { song: "Song", options: "Options", help: "Help" };
    const btns = {};
    for (const id in tabDefs) {
      const bt = el("button", id === tab ? "on" : "", tabs);
      bt.textContent = tabDefs[id];
      bt.addEventListener("click", () => {
        tab = id;
        Object.values(btns).forEach(x => x.classList.remove("on"));
        bt.classList.add("on");
        renderTab(content);
      });
      btns[id] = bt;
    }
    renderTab(content);

    function renderTab(c) {
      c.innerHTML = "";
      if (tab === "song") {
        let row = el("div", "menu-row", c);
        [["New", () => confirmBox("New song", "Clear the rack and all song data?",
            () => { send({ op: "new_song" }); })],
         ["Load", async () => { await showLoadSongDialog(); }],
         ["Save", () => send({ op: "save_room" })],
         ["Export WAV", () => { exportSong(false); }],
         ["Export Loop", () => { exportSong(true); }],
        ].forEach(([lab, fn]) => {
          const bt = el("button", "", row); bt.textContent = lab;
          bt.addEventListener("click", () => { closeModal(); fn(); });
        });
        row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Song name";
        const nm = el("button", "", row); nm.textContent = App.doc.name;
        nm.addEventListener("click", () => promptText("Song name", App.doc.name,
          (v) => send({ op: "set_song_prop", prop: "name", value: v })));
        row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Tempo";
        const bpmc = el("div", "bpm-ctl", row);
        const minus = el("button", "", bpmc); minus.textContent = "−";
        const lcd = el("div", "bpm-lcd", bpmc); lcd.textContent = App.doc.bpm + " BPM";
        const plus = el("button", "", bpmc); plus.textContent = "+";
        const setBpm = (v) => {
          v = Math.max(40, Math.min(250, v));
          send({ op: "set_song_prop", prop: "bpm", value: v });
          App.doc.bpm = v; lcd.textContent = v + " BPM";
        };
        minus.addEventListener("click", () => setBpm(App.doc.bpm - 1));
        plus.addEventListener("click", () => setBpm(App.doc.bpm + 1));
        let taps = [];
        lcd.addEventListener("click", () => {   // tap tempo
          const now = performance.now();
          taps = taps.filter(t => now - t < 3000); taps.push(now);
          if (taps.length >= 2) {
            const iv = (taps[taps.length - 1] - taps[0]) / (taps.length - 1);
            setBpm(Math.round(60000 / iv));
          }
        });
        row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Shuffle mode";
        const m8 = el("button", App.doc.shuffle_mode === 0 ? "on" : "", row);
        m8.textContent = "8th (March)";
        const m16 = el("button", App.doc.shuffle_mode === 1 ? "on" : "", row);
        m16.textContent = "16th (Swing)";
        m8.addEventListener("click", () => { send({ op: "set_song_prop", prop: "shuffle_mode", value: 0 }); m8.classList.add("on"); m16.classList.remove("on"); });
        m16.addEventListener("click", () => { send({ op: "set_song_prop", prop: "shuffle_mode", value: 1 }); m16.classList.add("on"); m8.classList.remove("on"); });
        row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Shuffle amount";
        row.appendChild(makeKnob({ label: "Shuffle", min: 0, max: 1, default: 0 },
          App.doc.shuffle, (v) => send({ op: "set_song_prop", prop: "shuffle", value: v })));
        row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Room";
        const rm = el("button", "", row); rm.textContent = App.room;
        rm.addEventListener("click", () => promptText("Switch room", App.room, (v) => {
          location.search = "?room=" + encodeURIComponent(v || "default");
        }));
      } else if (tab === "options") {
        const row = el("div", "menu-row", c);
        el("label", "", row).textContent = "Audio stream";
        const bt = el("button", "", row); bt.textContent = "Enable audio output";
        bt.addEventListener("click", ensureAudio);
        const cfg = App.doc.audio || {
          sample_rate: App.sr,
          block_size: App.block,
        };
        const updateAudioCfg = (prop, value) => {
          send({ op: "set_audio_config", prop, value });
          syncAudioConfig({
            sample_rate: prop === "sample_rate" ? value : (App.doc.audio?.sample_rate || App.sr),
            block_size: prop === "block_size" ? value : (App.doc.audio?.block_size || App.block),
          });
          updateLatency();
          if (window.streamPlayer.enabled) ensureAudio();
        };
        const addDiscreteSlider = (labelText, values, currentValue, onCommit, fmt) => {
          const sliderRow = el("div", "menu-row", c);
          el("label", "", sliderRow).textContent = labelText;
          const wrap = el("div", "menu-range-wrap", sliderRow);
          const input = el("input", "", wrap);
          input.type = "range";
          input.min = "0";
          input.max = String(values.length - 1);
          input.step = "1";
          const valueLcd = el("div", "menu-range-value", wrap);
          const setIndex = (idx) => {
            input.value = String(idx);
            valueLcd.textContent = fmt(values[idx]);
          };
          setIndex(closestOptionIndex(values, currentValue));
          input.addEventListener("input", () => setIndex(Number(input.value)));
          input.addEventListener("change", () => onCommit(values[Number(input.value)]));
          return { setIndex };
        };
        const latencyRow = el("div", "menu-row", c);
        el("label", "", latencyRow).textContent = "Latency est.";
        const latency = el("div", "menu-latency", latencyRow);
        const updateLatency = () => {
          const sr = App.doc.audio?.sample_rate || App.sr;
          const block = App.doc.audio?.block_size || App.block;
          latency.textContent = `${estimateLatencyMs(sr, block).toFixed(1)} ms (${block} / ${sr})`;
        };
        addDiscreteSlider("Sample rate", AUDIO_SAMPLE_RATES, cfg.sample_rate,
          (v) => updateAudioCfg("sample_rate", v), (v) => `${v} Hz`);
        addDiscreteSlider("Block size", AUDIO_BLOCK_SIZES, cfg.block_size,
          (v) => updateAudioCfg("block_size", v), (v) => `${v} frames`);
        updateLatency();
        const row2 = el("div", "menu-row", c);
        el("label", "", row2).textContent = "Upload sample";
        const up = el("button", "", row2); up.textContent = "Choose audio file…";
        up.addEventListener("click", () => { closeModal(); pickAndUploadSample(); });
        const row3 = el("div", "menu-row", c);
        el("label", "", row3).textContent = "Record sample";
        const rec = el("button", "", row3); rec.textContent = "🎤 Record from mic…";
        rec.addEventListener("click", () => { closeModal(); recordSampleModal(); });
      } else {
        c.innerHTML = "<div style='padding:10px;line-height:1.7;font-size:13px'>" +
          "<b>Refrag</b> — collaborative web reimplementation of the Caustic rack.<br>" +
          "Share this URL (with ?room=…) to jam with others.<br>" +
          "All synthesis runs on the server; audio is streamed to every client.<br>" +
          "See <code>doc/user-guide.md</code> for the full manual.</div>";
      }
    }
  }, []);
}

async function showLoadSongDialog() {
  let songs = [];
  try {
    const res = await fetch(`/api/songs?room=${encodeURIComponent(App.room)}`);
    const data = await res.json();
    songs = Array.isArray(data.songs) ? data.songs : [];
  } catch (e) {
    songs = [];
  }
  showModal("LOAD SONG", (body) => {
    const list = el("div", "file-list", body);
    if (!songs.length) {
      const empty = el("div", "", list);
      empty.textContent = "No saved songs found yet.";
      return;
    }
    songs.forEach((song) => {
      const item = el("div", "fitem", list);
      item.textContent = song;
      item.addEventListener("click", () => {
        closeModal();
        confirmBox("Load song", `Load "${song}" into the current room? Unsaved changes will be replaced.`,
          () => send({ op: "load_room", name: song }));
      });
    });
  });
}

function exportSong(loopOnly) {
  const url = `/api/export?room=${encodeURIComponent(App.room)}${loopOnly ? "&loop=1" : ""}`;
  const a = document.createElement("a");
  a.href = url; a.download = "";
  a.click();
}

/* ---------------- sample upload / recording (phone friendly) ------------- */

/* Encode a mono Float32Array as a 16-bit PCM WAV blob. */
function encodeWav(mono, sampleRate) {
  const n = mono.length;
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const wstr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  wstr(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); wstr(8, "WAVE");
  wstr(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); v.setUint16(32, 2, true);
  v.setUint16(34, 16, true); wstr(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, mono[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 32768 : s * 32767, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/* decodeAudioData with old callback-API fallback (older iOS Safari). */
function decodeAudio(ctx, arrayBuffer) {
  return new Promise((resolve, reject) => {
    const p = ctx.decodeAudioData(arrayBuffer, resolve, reject);
    if (p && p.then) p.then(resolve, reject);
  });
}

/* Convert any browser-decodable audio (m4a/mp3/ogg/webm/wav…) to a
   mono 16-bit WAV blob. */
async function audioDataToWavBlob(arrayBuffer, isWav) {
  if (isWav) return new Blob([arrayBuffer], { type: "audio/wav" });
  const ctx = new OfflineAudioContext(1, 1, 44100);
  const decoded = await decodeAudio(ctx, arrayBuffer);
  const n = decoded.length;
  const mono = new Float32Array(n);
  const nch = decoded.numberOfChannels || 1;
  for (let c = 0; c < nch; c++) {
    const d = decoded.getChannelData(c);
    for (let i = 0; i < n; i++) mono[i] += d[i] / nch;
  }
  return encodeWav(mono, decoded.sampleRate);
}

async function uploadWavBlob(blob, name) {
  const fd = new FormData();
  fd.append("name", name);
  fd.append("file", blob, name + ".wav");
  const r = await fetch("/api/samples", { method: "POST", body: fd });
  const res = await r.json();
  if (!r.ok) throw new Error(res.error || "upload failed");
  await loadSampleLib();
  return res.name;
}

/* File-picker upload. Accepts any audio the browser can decode and
   converts it to WAV before uploading. onDone(name) is optional. */
function pickAndUploadSample(onDone) {
  const inp = document.createElement("input");
  inp.type = "file";
  inp.accept = "audio/*,.wav,.mp3,.m4a,.aac,.ogg,.webm,.flac";
  inp.addEventListener("change", async () => {
    if (!inp.files.length) return;
    const file = inp.files[0];
    const base = (file.name || "sample").replace(/\.[^.]*$/, "")
      .replace(/[^A-Za-z0-9 _\-]/g, "").slice(0, 40) || "sample";
    try {
      const isWav = /\.wav$/i.test(file.name || "") ||
        (file.type || "").includes("wav");
      const blob = await audioDataToWavBlob(await file.arrayBuffer(), isWav);
      const name = await uploadWavBlob(blob, base);
      if (onDone) onDone(name);
      else showModal("SAMPLE UPLOADED", (b) => {
        el("div", "", b).textContent =
          `"${name}" is now available in the PCMSynth, BeatBox and Vocoder sample lists.`;
      });
    } catch (e) {
      showModal("UPLOAD FAILED", (b) => {
        el("div", "", b).textContent =
          "Could not decode this file (" + e.message + "). Try a WAV, MP3 or M4A file.";
      });
    }
  });
  inp.click();
}

/* Record a sample from the microphone (needs HTTPS or localhost).
   Captures raw PCM through the audio graph — no codecs involved, so it
   works the same on desktop and mobile browsers. */
function recordSampleModal(onDone) {
  let ctx = null, stream = null, node = null, src = null, timer = null, t0 = 0;
  let recording = false;
  const buffers = [];
  const stopAll = () => {
    if (timer) clearInterval(timer);
    recording = false;
    if (node) try { node.disconnect(); } catch (e) {}
    if (src) try { src.disconnect(); } catch (e) {}
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (ctx) try { ctx.close(); } catch (e) {}
  };
  showModal("RECORD SAMPLE", (b) => {
    const status = el("div", "menu-row", b);
    status.textContent = "Tap Record to capture audio from your microphone.";
    const timeLcd = el("div", "bpm-lcd", b);
    timeLcd.style.textAlign = "center";
    timeLcd.textContent = "0.0 s";
    const row = el("div", "menu-row", b);
    row.style.justifyContent = "center";
    const btn = el("button", "primary", row);
    btn.textContent = "● Record";
    btn.style.padding = "10px 24px";

    const finish = () => {
      clearInterval(timer);
      recording = false;
      const rate = ctx.sampleRate;
      stopAll();
      let total = 0;
      buffers.forEach(x => total += x.length);
      if (total < 1000) {
        status.textContent = "Recording too short — try again.";
        return;
      }
      const mono = new Float32Array(total);
      let off = 0;
      buffers.forEach(x => { mono.set(x, off); off += x.length; });
      const blob = encodeWav(mono, rate);
      closeModal();
      promptText("Sample name", "recording", async (nm) => {
        try {
          const name = await uploadWavBlob(blob, (nm || "recording").slice(0, 40));
          if (onDone) onDone(name);
        } catch (e) {
          showModal("UPLOAD FAILED", (bb) => {
            el("div", "", bb).textContent = e.message;
          });
        }
      });
    };

    btn.addEventListener("click", async () => {
      if (recording) { finish(); return; }
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          throw new Error("microphone needs HTTPS (or localhost)");
        }
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (e) {
        status.textContent = "Microphone unavailable: " + (e.message || e.name) +
          ". Use “Upload file” instead.";
        return;
      }
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      await ctx.resume();
      src = ctx.createMediaStreamSource(stream);
      node = ctx.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (ev) => {
        if (recording) buffers.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
      };
      src.connect(node);
      node.connect(ctx.destination);   // required by some browsers to run
      buffers.length = 0;
      recording = true;
      t0 = performance.now();
      timer = setInterval(() => {
        timeLcd.textContent = ((performance.now() - t0) / 1000).toFixed(1) + " s";
        if (performance.now() - t0 > 30000) finish();   // 30 s cap
      }, 100);
      btn.textContent = "■ Stop";
      status.textContent = "Recording… tap Stop when done (max 30 s).";
    });
  }, [{ label: "Cancel", onClick: () => { stopAll(); } }]);
}

/* Sample picker used by PCMSynth, BeatBox and Vocoder: always shows a
   fresh list from the server plus Upload / Record entries. */
async function pickSample(title, onPick) {
  await loadSampleLib();
  showModal(title, (body) => {
    const actions = el("div", "menu-row", body);
    const up = el("button", "", actions);
    up.textContent = "⬆ Upload file…";
    up.addEventListener("click", () => {
      closeModal();
      pickAndUploadSample((name) => onPick(name));
    });
    const rec = el("button", "", actions);
    rec.textContent = "🎤 Record…";
    rec.addEventListener("click", () => {
      closeModal();
      recordSampleModal((name) => onPick(name));
    });
    const list = el("div", "file-list", body);
    const addItems = (names, cls) => names.forEach(n => {
      const f = el("div", "fitem", list);
      f.textContent = (cls === "user" ? "★ " : "") + n;
      f.addEventListener("click", () => { closeModal(); onPick(n); });
    });
    addItems(App.sampleLib.user, "user");
    addItems(App.sampleLib.factory, "factory");
  });
}

async function loadSampleLib() {
  const r = await fetch("/api/samples");
  App.sampleLib = await r.json();
}

/* ---------------- notes ---------------- */

function sendNote(slot, note, on, vel = 1.0) {
  ensureAudio();
  send({ op: "note", slot, note, on, vel });
}

function flashRemoteNote(slot, note, on) {
  if (App.view.kind === "machine" && App.view.slot === slot && window._kbdFlash) {
    window._kbdFlash(note, on);
  }
}

/* ---------------- helpers used by panel builders ---------------- */

function paramWidget(slot, m, pid, opts = {}) {
  const spec = App.catalog.machines[m.type].controls[pid];
  const send_ = (v) => {
    m.params[pid] = v;
    send({ op: "set_param", slot, param: pid, value: v });
  };
  let w;
  if (spec.type === "knob") w = makeKnob(spec, m.params[pid], send_, opts);
  else if (spec.type === "slider") w = makeSlider(spec, m.params[pid], send_, opts);
  else if (spec.type === "select") w = makeSelector(spec, m.params[pid], send_);
  else w = makeToggle(spec, m.params[pid], send_);
  w._autoKey = slot + ":" + pid;
  w.dataset.autokey = slot + ":" + pid;
  if (spec.type === "knob" || spec.type === "slider") {
    w.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      offerClearAutomation(slot, m, pid);
    });
  }
  return w;
}

function offerClearAutomation(slot, m, pid) {
  const patKey = `${slot}:${"ABCD"[m.bank]}${m.pattern + 1}:${pid}`;
  const songKey = `${slot}:${pid}`;
  const hasPat = App.doc.automation.pattern[patKey];
  const hasSong = App.doc.automation.song[songKey];
  if (!hasPat && !hasSong) return;
  confirmBox("Clear automation", "Remove recorded automation for this control?", () => {
    if (hasPat) send({ op: "clear_automation", scope: "pattern", key: patKey });
    if (hasSong) send({ op: "clear_automation", scope: "song", key: songKey });
  });
}

/* ---------------- boot ---------------- */

async function boot() {
  const r = await fetch("/api/catalog");
  App.catalog = await r.json();
  await loadSampleLib();
  bindControlPanel();
  connectWS();
  const origRender = renderAll;
  window.renderAll = function () { computeAutoSets(); origRender(); };
}

boot();
