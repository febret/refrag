/* BeatBox machine panel. */
"use strict";

function buildBeatBox(body, slot, m) {
  const chWrap = el("div", "", body);
  chWrap.style.flex = "1 1 100%";
  chWrap.style.display = "flex";
  chWrap.style.flexDirection = "column";
  chWrap.style.gap = "3px";
  m.channels.forEach((ch, ci) => {
    const row = el("div", "bb-channel", chWrap);
    const ms = makeMS(ch.mute, ch.solo,
      (v) => send({ op: "set_channel_param", slot, channel: ci, param: "mute", value: v }),
      (v) => send({ op: "set_channel_param", slot, channel: ci, param: "solo", value: v }));
    row.appendChild(ms);
    const lcd = el("div", "bb-lcd", row);
    lcd.textContent = ch.sample || "(empty)";
    lcd.title = "Click to load a sample";
    lcd.addEventListener("click", () => {
      pickSample("LOAD SAMPLE — CH " + (ci + 1),
        (name) => send({ op: "set_channel_param", slot, channel: ci, param: "sample", value: name }));
    });
    const cc = App.catalog.machines.beatbox.channel_controls;
    for (const pid in cc) {
      const w = makeKnob(cc[pid], ch.params[pid],
        (v) => send({ op: "set_channel_param", slot, channel: ci, param: pid, value: v }));
      row.appendChild(w);
    }
    const mg = makeSelector({ label: "Group", options: ["OFF", "G1", "G2", "G3", "G4"] },
      ch.mute_group, (v) => send({ op: "set_channel_param", slot, channel: ci, param: "mute_group", value: v }));
    row.appendChild(mg);
    const play = el("button", "bb-play", row);
    play.innerHTML = "&#9654;";
    play.addEventListener("pointerdown", () => sendNote(slot, ci, true));
    play.addEventListener("pointerup", () => sendNote(slot, ci, false));
  });
  outGroup(body, slot, m);
}
