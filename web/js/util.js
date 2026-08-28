/* Refrag UI widget helpers (dependency-free). */
"use strict";

function el(tag, cls, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (parent) parent.appendChild(e);
  return e;
}

function fmtVal(spec, v) {
  if (spec.curve === "int") return String(Math.round(v));
  if (typeof v === "number") return (Math.round(v * 100) / 100).toString();
  return String(v);
}

/* Rotary knob widget. onChange(value) fires continuously. */
function makeKnob(spec, value, onChange, opts = {}) {
  const root = el("div", "knob");
  const cv = el("canvas", "", root);
  cv.width = 72; cv.height = 72;
  const valTip = el("div", "k-value", root);
  const lab = el("div", "k-label", root);
  lab.textContent = spec.label;
  let cur = value !== undefined ? value : spec.default;

  function draw() {
    const ctx = cv.getContext("2d");
    const c = 36, r = 30;
    ctx.clearRect(0, 0, 72, 72);
    // rim
    const g = ctx.createRadialGradient(c - 8, c - 10, 4, c, c, r);
    g.addColorStop(0, "#e7eaf2"); g.addColorStop(0.55, "#a9aebe");
    g.addColorStop(1, "#43464f");
    ctx.beginPath(); ctx.arc(c, c, r, 0, 7); ctx.fillStyle = "#16181f"; ctx.fill();
    ctx.beginPath(); ctx.arc(c, c, r - 3, 0, 7); ctx.fillStyle = g; ctx.fill();
    // face
    ctx.beginPath(); ctx.arc(c, c, r - 10, 0, 7);
    const g2 = ctx.createRadialGradient(c - 5, c - 7, 2, c, c, r - 10);
    g2.addColorStop(0, "#5d6270"); g2.addColorStop(1, "#23252c");
    ctx.fillStyle = g2; ctx.fill();
    // pointer
    const f = (cur - spec.min) / (spec.max - spec.min || 1);
    const ang = (-225 + f * 270) * Math.PI / 180;
    ctx.strokeStyle = "#f2f4fa"; ctx.lineWidth = 4; ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(c + Math.cos(ang) * 8, c + Math.sin(ang) * 8);
    ctx.lineTo(c + Math.cos(ang) * (r - 7), c + Math.sin(ang) * (r - 7));
    ctx.stroke();
    valTip.textContent = (opts.format ? opts.format(cur) : fmtVal(spec, cur));
  }
  function setFromDrag(dx, fine) {
    const range = spec.max - spec.min;
    let nv = cur + dx * range / (fine ? 900 : 160);
    nv = Math.min(spec.max, Math.max(spec.min, nv));
    if (spec.curve === "int") nv = Math.round(nv);
    if (nv !== cur) { cur = nv; draw(); onChange(cur); }
  }
  let lastX = null, lastY = null;
  cv.addEventListener("pointerdown", (e) => {
    lastX = e.clientX; lastY = e.clientY; cv.setPointerCapture(e.pointerId);
    root.classList.add("dragging");
    if (opts.onGrab) opts.onGrab();
    e.preventDefault();
  });
  cv.addEventListener("pointermove", (e) => {
    if (lastX === null) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    // Horizontal drag sets the value; ignore vertical-only movement.
    if (Math.abs(dx) > Math.abs(dy)) setFromDrag(dx, e.shiftKey);
  });
  cv.addEventListener("pointerup", () => { lastX = null; lastY = null; root.classList.remove("dragging"); });
  cv.addEventListener("dblclick", () => {
    if (opts.onDouble) { opts.onDouble(); return; }
    cur = spec.default; draw(); onChange(cur);
  });
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    setFromDrag(e.deltaY > 0 ? 8 : -8, e.shiftKey);
  }, { passive: false });

  draw();
  root._set = (v) => { cur = v; draw(); };
  root._get = () => cur;
  return root;
}

/* Vertical slider. */
function makeSlider(spec, value, onChange, opts = {}) {
  const root = el("div", "vslider" + (opts.cls ? " " + opts.cls : ""));
  const track = el("div", "track", root);
  const thumb = el("div", "thumb", track);
  const lab = el("div", "k-label", root);
  lab.textContent = spec.label;
  let cur = value !== undefined ? value : spec.default;
  const H = opts.height || 64;
  if (opts.height) track.style.height = H + "px";

  function draw() {
    const f = (cur - spec.min) / (spec.max - spec.min || 1);
    thumb.style.top = ((1 - f) * (H - 10)) + "px";
  }
  function setFromY(clientY) {
    const r = track.getBoundingClientRect();
    let f = 1 - (clientY - r.top) / r.height;
    f = Math.min(1, Math.max(0, f));
    const nv = spec.min + f * (spec.max - spec.min);
    if (nv !== cur) { cur = nv; draw(); onChange(cur); }
  }
  let drag = false;
  root.addEventListener("pointerdown", (e) => {
    drag = true; root.setPointerCapture(e.pointerId);
    if (opts.onGrab) opts.onGrab();
    setFromY(e.clientY); e.preventDefault();
  });
  root.addEventListener("pointermove", (e) => { if (drag) setFromY(e.clientY); });
  root.addEventListener("pointerup", () => { drag = false; });
  root.addEventListener("dblclick", () => {
    if (opts.onDouble) { opts.onDouble(); return; }
    cur = spec.default; draw(); onChange(cur);
  });
  draw();
  root._set = (v) => { cur = v; draw(); };
  root._get = () => cur;
  return root;
}

