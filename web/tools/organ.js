/* Organ machine panel. */
"use strict";

function buildOrgan(body, slot, m) {
  const g = makeGroup("DRAWBARS", body);
  ["bar16", "bar5_13", "bar8", "bar4", "bar2_23", "bar2", "bar1_35", "bar1_13", "bar1"]
    .forEach(id => {
      const spec = App.catalog.machines.organ.controls[id];
      const w = makeSlider(spec, m.params[id],
        (v) => { m.params[id] = v; send({ op: "set_param", slot, param: id, value: v }); },
        { height: 90, cls: "drawbar" });
      w._autoKey = slot + ":" + id;
      w.dataset.autokey = slot + ":" + id;
      g.row.appendChild(w);
    });
  let g2 = makeGroup("PERCUSSION", body);
  widgets(g2, slot, m, ["perc_tone", "perc_decay"]);
  g2 = makeGroup("LESLIE", body);
  widgets(g2, slot, m, ["leslie_speed", "leslie_depth"]);
  g2 = makeGroup("DRIVE", body);
  widgets(g2, slot, m, ["drive"]);
  outGroup(body, slot, m);
}
