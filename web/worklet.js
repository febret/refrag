/* AudioWorklet ring-buffer player for the Refrag PCM stream. */

class RefragPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.capacity = sampleRate * 2;
    this.left = new Float32Array(this.capacity);
    this.right = new Float32Array(this.capacity);
    this.readPos = 0;
    this.writePos = 0;
    this.started = false;
    this.minBuffer = Math.floor(sampleRate * 0.12);   // 120ms jitter buffer
    this.targetBuffer = Math.floor(sampleRate * 0.18);
    this.maxBuffer = Math.floor(sampleRate * 0.45);
    this.underruns = 0;
    this.drops = 0;
    this.reportAt = 0;
    this.port.onmessage = (e) => {
      const { left, right } = e.data;
      const n = left.length;
      if (this.buffered() + n > this.maxBuffer) {
        const dropped = this.buffered() + n - this.targetBuffer;
        this.readPos = (this.readPos + dropped) % this.capacity;
        this.drops += dropped;
      }
      for (let i = 0; i < n; i++) {
        const writePos = (this.writePos + i) % this.capacity;
        this.left[writePos] = left[i];
        this.right[writePos] = right[i];
      }
      this.writePos = (this.writePos + n) % this.capacity;
    };
  }

  buffered() {
    let samples = this.writePos - this.readPos;
    if (samples < 0) samples += this.capacity;
    return samples;
  }

  process(inputs, outputs) {
    const out = outputs[0];
    const l = out[0], r = out[1] || out[0];
    const n = l.length;
    const avail = this.buffered();
    if (!this.started) {
      if (avail < this.minBuffer) { l.fill(0); r.fill(0); return true; }
      this.started = true;
    }
    if (avail < n) {
      l.fill(0); r.fill(0);
      this.underruns++;
      this.started = false;      // underrun: rebuild jitter buffer
      return true;
    }
    for (let i = 0; i < n; i++) {
      const readPos = (this.readPos + i) % this.capacity;
      l[i] = this.left[readPos];
      r[i] = this.right[readPos];
    }
    this.readPos = (this.readPos + n) % this.capacity;
    this.reportAt += n;
    if (this.reportAt >= sampleRate) {
      this.reportAt -= sampleRate;
      this.port.postMessage({
        type: "stats",
        buffered: this.buffered(),
        underruns: this.underruns,
        drops: this.drops,
      });
    }
    return true;
  }
}

registerProcessor("refrag-player", RefragPlayer);
