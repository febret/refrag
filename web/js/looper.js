/* Live performance looper and its tactile XY controls. */
"use strict";

const LOOPER_BANKS = ["A", "B", "C", "D"];
const LOOPER_HUES = [194, 102, 28, 278, 168, 344, 52, 218, 128, 12, 302, 180, 76, 242];

function looperPatternKey(bank, pattern) {
  return LOOPER_BANKS[bank] + (pattern + 1);
}

function looperActive(slot, m) {
  const live = App.status.looper?.[String(slot)];
  const queue = Array.isArray(live?.queue) ? live.queue :
    (live?.queued_bank !== undefined ?
      [{ bank: live.queued_bank, pattern: live.queued_pattern }] : []);
  return {
    bank: live?.bank ?? m.bank,
    pattern: live?.pattern ?? m.pattern,
    queue,
    mode: live?.mode ?? m.looper_mode ?? "queue",
    looperBank: live?.looper_bank ?? m.looper_bank ?? m.bank,
    transposeStep: live?.transpose_step ?? 0,
    progress: live?.progress ?? 0,
  };
}

function formatTransposeLabel(value) {
  return (value > 0 ? "+" : "") + value + " ST";
}

function ensureTransposeSteps(m) {
  const legacy = Math.max(-24, Math.min(24, Number.isFinite(m.transpose) ? m.transpose : 0));
  let steps = Array.isArray(m.transpose_steps) ? m.transpose_steps.slice(0, 4) : [];
  steps = steps.map(step => ({
    transpose: Math.max(-24, Math.min(24, Number(step?.transpose ?? legacy))),
    loops: Math.max(1, Math.min(4, Number(step?.loops ?? 1))),
  }));
  while (steps.length < 4) steps.push({ transpose: legacy, loops: 1 });
  m.transpose_steps = steps;
  m.transpose = steps[0].transpose;
  return steps;
}

function formatLooperValue(kind, value) {
  if (kind === "pan") {
    if (Math.abs(value) < 0.01) return "C";
    return (value < 0 ? "L " : "R ") + Math.round(Math.abs(value) * 100);
  }
  if (kind.startsWith("eq_")) {
    const n = Math.round(value * 12);
    return (n > 0 ? "+" : "") + n + " dB";
  }
  return Math.round(value * 100) + "%";
}

function makeLooperXYPad(parent, slot, m, options) {
  const root = el("div", "looper-xy", parent);
  const title = el("div", "looper-xy-title", root);
  el("span", "", title).textContent = options.title;
  const reset = el("button", "looper-mini-reset", title);
  reset.type = "button";
  reset.textContent = "RST";
  reset.title = "Reset both axes";

  const surface = el("div", "looper-xy-surface", root);
  surface.setAttribute("role", "group");
  surface.setAttribute("aria-label", options.title + " XY control");
  el("div", "looper-xy-grid", surface);
  const thumb = el("div", "looper-xy-thumb", surface);
  const readout = el("div", "looper-xy-readout", root);
  const xRead = el("span", "", readout);
  const yRead = el("span", "", readout);
  const xSpec = App.catalog.mixerStrip[options.x];
  const ySpec = App.catalog.mixerStrip[options.y];
  let x = m.mixer[options.x];
  let y = m.mixer[options.y];
  let dragging = false;

  function fraction(value, spec) {
    return (value - spec.min) / (spec.max - spec.min || 1);
  }

  function draw() {
    thumb.style.left = (fraction(x, xSpec) * 100) + "%";
    thumb.style.top = ((1 - fraction(y, ySpec)) * 100) + "%";
    xRead.textContent = "X " + xSpec.label.toUpperCase() + " " +
      formatLooperValue(options.x, x);
    yRead.textContent = "Y " + ySpec.label.toUpperCase() + " " +
      formatLooperValue(options.y, y);
  }

  function setAxis(param, value) {
    if (param === options.x) x = value;
    else if (param === options.y) y = value;
    else return;
    m.mixer[param] = value;
    draw();
  }

  function sendAxis(param, value) {
    setAxis(param, value);
    send({ op: "set_mixer", slot, param, value });
  }

  function applyPointer(e) {
    const r = surface.getBoundingClientRect();
    const xf = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const yf = Math.min(1, Math.max(0, 1 - (e.clientY - r.top) / r.height));
    const nx = xSpec.min + xf * (xSpec.max - xSpec.min);
    const ny = ySpec.min + yf * (ySpec.max - ySpec.min);
    if (Math.abs(nx - x) > 0.0001) sendAxis(options.x, nx);
    if (Math.abs(ny - y) > 0.0001) sendAxis(options.y, ny);
  }

  surface.addEventListener("pointerdown", (e) => {
    dragging = true;
    try { surface.setPointerCapture(e.pointerId); } catch { /* synthetic pointer */ }
    root.classList.add("dragging");
    applyPointer(e);
    e.preventDefault();
  });
  surface.addEventListener("pointermove", (e) => {
    if (dragging) applyPointer(e);
  });
  surface.addEventListener("pointerup", () => {
    dragging = false;
    root.classList.remove("dragging");
  });
  surface.addEventListener("pointercancel", () => {
    dragging = false;
    root.classList.remove("dragging");
  });
  reset.addEventListener("click", () => {
    sendAxis(options.x, xSpec.default);
    sendAxis(options.y, ySpec.default);
  });

  root._sync = setAxis;
  draw();
  return root;
}