/* Selector: LCD that cycles options on click, or opens a list on long list. */
function makeSelector(spec, value, onChange) {
  const root = el("div", "selector");
  const lcd = el("div", "sel-lcd", root);
  const lab = el("div", "k-label", root);
  lab.textContent = spec.label;
  let cur = value !== undefined ? value : spec.default;
  function draw() { lcd.textContent = spec.options[cur] ?? "?"; }
  lcd.addEventListener("click", () => {
    if (spec.options.length > 6) {
      pickFromList(spec.label, spec.options, cur, (i) => {
        cur = i; draw(); onChange(cur);
      });
    } else {
      cur = (cur + 1) % spec.options.length; draw(); onChange(cur);
    }
  });
  lcd.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    cur = (cur - 1 + spec.options.length) % spec.options.length;
    draw(); onChange(cur);
  });
  draw();
  root._set = (v) => { cur = v; draw(); };
  root._get = () => cur;
  return root;
}

function makeToggle(spec, value, onChange) {
  const root = el("div", "toggle");
  el("div", "t-btn", root);
  const lab = el("div", "k-label", root);
  lab.textContent = spec.label;
  let cur = value ? 1 : 0;
  function draw() { root.classList.toggle("on", !!cur); }
  root.addEventListener("click", () => { cur = cur ? 0 : 1; draw(); onChange(cur); });
  draw();
  root._set = (v) => { cur = v ? 1 : 0; draw(); };
  root._get = () => cur;
  return root;
}

function makeVU(horizontal) {
  const root = el("div", "vu" + (horizontal ? " vu-h" : ""));
  const fill = el("div", "vu-fill", root);
  root._set = (v) => {
    const pct = Math.min(1, v) * 100;
    if (horizontal) { fill.style.height = "100%"; fill.style.width = pct + "%"; }
    else fill.style.height = pct + "%";
  };
  return root;
}

function makeGroup(title, parent) {
  const gb = el("div", "groupbox", parent);
  const t = el("div", "gb-title", gb);
  t.textContent = title;
  const row = el("div", "gb-row", gb);
  return { box: gb, row };
}

/* Mute/solo pair. */
function makeMS(m, s, onM, onS) {
  const root = el("div", "ms");
  const bm = el("button", "m" + (m ? " on" : ""), root); bm.textContent = "M";
  const bs = el("button", "s" + (s ? " on" : ""), root); bs.textContent = "S";
  bm.addEventListener("click", () => { bm.classList.toggle("on"); onM(bm.classList.contains("on") ? 1 : 0); });
  bs.addEventListener("click", () => { bs.classList.toggle("on"); onS(bs.classList.contains("on") ? 1 : 0); });
  root._set = (mv, sv) => { bm.classList.toggle("on", !!mv); bs.classList.toggle("on", !!sv); };
  return root;
}

