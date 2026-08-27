/* Modular machine panel (front bays + rear wiring view). */
"use strict";

function buildModular(body, slot, m) {
  const bar = el("div", "", body);
  bar.style.flex = "1 1 100%"; bar.style.display = "flex"; bar.style.gap = "4px";
  const rear = m._rear || false;
  const flip = el("button", "pattern-btn" + (rear ? " on" : ""), bar);
  flip.textContent = rear ? "SHOW FRONT" : "SHOW REAR (WIRING)";
  flip.addEventListener("click", () => { m._rear = !rear; renderAll(); });

  if (!rear) buildModularFront(body, slot, m);
  else buildModularRear(body, slot, m);
  outGroup(body, slot, m);
  const g = makeGroup("PATCH GAIN", body);
  widgets(g, slot, m, ["out_gain"]);
}

function buildModularFront(body, slot, m) {
  const bays = el("div", "mod-bays", body);
  bays.style.flex = "1 1 100%";
  const catalogC = App.catalog.modularComponents;
  for (let i = 0; i < m.components.length; i++) {
    const comp = m.components[i];
    if (comp === "occupied") continue;
    if (!comp) {
      const bay = el("div", "mod-bay", bays);
      bay.textContent = "+ component";
      bay.addEventListener("click", () => {
        const types = Object.keys(catalogC);
        pickFromList("SELECT COMPONENT",
          types.map(t => catalogC[t].name + (catalogC[t].size > 1 ? " (2 bays)" : "")),
          -1, (idx) => send({ op: "mod_place", slot, bay: i, ctype: types[idx] }));
      });
      continue;
    }
    const spec = catalogC[comp.type];
    const c = el("div", "mod-comp" + (spec.size > 1 ? " wide" : ""), bays);
    const h = el("div", "mc-head", c);
    el("span", "", h).textContent = spec.name.toUpperCase();
    const x = el("span", "mc-del", h); x.textContent = "✕";
    x.addEventListener("click", () => send({ op: "mod_remove", slot, bay: i }));
    const cb = el("div", "mc-body", c);
    for (const pid in spec.controls) {
      const cspec = spec.controls[pid];
      let w;
      const onCh = (v) => send({ op: "mod_param", slot, bay: i, param: pid, value: v });
      if (cspec.type === "select") w = makeSelector(cspec, comp.params[pid], onCh);
      else if (cspec.type === "toggle") w = makeToggle(cspec, comp.params[pid], onCh);
      else w = makeKnob(cspec, comp.params[pid], onCh);
      cb.appendChild(w);
    }
  }
}

function buildModularRear(body, slot, m) {
  const wrap = el("div", "mod-rear-wrap", body);
  wrap.style.flex = "1 1 100%";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.id = "mod-wires";
  const catalogC = App.catalog.modularComponents;
  let pendingSrc = null;

  const panel = el("div", "", wrap);
  panel.style.display = "flex"; panel.style.flexDirection = "column"; panel.style.gap = "8px";

  // fixed panel jacks
  const fixedRow = el("div", "jack-row", panel);
  fixedRow.style.background = "#1d2030"; fixedRow.style.padding = "8px";
  fixedRow.style.borderRadius = "5px";
  const addJack = (parent, jid, label, isOut) => {
    const item = el("div", "jack-item", parent);
    const j = el("div", "jack", item);
    j.dataset.jack = jid; j.dataset.out = isOut ? "1" : "0";
    el("span", "", item).textContent = label;
    j.addEventListener("click", () => {
      if (isOut) {
        pendingSrc = pendingSrc === jid ? null : jid;
        document.querySelectorAll(".jack").forEach(x => x.classList.remove("sel"));
        if (pendingSrc) j.classList.add("sel");
      } else if (pendingSrc) {
        send({ op: "mod_wire", slot, src: pendingSrc, dst: jid });
        pendingSrc = null;
      } else {
        // clicking an input jack with a wire removes it
        const w = m.wires.find(w => w[1] === jid);
        if (w) send({ op: "mod_wire", slot, src: w[0], dst: w[1], remove: 1 });
      }
    });
    return j;
  };
  addJack(fixedRow, "panel.note_cv", "NOTE CV", true);
  addJack(fixedRow, "panel.velocity", "VELOCITY", true);
  addJack(fixedRow, "panel.mod_wheel", "MOD WHEEL", true);
  el("div", "spacer", fixedRow).style.flex = "1";
  addJack(fixedRow, "panel.volume_mod", "VOL MOD", false);
  addJack(fixedRow, "panel.left_out", "LEFT/MONO OUT", false);
  addJack(fixedRow, "panel.right_out", "RIGHT OUT", false);

  // component jacks
  const bays = el("div", "mod-bays", panel);
  for (let i = 0; i < m.components.length; i++) {
    const comp = m.components[i];
    if (comp === "occupied") continue;
    if (!comp) { el("div", "mod-bay", bays).textContent = "—"; continue; }
    const spec = catalogC[comp.type];
    const c = el("div", "mod-comp" + (spec.size > 1 ? " wide" : ""), bays);
    const h = el("div", "mc-head", c);
    el("span", "", h).textContent = spec.name.toUpperCase();
    const cb = el("div", "mc-body", c);
    cb.style.justifyContent = "space-between"; cb.style.width = "100%";
    const inCol = el("div", "jack-row", cb);
    spec.inputs.forEach(inp => addJack(inCol, `c${i}.${inp}`, inp, false));
    const outCol = el("div", "jack-row", cb);
    spec.outputs.forEach(out => addJack(outCol, `c${i}.${out}`, out, true));
  }

  wrap.appendChild(svg);
  // draw wires after layout
  requestAnimationFrame(() => {
    const wr = wrap.getBoundingClientRect();
    svg.setAttribute("width", wr.width);
    svg.setAttribute("height", wr.height);
    svg.style.position = "absolute";
    svg.style.left = 0; svg.style.top = 0;
    m.wires.forEach(([src, dst], wi) => {
      const a = wrap.querySelector(`[data-jack="${src}"]`);
      const b = wrap.querySelector(`[data-jack="${dst}"]`);
      if (!a || !b) return;
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const x1 = ra.left + ra.width / 2 - wr.left, y1 = ra.top + ra.height / 2 - wr.top;
      const x2 = rb.left + rb.width / 2 - wr.left, y2 = rb.top + rb.height / 2 - wr.top;
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const sag = 30 + (wi % 3) * 14;
      path.setAttribute("d", `M ${x1} ${y1} C ${x1} ${y1 + sag}, ${x2} ${y2 + sag}, ${x2} ${y2}`);
      path.setAttribute("stroke", ["#e8a33d", "#4f8dff", "#43d34d", "#d34f4f"][wi % 4]);
      path.setAttribute("stroke-width", "3");
      path.setAttribute("fill", "none");
      path.setAttribute("opacity", "0.85");
      svg.appendChild(path);
    });
  });
}
