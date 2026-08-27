/* Streaming PCM player: receives Int16 stereo frames over WebSocket and
   uses an AudioWorklet when available, with an AudioBuffer fallback for
   browsers that do not expose worklets on insecure LAN connections. */
"use strict";

class StreamPlayer {
  constructor() {
    this.ctx = null;
    this.node = null;
    this.enabled = false;
    this.pending = [];
    this.stats = { buffered: 0, underruns: 0, drops: 0 };
    this.backend = null;
    this.serverRate = 44100;
    this.nextStartTime = 0;
    this.sources = new Set();
  }

  async enable(serverRate) {
    if (this.enabled) {
      if (serverRate && serverRate !== this.serverRate) {
        await this.disable();
      } else {
        if (this.ctx.state === "suspended") await this.ctx.resume();
        return;
      }
    }
    this.serverRate = serverRate;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio is not supported");
    try {
      try {
        this.ctx = new AudioContextClass({ sampleRate: serverRate });
      } catch (err) {
        this.ctx = new AudioContextClass();
      }

      // Invoke resume and a silent source before the first await so mobile
      // browsers still consider this part of the user's click gesture.
      const silent = this.ctx.createBufferSource();
      silent.buffer = this.ctx.createBuffer(1, 1, this.ctx.sampleRate);
      silent.connect(this.ctx.destination);
      silent.start();
      const resume = this.ctx.state === "suspended"
        ? this.ctx.resume().catch((err) => {
          console.warn("Audio output still needs a user gesture", err);
        })
        : Promise.resolve();

      const canUseWorklet = this.ctx.audioWorklet &&
        typeof window.AudioWorkletNode === "function" &&
        this.ctx.sampleRate === serverRate;
      if (canUseWorklet) {
        try {
          await Promise.all([
            resume,
            this.ctx.audioWorklet.addModule("/web/worklet.js?v=3"),
          ]);
          this.node = new AudioWorkletNode(this.ctx, "refrag-player",
            { outputChannelCount: [2] });
          this.node.port.onmessage = (e) => {
            if (e.data && e.data.type === "stats") this.stats = e.data;
          };
          this.backend = "worklet";
        } catch (err) {
          console.warn("AudioWorklet unavailable; using buffered audio", err);
          await resume;
          this._setupBufferBackend();
        }
      } else {
        await resume;
        this._setupBufferBackend();
      }
      if (!this.node) throw new Error("Could not create an audio output");
      this.node.connect(this.ctx.destination);
      this.enabled = true;
      for (const buf of this.pending) this.push(buf);
      this.pending = [];
    } catch (err) {
      await this.disable();
      throw err;
    }
  }

  async disable() {
    this.enabled = false;
    this.nextStartTime = 0;
    for (const source of this.sources) {
      try { source.stop(); } catch (e) {}
      try { source.disconnect(); } catch (e) {}
    }
    this.sources.clear();
    if (this.node) {
      try { this.node.disconnect(); } catch (e) {}
    }
    const ctx = this.ctx;
    this.ctx = null;
    this.node = null;
    this.backend = null;
    if (ctx && ctx.state !== "closed") {
      if (ctx.state === "suspended") await ctx.resume();
      try {
        await ctx.close();
      } catch (closeError) {
        console.error("Could not close failed audio context", closeError);
      }
    }
  }

  _setupBufferBackend() {
    this.node = this.ctx.createGain();
    this.backend = "buffer";
    this.nextStartTime = 0;
  }

  push(arrayBuffer) {
    if (!this.enabled) {
      // keep a small backlog so audio starts promptly after enabling
      this.pending.push(arrayBuffer);
      if (this.pending.length > 8) this.pending.shift();
      return;
    }
    const int16 = new Int16Array(arrayBuffer);
    const n = int16.length / 2;
    if (this.backend === "buffer") {
      this._pushBuffer(int16, n);
      return;
    }
    const left = new Float32Array(n);
    const right = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      left[i] = int16[2 * i] / 32768;
      right[i] = int16[2 * i + 1] / 32768;
    }
    this.node.port.postMessage({ left, right }, [left.buffer, right.buffer]);
  }

  _pushBuffer(int16, n) {
    const now = this.ctx.currentTime;
    if (this.nextStartTime < now + 0.04) {
      if (this.nextStartTime > 0) this.stats.underruns++;
      this.nextStartTime = now + 0.12;
    }
    if (this.nextStartTime > now + 0.5) {
      this.stats.drops += n;
      return;
    }

    const buffer = this.ctx.createBuffer(2, n, this.serverRate);
    const left = buffer.getChannelData(0);
    const right = buffer.getChannelData(1);
    for (let i = 0; i < n; i++) {
      left[i] = int16[2 * i] / 32768;
      right[i] = int16[2 * i + 1] / 32768;
    }
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.node);
    this.sources.add(source);
    source.onended = () => {
      source.disconnect();
      this.sources.delete(source);
    };
    source.start(this.nextStartTime);
    this.nextStartTime += n / this.serverRate;
    this.stats.buffered = Math.round(
      Math.max(0, this.nextStartTime - now) * this.serverRate);
  }
}

window.streamPlayer = new StreamPlayer();