/* Preview keyboard: 2 octaves within given base octave. */
function makeKeyboard(baseOctaveGetter, onNote, opts = {}) {
  const wrap = el("div", "kbd-wrap");
  const kbd = el("div", "kbd", wrap);
  const octs = el("div", "oct-btns", wrap);
  const up = el("button", "", octs); up.innerHTML = "&#9650;";
  const dn = el("button", "", octs); dn.innerHTML = "&#9660;";
  const NW = 14;      // white keys shown (2 octaves)
  const whiteSemis = [0, 2, 4, 5, 7, 9, 11];
  const blackSemis = { 0: 1, 1: 3, 3: 6, 4: 8, 5: 10 };
  const keys = new Map();

  function rebuild() {
    kbd.innerHTML = "";
    keys.clear();
    const oct = baseOctaveGetter();
    const w = 100 / NW;
    for (let i = 0; i < NW; i++) {
      const octOff = Math.floor(i / 7);
      const semi = whiteSemis[i % 7];
      const note = (oct + 1 + octOff) * 12 + semi;
      const k = el("div", "wkey", kbd);
      k.style.left = (i * w) + "%"; k.style.width = w + "%";
      k.dataset.note = note;
      keys.set(note, k);
      if (semi === 0) {
        const l = el("div", "keylabel", kbd);
        l.textContent = "C" + (oct + octOff);
        l.style.left = (i * w + 0.5) + "%";
      }
    }
    for (let i = 0; i < NW; i++) {
      const wi = i % 7;
      if (blackSemis[wi] === undefined || i === NW - 1) continue;
      const octOff = Math.floor(i / 7);
      const note = (oct + 1 + octOff) * 12 + blackSemis[wi];
      const k = el("div", "bkey", kbd);
      k.style.left = (i * w + w * 0.62) + "%"; k.style.width = (w * 0.72) + "%";
      k.dataset.note = note;
      keys.set(note, k);
    }
  }
  let activeNote = null;
  function keyAt(x, y) {
    const els = document.elementsFromPoint(x, y);
    for (const e of els) if (e.dataset && e.dataset.note) return +e.dataset.note;
    return null;
  }
  kbd.addEventListener("pointerdown", (e) => {
    kbd.setPointerCapture(e.pointerId);
    const n = keyAt(e.clientX, e.clientY);
    if (n !== null) { activeNote = n; keys.get(n)?.classList.add("down"); onNote(n, true); }
    e.preventDefault();
  });
  kbd.addEventListener("pointermove", (e) => {
    if (activeNote === null) return;
    const n = keyAt(e.clientX, e.clientY);
    if (n !== null && n !== activeNote) {
      keys.get(activeNote)?.classList.remove("down"); onNote(activeNote, false);
      activeNote = n; keys.get(n)?.classList.add("down"); onNote(n, true);
    }
  });
  function release() {
    if (activeNote !== null) {
      keys.get(activeNote)?.classList.remove("down");
      onNote(activeNote, false); activeNote = null;
    }
  }
  kbd.addEventListener("pointerup", release);
  kbd.addEventListener("pointercancel", release);
  up.addEventListener("click", () => { if (opts.onOctave) opts.onOctave(1); rebuild(); });
  dn.addEventListener("click", () => { if (opts.onOctave) opts.onOctave(-1); rebuild(); });
  rebuild();
  wrap._rebuild = rebuild;
  wrap._flash = (note, on) => { keys.get(note)?.classList.toggle("down", on); };
  return wrap;
}

/* ---------------- modals ---------------- */

function closeModal() {
  document.getElementById("modal-root").innerHTML = "";
}

function showModal(title, buildBody, actions) {
  const rootEl = document.getElementById("modal-root");
  rootEl.innerHTML = "";
  const ov = el("div", "modal-overlay", rootEl);
  const m = el("div", "modal", ov);
  const h = el("h3", "", m); h.textContent = title;
  const body = el("div", "modal-body", m);
  buildBody(body);
  const act = el("div", "modal-actions", m);
  (actions || [{ label: "Close" }]).forEach(a => {
    const b = el("button", a.primary ? "primary" : "", act);
    b.textContent = a.label;
    b.addEventListener("click", () => {
      if (!a.onClick || a.onClick() !== false) closeModal();
    });
  });
  ov.addEventListener("click", (e) => { if (e.target === ov) closeModal(); });
  return { body, overlay: ov };
}

function pickFromList(title, items, selIdx, onPick) {
  showModal(title, (body) => {
    const list = el("div", "file-list", body);
    items.forEach((it, i) => {
      const f = el("div", "fitem" + (i === selIdx ? " sel" : ""), list);
      f.textContent = it;
      f.addEventListener("click", () => { closeModal(); onPick(i, it); });
    });
    if (!items.length) el("div", "", body).textContent = "(empty)";
  });
}

function promptText(title, initial, onOk) {
  const { body } = showModal(title, (b) => {
    const inp = el("input", "", b);
    inp.type = "text"; inp.value = initial || "";
    setTimeout(() => { inp.focus(); inp.select(); }, 50);
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { closeModal(); onOk(inp.value); }
    });
    b._inp = inp;
  }, [
    { label: "Cancel" },
    { label: "OK", primary: true, onClick: () => { onOk(body._inp.value); } },
  ]);
}

function confirmBox(title, text, onOk) {
  showModal(title, (b) => { el("div", "", b).textContent = text; }, [
    { label: "Cancel" },
    { label: "OK", primary: true, onClick: onOk },
  ]);
}

/* Brief non-blocking notification (e.g. save confirmation, errors). */
function showToast(text, isError = false) {
  let root = document.getElementById("toast-root");
  if (!root) {
    root = el("div", "", document.body);
    root.id = "toast-root";
  }
  const t = el("div", "toast" + (isError ? " error" : ""), root);
  t.textContent = text;
  setTimeout(() => t.classList.add("show"), 10);
  setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => t.remove(), 300);
  }, 2500);
}
