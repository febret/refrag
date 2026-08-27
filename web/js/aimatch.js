/* AI Match: record or upload a short clip and fill the current pattern
   with notes that match it.  Audio is always converted to mono 16-bit WAV
   in the browser (decodeAudioData handles mp3/ogg/etc.), so the server
   only ever parses WAV. */
"use strict";

const AIMATCH_MAX_SECONDS = 15;

function aiMatchDialog(slot, m) {
  const st = { audio: null, sr: 0, ctx: null, rec: null, preview: null, busy: false };

  function ctx() {
    if (!st.ctx) st.ctx = new (window.AudioContext || window.webkitAudioContext)();
    return st.ctx;
  }

  function cleanup() {
    if (st.rec) stopRecording();
    if (st.preview) { try { st.preview.stop(); } catch (e) {} st.preview = null; }
    if (st.ctx) { st.ctx.close(); st.ctx = null; }
  }

  let statusEl, recBtn, prevBtn;
  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "ai-status" + (cls ? " " + cls : "");
  }
  function haveClip() {
    prevBtn.disabled = !st.audio;
  }

  /* -- recording ---------------------------------------------------- */

  async function startRecording() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setStatus("Microphone unavailable: " + e.message, "err");
      return;
    }
    const ac = ctx();
    if (ac.state === "suspended") await ac.resume();
    const src = ac.createMediaStreamSource(stream);
    const proc = ac.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let frames = 0;
    proc.onaudioprocess = (e) => {
      const d = e.inputBuffer.getChannelData(0);
      chunks.push(new Float32Array(d));
      frames += d.length;
      const secs = frames / ac.sampleRate;
      setStatus("Recording… " + secs.toFixed(1) + "s (click STOP to finish)", "rec");
      if (secs >= AIMATCH_MAX_SECONDS) stopRecording();
    };
    src.connect(proc);
    proc.connect(ac.destination);   // required by some browsers to run the node
    st.rec = { stream, src, proc, chunks };
    recBtn.textContent = "◼ STOP";
    setStatus("Recording…", "rec");
  }

  function stopRecording() {
    const r = st.rec;
    if (!r) return;
    st.rec = null;
    r.proc.disconnect(); r.src.disconnect();
    r.stream.getTracks().forEach(t => t.stop());
    const n = r.chunks.reduce((a, c) => a + c.length, 0);
    const audio = new Float32Array(n);
    let off = 0;
    for (const c of r.chunks) { audio.set(c, off); off += c.length; }
    recBtn.textContent = "● RECORD";
    if (n < st.ctx.sampleRate * 0.2) {
      setStatus("Recording too short — try again.", "err");
      return;
    }
    st.audio = audio;
    st.sr = st.ctx.sampleRate;
    setStatus("Recorded " + (n / st.sr).toFixed(1) + "s clip — ready to match.", "ok");
    haveClip();
  }

  /* -- file upload ---------------------------------------------------- */

  async function loadFile(file) {
    try {
      const buf = await file.arrayBuffer();
      const decoded = await ctx().decodeAudioData(buf);
      const n = Math.min(decoded.length, AIMATCH_MAX_SECONDS * 2 * decoded.sampleRate);
      const mono = new Float32Array(n);
      for (let c = 0; c < decoded.numberOfChannels; c++) {
        const d = decoded.getChannelData(c);
        for (let i = 0; i < n; i++) mono[i] += d[i] / decoded.numberOfChannels;
      }
      st.audio = mono;
      st.sr = decoded.sampleRate;
      setStatus("Loaded " + file.name + " (" + (n / st.sr).toFixed(1) + "s) — ready to match.", "ok");
      haveClip();
    } catch (e) {
      setStatus("Could not decode that file: " + e.message, "err");
    }
  }

  /* -- preview / upload ---------------------------------------------------- */

  function preview() {
    if (!st.audio) return;
    if (st.preview) { try { st.preview.stop(); } catch (e) {} }
    const ac = ctx();
    const buf = ac.createBuffer(1, st.audio.length, st.sr);
    buf.copyToChannel(st.audio, 0);
    const src = ac.createBufferSource();
    src.buffer = buf;
    src.connect(ac.destination);
    src.start();
    st.preview = src;
  }

  async function upload() {
    if (!st.audio || st.busy) return;
    st.busy = true;
    setStatus("Matching… this overwrites pattern " + patKey(m) + ".", "rec");
    const fd = new FormData();
    fd.append("file", encodeWav(st.audio, st.sr), "aimatch.wav");
    try {
      const q = "room=" + encodeURIComponent(App.room) + "&slot=" + slot;
      const resp = await fetch("/api/aimatch?" + q, { method: "POST", body: fd });
      const out = await resp.json();
      if (!resp.ok) {
        setStatus(out.error || "AI Match failed.", "err");
        st.busy = false;
        return;
      }
      cleanup();
      closeModal();
    } catch (e) {
      setStatus("AI Match failed: " + e.message, "err");
      st.busy = false;
    }
  }

  /* -- modal ---------------------------------------------------- */

  showModal("AI MATCH — " + m.name, (b) => {
    const info = el("div", "fl-info", b);
    info.textContent =
      "Record or upload a short sound clip (up to " + AIMATCH_MAX_SECONDS +
      "s recorded). AI Match fills the pattern with the notes and chords it " +
      "hears, replacing everything in pattern " + patKey(m) +
      " and possibly changing its measure count. The instrument itself is untouched.";
    const row = el("div", "ai-row", b);
    recBtn = el("button", "", row);
    recBtn.textContent = "● RECORD";
    recBtn.addEventListener("click", () => st.rec ? stopRecording() : startRecording());
    const fileBtn = el("button", "", row);
    fileBtn.textContent = "📁 FILE…";
    const fileInp = el("input", "", row);
    fileInp.type = "file"; fileInp.accept = "audio/*"; fileInp.style.display = "none";
    fileBtn.addEventListener("click", () => fileInp.click());
    fileInp.addEventListener("change", () => {
      if (fileInp.files[0]) loadFile(fileInp.files[0]);
    });
    prevBtn = el("button", "", row);
    prevBtn.textContent = "▶ PREVIEW";
    prevBtn.disabled = true;
    prevBtn.addEventListener("click", preview);
    statusEl = el("div", "ai-status", b);
    statusEl.textContent = "No clip yet.";
  }, [
    { label: "Cancel", onClick: () => { cleanup(); } },
    { label: "MATCH", primary: true, onClick: () => { upload(); return false; } },
  ]);
}

/* Encode mono Float32 samples as a 16-bit PCM WAV Blob. */
function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const wstr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  wstr(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  wstr(8, "WAVE");
  wstr(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);          // PCM
  v.setUint16(22, 1, true);          // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  wstr(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}