function makeLooperSwitch(parent, label, className, active, onClick, disabled) {
  const button = el("button", "looper-switch " + className + (active ? " on" : ""), parent);
  button.type = "button";
  button.disabled = !!disabled;
  const lamp = el("span", "looper-switch-lamp", button);
  lamp.setAttribute("aria-hidden", "true");
  el("span", "looper-switch-label", button).textContent = label;
  if (onClick) button.addEventListener("click", onClick);
  return button;
}

function renderLooper(mv) {
  const shell = el("div", "looper-shell", mv);
  const sizer = el("div", "looper-sizer", shell);
  const deck = el("div", "looper-deck", sizer);
  const top = el("div", "looper-top", deck);
  const brand = el("div", "looper-brand", top);
  el("div", "looper-brand-mark", brand).textContent = "REFRAG";
  el("div", "looper-brand-name", brand).textContent = "LIVE PERFORMANCE LOOPER";
  const display = el("div", "looper-master-display", top);
  el("span", "looper-display-kicker", display).textContent = "QUANTIZED LAUNCH";
  el("strong", "", display).textContent = App.doc.transport.playing ?
    (App.doc.transport.mode === "pattern" ? "PERFORMANCE ACTIVE" : "SONG ARMED") :
    "STANDBY";
  const legend = el("div", "looper-legend", top);
  legend.innerHTML =
    "<span><i class='live'></i>LIVE</span><span><i class='queued'></i>QUEUED</span>" +
    "<span><i class='filled'></i>HAS NOTES</span>";

  const state = App._looperState = App._looperState || { banks: {}, transposeCollapsed: {} };
  const machines = App.doc.machines
    .map((m, slot) => ({ m, slot })).filter(({ m }) => m);
  if (!machines.length) {
    const empty = el("div", "looper-empty", deck);
    empty.textContent = "NO MACHINES INSTALLED // LOAD A MACHINE TO BUILD A PERFORMANCE SET";
    fitLooperDeck(shell, sizer, deck, 1);
    return;
  }

  const channels = el("div", "looper-channels", deck);
  machines.forEach(({ m, slot }) => {
    const hue = LOOPER_HUES[slot % LOOPER_HUES.length];
    const row = el("section", "looper-channel", channels);
    row.dataset.slot = slot;
    row.style.setProperty("--channel-hue", hue);

    const identity = el("div", "looper-identity", row);
    el("div", "looper-channel-number", identity).textContent =
      "CHANNEL " + String(slot + 1).padStart(2, "0");
    const name = el("div", "looper-machine-name", identity);
    name.textContent = m.name;
    name.title = "Double-click to open machine";
    name.addEventListener("dblclick", () => setView({ kind: "machine", slot }));
    el("div", "looper-machine-type", identity).textContent =
      App.catalog.machines[m.type].name.toUpperCase();
    const meter = el("div", "looper-meter", identity);
    for (let i = 0; i < 12; i++) el("i", "", meter);

    const bankBox = el("div", "looper-bank", row);
    el("div", "looper-section-label", bankBox).textContent = "PATTERN BANK";
    const bankControls = el("div", "looper-bank-controls", bankBox);
    const previous = el("button", "looper-bank-step", bankControls);
    previous.type = "button";
    previous.textContent = "<";
    const bankDisplay = el("div", "looper-bank-display", bankControls);
    const next = el("button", "looper-bank-step", bankControls);
    next.type = "button";
    next.textContent = ">";
    let browsedBank = state.banks[slot] ?? m.looper_bank ?? m.bank;
    state.banks[slot] = browsedBank;
    function setBank(bank) {
      const nextBank = (bank + LOOPER_BANKS.length) % LOOPER_BANKS.length;
      state.banks[slot] = nextBank;
      m.looper_bank = nextBank;
      send({ op: "looper_set_bank", slot, bank: nextBank });
      renderAll();
    }
    bankDisplay.textContent = LOOPER_BANKS[browsedBank];
    previous.title = "Previous bank";
    next.title = "Next bank";
    previous.addEventListener("click", () => setBank(browsedBank - 1));
    next.addEventListener("click", () => setBank(browsedBank + 1));

    const launchBox = el("div", "looper-launcher", row);
    const launchHead = el("div", "looper-launch-head", launchBox);
    el("span", "looper-section-label", launchHead).textContent =
      "PATTERN LAUNCH // BANK " + LOOPER_BANKS[browsedBank];
    const live = looperActive(slot, m);
    const queue = live.queue || [];
    const liveReadout = el("span", "looper-live-readout", launchHead);
    liveReadout.textContent = "LIVE " + looperPatternKey(live.bank, live.pattern);
    const queueBar = el("div", "looper-queue-bar", launchBox);
    const queueReadout = el("div", "looper-queue-readout", queueBar);
    queueReadout.textContent = queue.length ?
      ("QUEUE " + queue.map(item => looperPatternKey(item.bank, item.pattern)).join(" > ")) :
      "QUEUE EMPTY";
    const clearQueue = el("button", "looper-clear-queue", queueBar);
    clearQueue.type = "button";
    clearQueue.textContent = "CLR";
    clearQueue.title = "Cancel queued pattern launches";
    clearQueue.disabled = !queue.length;
    clearQueue.addEventListener("click", () => {
      send({ op: "looper_clear_queue", slot });
    });
    const pads = el("div", "looper-pads", launchBox);
    for (let pattern = 0; pattern < 16; pattern++) {
      const key = looperPatternKey(browsedBank, pattern);
      const pat = m.patterns[key];
      const pad = el("button", "looper-pad" +
        (pat?.notes?.length ? " filled" : " empty"), pads);
      pad.type = "button";
      pad.dataset.bank = browsedBank;
      pad.dataset.pattern = pattern;
      pad.style.setProperty("--pad-hue", (hue + pattern * 4) % 360);
      pad.setAttribute("aria-label", "Launch pattern " + key);
      el("span", "looper-pad-number", pad).textContent = pattern + 1;
      el("span", "looper-pad-glass", pad);
      pad.addEventListener("click", () => {
        // Launch must never depend on local audio init (it can hang or fail
        // on touch devices); unlocking the stream is best-effort.
        ensureAudio();
        row.querySelectorAll(".looper-pad.requested")
          .forEach(p => p.classList.remove("requested"));
        pad.classList.add("requested");
        send({ op: "looper_pattern", slot, bank: browsedBank, pattern });
      });
    }

    const performance = el("div", "looper-performance", row);
    makeLooperXYPad(performance, slot, m, {
      title: "LEVEL / PAN", x: "pan", y: "volume",
    });
    makeLooperXYPad(performance, slot, m, {
      title: "TONE", x: "eq_bass", y: "eq_high",
    });
    makeLooperXYPad(performance, slot, m, {
      title: "MASTER SENDS", x: "send_delay", y: "send_reverb",
    });

    const switches = el("div", "looper-switches", row);
    el("div", "looper-section-label", switches).textContent = "CHANNEL LOGIC";
    const switchGrid = el("div", "looper-switch-grid", switches);
    const queueMode = makeLooperSwitch(
      switchGrid, "QUEUE MODE", "mode",
      live.mode !== "random", null, false);
    queueMode.dataset.mode = "queue";
    queueMode.addEventListener("click", () => {
      if ((m.looper_mode || "queue") === "queue") return;
      m.looper_mode = "queue";
      send({ op: "looper_set_mode", slot, mode: "queue" });
      renderAll();
    });
    const randomMode = makeLooperSwitch(
      switchGrid, "RANDOM MODE", "mode random",
      live.mode === "random", null, false);
    randomMode.dataset.mode = "random";
    randomMode.addEventListener("click", () => {
      if ((m.looper_mode || "queue") === "random") return;
      m.looper_mode = "random";
      send({ op: "looper_set_mode", slot, mode: "random" });
      renderAll();
    });
    const mute = makeLooperSwitch(switchGrid, "MUTE", "danger", !!m.mute, null, false);
    mute.dataset.control = "mute";
    mute.addEventListener("click", () => {
      m.mute = m.mute ? 0 : 1;
      mute.classList.toggle("on", !!m.mute);
      send({ op: "set_mixer", slot, param: "mute", value: m.mute });
    });
    const solo = makeLooperSwitch(switchGrid, "SOLO", "warning", !!m.solo, null, false);
    solo.dataset.control = "solo";
    solo.addEventListener("click", () => {
      m.solo = m.solo ? 0 : 1;
      solo.classList.toggle("on", !!m.solo);
      send({ op: "set_mixer", slot, param: "solo", value: m.solo });
    });
    m.effects.forEach((fx, index) => {
      const fxButton = makeLooperSwitch(
        switchGrid,
        fx ? "FX" + (index + 1) + " " + fx.type.toUpperCase() : "FX" + (index + 1) + " EMPTY",
        "effect",
        !!fx && !fx.bypass,
        null,
        !fx
      );
      if (fx) {
        fxButton.dataset.effectIndex = index;
        fxButton.addEventListener("click", () => {
          fx.bypass = fx.bypass ? 0 : 1;
          fxButton.classList.toggle("on", !fx.bypass);
          send({
            op: "set_effect_param", slot, index, param: "bypass",
            value: fx.bypass,
          });
        });
      }
    });

    const activeKey = looperPatternKey(live.bank, live.pattern);
    const activePattern = m.patterns[activeKey];
    const flourish = activePattern?.flourish;
    const flourButton = makeLooperSwitch(
      switchGrid,
      flourish ? "FLOURISH" : "NO FLOURISH",
      "flourish",
      !!flourish?.on,
      null,
      !flourish
    );
    if (flourish) {
      flourButton.addEventListener("click", () => {
        flourish.on = flourish.on ? 0 : 1;
        flourButton.classList.toggle("on", !!flourish.on);
        send({
          op: "flourish_toggle", slot, key: activeKey,
          on: flourish.on,
        });
      });
    }

    const isBeatbox = m.type === "beatbox";
    const isCollapsed = isBeatbox ? true : !!(state.transposeCollapsed[slot] ?? true);
    if (isCollapsed) row.classList.add("transpose-collapsed");

    const transpose = el("div",
      "looper-transpose" + (isBeatbox ? " disabled" : ""),
      row);
    transpose.dataset.transposeSlot = slot;

    if (isBeatbox) {
      // Beatbox: static narrow strip, no toggle
      const strip = el("div", "looper-transpose-strip", transpose);
      el("span", "looper-transpose-strip-label", strip).textContent = "LIVE TRANSPOSE";
      el("div", "looper-transpose-strip-value", strip).textContent = "DRUM MAP";
    } else {
      const steps = ensureTransposeSteps(m);
      const liveStep = (Number(live.transposeStep) || 0) % 4;

      function stepSummary(idx) {
        const s = steps[idx];
        return formatTransposeLabel(s.transpose) + "\n" + s.loops + " LP";
      }

      // ---- Collapsed strip (always in DOM, hidden when expanded) ----
      const strip = el("button", "looper-transpose-strip", transpose);
      strip.type = "button";
      strip.title = "Expand transpose sequencer";
      el("span", "looper-transpose-strip-label", strip).textContent = "LIVE TRANSPOSE";
      const pips = el("div", "looper-transpose-pips", strip);
      for (let i = 0; i < 4; i++) {
        const pip = el("span",
          "looper-transpose-pip" + (i === liveStep ? " active" : ""),
          pips);
        pip.dataset.pipStep = i;
      }
      const stripValue = el("div", "looper-transpose-strip-value", strip);
      stripValue.textContent = formatTransposeLabel(steps[liveStep].transpose);

      strip.addEventListener("click", () => {
        row.classList.remove("transpose-collapsed");
        state.transposeCollapsed[slot] = false;
        fitLooperDeck(shell, sizer, deck, machines.length);
      });

      // ---- Expanded panel ----
      const panel = el("div", "looper-transpose-panel", transpose);

      // Panel header with collapse button
      const panelHeader = el("div", "looper-transpose-panel-header", panel);
      el("span", "looper-section-label", panelHeader).textContent = "LIVE TRANSPOSE";
      const collapseBtn = el("button", "looper-transpose-collapse", panelHeader);
      collapseBtn.type = "button";
      collapseBtn.title = "Collapse transpose sequencer";
      collapseBtn.textContent = "◀";
      collapseBtn.addEventListener("click", () => {
        row.classList.add("transpose-collapsed");
        state.transposeCollapsed[slot] = true;
        fitLooperDeck(shell, sizer, deck, machines.length);
      });

      // Step grid: 4 steps in a 2×2 grid
      const stepGrid = el("div", "looper-transpose-steps", panel);
      for (let stepIndex = 0; stepIndex < 4; stepIndex++) {
        const step = steps[stepIndex];
        const stepBox = el(
          "div",
          "looper-transpose-step" + (stepIndex === liveStep ? " active" : ""),
          stepGrid
        );
        stepBox.dataset.step = stepIndex;
        el("div", "looper-transpose-step-title", stepBox).textContent = "S" + (stepIndex + 1);

        const transposeRow = el("div", "looper-transpose-row", stepBox);
        const tDown = el("button", "", transposeRow);
        tDown.type = "button";
        tDown.textContent = "−";
        const tValue = el("span", "value", transposeRow);
        tValue.textContent = formatTransposeLabel(step.transpose);
        const tUp = el("button", "", transposeRow);
        tUp.type = "button";
        tUp.textContent = "+";
        tDown.addEventListener("click", () => {
          const next = Math.max(-24, step.transpose - 1);
          if (next === step.transpose) return;
          step.transpose = next;
          m.transpose = steps[0].transpose;
          tValue.textContent = formatTransposeLabel(step.transpose);
          send({ op: "set_transpose_step", slot, step: stepIndex, transpose: next });
        });
        tUp.addEventListener("click", () => {
          const next = Math.min(24, step.transpose + 1);
          if (next === step.transpose) return;
          step.transpose = next;
          m.transpose = steps[0].transpose;
          tValue.textContent = formatTransposeLabel(step.transpose);
          send({ op: "set_transpose_step", slot, step: stepIndex, transpose: next });
        });

        const loopsRow = el("div", "looper-transpose-row loops", stepBox);
        const lDown = el("button", "", loopsRow);
        lDown.type = "button";
        lDown.textContent = "−";
        const lValue = el("span", "value", loopsRow);
        lValue.textContent = step.loops + "LP";
        const lUp = el("button", "", loopsRow);
        lUp.type = "button";
        lUp.textContent = "+";
        lDown.addEventListener("click", () => {
          const next = Math.max(1, step.loops - 1);
          if (next === step.loops) return;
          step.loops = next;
          lValue.textContent = step.loops + "LP";
          send({ op: "set_transpose_step", slot, step: stepIndex, loops: next });
        });
        lUp.addEventListener("click", () => {
          const next = Math.min(4, step.loops + 1);
          if (next === step.loops) return;
          step.loops = next;
          lValue.textContent = step.loops + "LP";
          send({ op: "set_transpose_step", slot, step: stepIndex, loops: next });
        });
      }
    }

    row.classList.toggle("playing",
      App.doc.transport.playing && App.doc.transport.mode === "pattern");
  });

  function syncFromEcho(op) {
    const row = channels.querySelector(`.looper-channel[data-slot="${op.slot}"]`);
    if (!row) return;
    if (op.op === "set_mixer") {
      if (op.param === "mute" || op.param === "solo") {
        row.querySelector(`[data-control="${op.param}"]`)
          ?.classList.toggle("on", !!op.value);
      } else {
        row.querySelectorAll(".looper-xy")
          .forEach(pad => pad._sync?.(op.param, op.value));
      }
    } else if (op.op === "set_effect_param" && op.param === "bypass") {
      row.querySelector(`[data-effect-index="${op.index}"]`)
        ?.classList.toggle("on", !op.value);
    }
  }
  window._echoRefresh = syncFromEcho;
  window._statusHook = updateLooperStatus;
  updateLooperStatus(App.status);
  fitLooperDeck(shell, sizer, deck, machines.length);
}

