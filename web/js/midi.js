/* Web MIDI input: play the currently viewed machine from a USB MIDI keyboard.
   Local hardware preference (enabled flag, selected device, channel filter) is
   kept in localStorage — it is per-browser, not part of the shared room state. */
"use strict";

const MidiInput = {
  supported: !!(navigator.requestMIDIAccess),
  access: null,
  inputs: [],           // [{id, name, manufacturer}]
  activeNotes: new Map(),  // note -> slot it was triggered on (so release always targets the right machine)
  onDevicesChanged: null, // optional callback for settings UI refresh

  _prefs() {
    try {
      return JSON.parse(localStorage.getItem("refrag_midi") || "{}");
    } catch (e) { return {}; }
  },
  _savePrefs(p) {
    try { localStorage.setItem("refrag_midi", JSON.stringify(p)); } catch (e) {}
  },
  isEnabled() { return !!this._prefs().enabled; },
  getSelectedId() { return this._prefs().deviceId || ""; },
  getChannel() {
    const ch = this._prefs().channel;
    return (ch === undefined || ch === null) ? "all" : ch; // "all" or 0-15
  },
  setChannel(ch) {
    const p = this._prefs(); p.channel = ch; this._savePrefs(p);
  },
  setSelectedId(id) {
    const p = this._prefs(); p.deviceId = id; this._savePrefs(p);
    this._releaseAllNotes();
    this._bindInputs();
  },

  async enable() {
    if (!this.supported) return false;
    const p = this._prefs(); p.enabled = true; this._savePrefs(p);
    if (!this.access) {
      try {
        this.access = await navigator.requestMIDIAccess({ sysex: false });
      } catch (e) {
        return false;
      }
      this.access.onstatechange = () => { this._releaseAllNotes(); this._refreshDeviceList(); this._bindInputs(); };
    }
    this._refreshDeviceList();
    this._bindInputs();
    return true;
  },

  disable() {
    const p = this._prefs(); p.enabled = false; this._savePrefs(p);
    this._releaseAllNotes();
    this._unbindInputs();
  },

  listDevices() { return this.inputs; },

  _refreshDeviceList() {
    this.inputs = [];
    if (this.access) {
      for (const input of this.access.inputs.values()) {
        this.inputs.push({ id: input.id, name: input.name || "MIDI device", manufacturer: input.manufacturer || "" });
      }
    }
    if (this.onDevicesChanged) this.onDevicesChanged();
  },

  _unbindInputs() {
    if (!this.access) return;
    for (const input of this.access.inputs.values()) input.onmidimessage = null;
  },

  _bindInputs() {
    this._unbindInputs();
    if (!this.access || !this.isEnabled()) return;
    const selId = this.getSelectedId();
    for (const input of this.access.inputs.values()) {
      if (selId && input.id !== selId) continue;
      input.onmidimessage = (ev) => this._handleMessage(ev);
    }
  },

  _handleMessage(ev) {
    const [status, d1, d2] = ev.data;
    const cmd = status & 0xf0;
    const channel = status & 0x0f;
    const filter = this.getChannel();
    if (filter !== "all" && Number(filter) !== channel) return;
    if (cmd === 0x90 && d2 > 0) {
      this._noteOn(d1, d2);
    } else if (cmd === 0x80 || (cmd === 0x90 && d2 === 0)) {
      this._noteOff(d1);
    }
  },

  _targetSlot() {
    if (typeof App === "undefined" || !App.view || App.view.kind !== "machine") return null;
    return App.view.slot;
  },

  _noteOn(note, vel) {
    const slot = this._targetSlot();
    if (slot === null || slot === undefined) return;
    // Re-trigger if the same note is already sounding (e.g. duplicate MIDI events),
    // so it's never left permanently on without a matching sustain.
    if (this.activeNotes.has(note)) this._noteOff(note);
    this.activeNotes.set(note, slot);
    sendNote(slot, note, true, vel / 127);
    if (window._kbdFlash) window._kbdFlash(note, true);
  },

  _noteOff(note) {
    // Always release on the slot the note was originally triggered on, so
    // switching machine panels while the key is held doesn't strand the note.
    const slot = this.activeNotes.get(note);
    this.activeNotes.delete(note);
    if (slot === null || slot === undefined) return;
    sendNote(slot, note, false);
    if (window._kbdFlash) window._kbdFlash(note, false);
  },

  /* Release every currently-sounding MIDI-triggered note (e.g. before switching
     input device or disabling MIDI), so no note is left stuck sustaining. */
  _releaseAllNotes() {
    for (const note of Array.from(this.activeNotes.keys())) this._noteOff(note);
  },

  /* Auto-start on load if the user previously enabled MIDI input. */
  async init() {
    if (this.supported && this.isEnabled()) await this.enable();
  },
};

window.addEventListener("load", () => { MidiInput.init(); });
window.addEventListener("beforeunload", () => { MidiInput._releaseAllNotes(); });
