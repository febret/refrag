/* 8BitSynth (bitsynth) machine panel. */
"use strict";

function build8Bit(body, slot, m) {
  let g = makeGroup("BLEND / PITCH", body);
  widgets(g, slot, m, ["blend", "octave", "semis", "cents"]);
  outGroup(body, slot, m);

  const g2 = makeGroup("EXPRESSION", body);
  g2.box.style.flex = "1 1 100%";
  g2.row.style.flexDirection = "column";
  g2.row.style.alignItems = "stretch";

  const selRow = el("div", "", g2.row);
  selRow.style.display = "flex"; selRow.style.gap = "4px"; selRow.style.marginBottom = "4px";
  const mkSel = (id, label) => {
    const b = el("button", "pattern-btn" + (m.expr_sel === id ? " on" : ""), selRow);
    b.textContent = label;
    b.addEventListener("click", () => {
      m.expr_sel = id;
      send({ op: "set_machine_prop", slot, prop: "expr_sel", value: id });
      renderAll();
    });
  };
  mkSel(0, "EXPR A"); mkSel(1, "EXPR B");
  const copyB = el("button", "pattern-btn", selRow);
  copyB.textContent = "COPY OTHER";
  copyB.addEventListener("click", () => {
    const other = m.expr_sel === 0 ? m.expr_b : m.expr_a;
    setExpr(other);
  });

  const lcd = el("div", "expr-lcd", g2.row);
  const cur = () => (m.expr_sel === 0 ? m.expr_a : m.expr_b);
  lcd.textContent = cur();
  lcd.addEventListener("click", () =>
    promptText("Edit expression (variable: t)", cur(), setExpr));

  function setExpr(v) {
    const prop = m.expr_sel === 0 ? "expr_a" : "expr_b";
    m[prop] = v;
    lcd.textContent = v;
    send({ op: "set_machine_prop", slot, prop, value: v });
  }

  const keys = el("div", "expr-keys", g2.row);
  ["7", "8", "9", "(", ")", "<<", ">>", "&", "|", "^",
   "4", "5", "6", "+", "−", "*", "/", "%", "t", "⌫"].forEach(k => {
    const b = el("button", "", keys);
    b.textContent = k;
    b.addEventListener("click", () => {
      let v = cur();
      if (k === "⌫") v = v.slice(0, -1);
      else if (k === "−") v += "-";
      else v += k;
      setExpr(v);
    });
  });
  const keys2 = el("div", "expr-keys", g2.row);
  ["0", "1", "2", "3"].forEach(k => {
    const b = el("button", "", keys2);
    b.textContent = k;
    b.addEventListener("click", () => setExpr(cur() + k));
  });
}