/* Scale the deck so the whole panel always fits the viewport (no scrollbars).
   Tries 1-3 channel columns and keeps whichever yields the largest scale. */
function fitLooperDeck(shell, sizer, deck, channelCount) {
  const channels = deck.querySelector(".looper-channels");

  let lastBox = "";

  function fit() {
    if (!shell.isConnected) return;
    const availW = shell.clientWidth - 24;
    const availH = shell.clientHeight - 24;
    if (availW <= 0 || availH <= 0) return;
    lastBox = availW + "x" + availH;
    let best = { scale: 0, cols: 1, w: 1, h: 1 };
    const maxCols = channels ? Math.min(3, channelCount) : 1;
    for (let cols = 1; cols <= maxCols; cols++) {
      if (channels) {
        channels.style.setProperty("--looper-cols", cols);
        channels.style.setProperty("--looper-rows", Math.ceil(channelCount / cols));
      }
      const w = deck.scrollWidth;
      const h = deck.scrollHeight;
      const scale = Math.min(availW / w, availH / h, 1);
      if (scale > best.scale) best = { scale, cols, w, h };
    }
    if (channels) {
      channels.style.setProperty("--looper-cols", best.cols);
      channels.style.setProperty("--looper-rows", Math.ceil(channelCount / best.cols));
    }
    deck.style.transform = `scale(${best.scale})`;
    sizer.style.width = (best.w * best.scale) + "px";
    sizer.style.height = (best.h * best.scale) + "px";
  }

  App._looperFitObserver?.disconnect();
  App._looperFitObserver = new ResizeObserver(fit);
  App._looperFitObserver.observe(shell);
  if (App._looperFitResize) removeEventListener("resize", App._looperFitResize);
  App._looperFitResize = fit;
  addEventListener("resize", fit);
  // Fallback for hosts that throttle resize events: refit on status ticks.
  App._looperFitCheck = () => {
    if (shell.isConnected &&
        (shell.clientWidth - 24) + "x" + (shell.clientHeight - 24) !== lastBox) fit();
  };
  fit();
}

function updateLooperStatus(status) {
  App._looperFitCheck?.();
  const isPlaying = App.doc?.transport.playing && App.doc.transport.mode === "pattern";
  document.querySelectorAll(".looper-channel").forEach(row => {
    const slot = Number(row.dataset.slot);
    const m = App.doc.machines[slot];
    if (!m) return;
    const live = status.looper?.[String(slot)] || {
      bank: m.bank, pattern: m.pattern, progress: 0,
    };
    const queue = Array.isArray(live.queue) ? live.queue :
      (live.queued_bank !== undefined ?
        [{ bank: live.queued_bank, pattern: live.queued_pattern }] : []);
    row.classList.toggle("playing", isPlaying);
    row.querySelectorAll(".looper-pad").forEach(pad => {
      const bank = Number(pad.dataset.bank);
      const pattern = Number(pad.dataset.pattern);
      const active = bank === live.bank && pattern === live.pattern;
      const queued = queue.some(item => item.bank === bank && item.pattern === pattern);
      pad.classList.toggle("active", active);
      pad.classList.toggle("queued", queued);
      pad.classList.remove("requested");
      pad.style.setProperty("--progress", active ? (live.progress || 0) : 0);
    });
    const readout = row.querySelector(".looper-live-readout");
    if (readout) {
      readout.textContent = "LIVE " + looperPatternKey(live.bank, live.pattern) +
        (queue.length ? "  >  " + looperPatternKey(queue[0].bank, queue[0].pattern) : "");
    }
    const queueReadout = row.querySelector(".looper-queue-readout");
    if (queueReadout) {
      queueReadout.textContent = queue.length ?
        ("QUEUE " + queue.map(item => looperPatternKey(item.bank, item.pattern)).join(" > ")) :
        "QUEUE EMPTY";
    }
    const clearQueue = row.querySelector(".looper-clear-queue");
    if (clearQueue) clearQueue.disabled = !queue.length;
    const mode = live.mode ?? m.looper_mode ?? "queue";
    row.querySelectorAll(".looper-switch[data-mode]").forEach(button => {
      const selected = button.dataset.mode === mode;
      button.classList.toggle("on", selected);
      if (selected) button.setAttribute("aria-pressed", "true");
      else button.removeAttribute("aria-pressed");
    });
    const transposeStep = Number(live.transpose_step ?? 0) % 4;
    row.querySelectorAll(".looper-transpose-step").forEach(stepEl => {
      stepEl.classList.toggle("active", Number(stepEl.dataset.step) === transposeStep);
    });
    row.querySelectorAll(".looper-transpose-pip").forEach(pip => {
      pip.classList.toggle("active", Number(pip.dataset.pipStep) === transposeStep);
    });
    const stripValue = row.querySelector(".looper-transpose-strip-value");
    if (stripValue && m.type !== "beatbox") {
      const steps = ensureTransposeSteps(m);
      stripValue.textContent = formatTransposeLabel(steps[transposeStep].transpose);
    }
    const level = Math.min(1, status.vu?.[slot] || 0);
    row.querySelectorAll(".looper-meter i").forEach((segment, index, all) => {
      segment.classList.toggle("lit", index < Math.ceil(level * all.length));
    });
  });
}
