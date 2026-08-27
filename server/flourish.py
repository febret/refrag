"""Flourish: rule-based, seeded expansion of a pattern with extra notes.

generate(pat, themes, seed, drum=False) returns a list of NEW notes
([key, start, dur, vel, flags]) to append to the pattern.  It never
modifies or removes existing notes and never changes the pattern length.
Every returned note carries FLAG (bit 4) so the client can render it
glowing blue, toggle it, or commit it into a normal note.

Generation is deterministic for a given (pattern, themes, seed) so all
clients in a room converge on the same result; a "reroll" is simply a
new seed.
"""

import random

FLAG = 4                     # note flag bit marking a flourish note
BEATS_PER_MEASURE = 4

THEMES = ("major", "minor", "jazzy", "fast", "mellow",
          "syncopated", "arp", "octaves")

MAJOR = (0, 2, 4, 5, 7, 9, 11)
MINOR = (0, 2, 3, 5, 7, 8, 10)

# beatbox channel layout (see state.DEFAULT_BEATBOX_KIT)
KICK, SNARE, CLHAT, OPHAT, CLAP, TOM_LO, TOM_HI, CRASH = range(8)


def base_notes(pat):
    """Notes of a pattern excluding flourish additions."""
    return [n for n in pat["notes"] if not (len(n) > 4 and int(n[4]) & FLAG)]


def generate(pat, themes, seed, drum=False):
    themes = [t for t in themes if t in THEMES]
    rng = random.Random(int(seed) & 0x7FFFFFFF)
    if drum:
        return _drum(pat, themes, rng)
    return _pitched(pat, themes, rng)


# -- key / scale helpers ------------------------------------------------------

def _detect_key(pitches, themes):
    """Best-fitting (root_pc, scale) for the given pitches."""
    if "major" in themes and "minor" not in themes:
        scales = (MAJOR,)
    elif "minor" in themes and "major" not in themes:
        scales = (MINOR,)
    else:
        scales = (MAJOR, MINOR)
    if not pitches:
        return 0, scales[-1]
    pcs = [p % 12 for p in pitches]
    best, best_score = (pcs[0], scales[0]), -1.0
    for root in range(12):
        for sc in scales:
            member = {(root + iv) % 12 for iv in sc}
            score = sum(1.0 for pc in pcs if pc in member)
            score += 0.5 * sum(1.0 for pc in pcs if pc == root)
            if score > best_score:
                best_score, best = score, (root, sc)
    return best


def _degree(root, scale, key):
    """Index of the scale degree closest to key's pitch class."""
    pc = (key - root) % 12
    return min(range(7),
               key=lambda i: min((pc - scale[i]) % 12, (scale[i] - pc) % 12))


def _tone(root, scale, key, steps):
    """Key transposed up `steps` scale degrees (negative allowed)."""
    d = _degree(root, scale, key)
    nd = d + steps
    octs, idx = divmod(nd, 7)
    return key + (scale[idx] + 12 * octs) - scale[d]


def _clamp_key(k):
    return max(12, min(115, int(k)))


# -- pitched machines ---------------------------------------------------------

def _pitched(pat, themes, rng):
    span = pat["length"] * BEATS_PER_MEASURE
    base = base_notes(pat)
    root, scale = _detect_key([n[0] for n in base], themes)

    out = []
    occupied = {(int(n[0]), round(float(n[1]) * 8)) for n in base}
    cap = 16 + 12 * pat["length"]
    density = 1.0
    if "fast" in themes:
        density *= 1.3
    if "mellow" in themes:
        density *= 0.55

    def put(key, start, dur, vel):
        key = _clamp_key(key)
        start = round(float(start) * 8) / 8.0
        if not 0 <= start < span or len(out) >= cap:
            return
        if (key, round(start * 8)) in occupied:
            return
        occupied.add((key, round(start * 8)))
        dur = max(0.25, min(float(dur), span - start))
        out.append([key, start, dur, round(min(1.0, max(0.05, vel)), 3), FLAG])

    # no notes yet: seed an anchor root chord per measure to build on
    anchors = [[n[0], float(n[1]), float(n[2]), float(n[3])] for n in base]
    if not anchors:
        for mstart in range(0, span, BEATS_PER_MEASURE):
            key = 48 + root
            put(key, mstart, BEATS_PER_MEASURE, 0.6)
            anchors.append([48 + root, float(mstart), 4.0, 0.6])
    anchors.sort(key=lambda n: n[1])

    # 1. chords / arps around each anchor
    chord_steps = [2, 4]                       # third + fifth
    if "jazzy" in themes:
        chord_steps += [6, 8]                  # seventh + ninth color tones
    for n in anchors:
        key, start, dur, vel = n[0], n[1], n[2], n[3]
        if rng.random() > 0.9 * density:
            continue
        picked = [s for s in chord_steps
                  if rng.random() < (0.85 if s in (2, 4) else 0.45)]
        if "arp" in themes and picked:
            step = max(0.25, min(0.5, dur / (len(picked) + 1)))
            for i, s in enumerate(picked):
                put(_tone(root, scale, key, s), start + (i + 1) * step,
                    step, vel * rng.uniform(0.45, 0.7))
        else:
            for s in picked:
                put(_tone(root, scale, key, s), start, dur,
                    vel * rng.uniform(0.5, 0.75))

    # 2. octave doubling
    if "octaves" in themes:
        for n in anchors:
            if rng.random() < 0.6 * density:
                shift = -12 if n[0] >= 72 else 12
                put(n[0] + shift, n[1], n[2], n[3] * rng.uniform(0.4, 0.6))

    # 3. fast: scalewise runs bridging gaps between consecutive anchors
    if "fast" in themes:
        for a, b in zip(anchors, anchors[1:] + anchors[:1]):
            gap_start = a[1] + a[2]
            gap_end = b[1] if b[1] > a[1] else span
            if gap_end - gap_start < 0.5:
                continue
            steps = min(6, int((gap_end - gap_start) / 0.25))
            direction = 1 if b[0] >= a[0] else -1
            for i in range(steps):
                if rng.random() > 0.75:
                    continue
                put(_tone(root, scale, a[0], direction * (i + 1)),
                    gap_start + i * 0.25, 0.25, rng.uniform(0.35, 0.55))

    # 4. syncopated: short chord tones on offbeats
    if "syncopated" in themes:
        center = sorted(n[0] for n in anchors)[len(anchors) // 2]
        for b8 in range(span * 2):
            start = b8 / 2.0 + 0.5
            if start >= span or rng.random() > 0.3 * density:
                continue
            step = rng.choice([0, 2, 4])
            put(_tone(root, scale, center, step), start, 0.25,
                rng.uniform(0.3, 0.5))

    # 5. mellow: one sustained low pad note per measure
    if "mellow" in themes:
        low = min(n[0] for n in anchors)
        for mstart in range(0, span, BEATS_PER_MEASURE):
            pad = _tone(root, scale, low, 0) - 12
            put(pad, mstart, BEATS_PER_MEASURE, rng.uniform(0.25, 0.35))

    return out


# -- beatbox drum grid --------------------------------------------------------

def _drum(pat, themes, rng):
    span = pat["length"] * BEATS_PER_MEASURE
    base = base_notes(pat)
    out = []
    occupied = {(int(n[0]) % 8, round(float(n[1]) * 4)) for n in base}
    cap = 16 + 16 * pat["length"]
    density = 1.0
    if "fast" in themes:
        density *= 1.3
    if "mellow" in themes:
        density *= 0.5

    def put(ch, start, vel):
        start = round(float(start) * 4) / 4.0
        if not 0 <= start < span or len(out) >= cap:
            return
        if (ch, round(start * 4)) in occupied:
            return
        occupied.add((ch, round(start * 4)))
        out.append([ch, start, 0.25, round(min(1.0, max(0.05, vel)), 3), FLAG])

    steps16 = span * 4

    # hat bed: 16ths when fast, 8ths otherwise (sparser offbeat hats if mellow)
    hat_step = 1 if "fast" in themes else 2
    for s in range(0, steps16, hat_step):
        if "mellow" in themes and s % 4 != 2:
            continue
        if rng.random() < 0.8 * density:
            ch = OPHAT if ("mellow" in themes and rng.random() < 0.4) else CLHAT
            put(ch, s / 4.0, rng.uniform(0.25, 0.5))

    # ghost snares leading into backbeats (beats 2 and 4 of each measure)
    if "fast" in themes or "jazzy" in themes:
        for m in range(pat["length"]):
            for back in (1.0, 3.0):
                if rng.random() < 0.45 * density:
                    put(SNARE, m * 4 + back - 0.25, rng.uniform(0.15, 0.3))

    # syncopated: offbeat kicks and layered claps
    if "syncopated" in themes:
        for b in range(span):
            if rng.random() < 0.35 * density:
                put(KICK, b + 0.5, rng.uniform(0.5, 0.8))
        for m in range(pat["length"]):
            if rng.random() < 0.4:
                put(CLAP, m * 4 + 3.0, rng.uniform(0.4, 0.6))

    # harmonic themes translate to fills / accents on a drum kit
    if "major" in themes or "arp" in themes:
        if rng.random() < 0.7:
            put(CRASH, 0.0, rng.uniform(0.4, 0.6))
    if "minor" in themes or "jazzy" in themes or "arp" in themes:
        # tom fill over the last beat of the pattern
        fill = [TOM_HI, TOM_HI, TOM_LO, TOM_LO]
        for i, ch in enumerate(fill):
            if rng.random() < 0.6 * density:
                put(ch, span - 1 + i * 0.25, rng.uniform(0.35, 0.6))
    if "octaves" in themes:
        for m in range(pat["length"]):
            if rng.random() < 0.5:
                put(TOM_LO, m * 4 + 2.5, rng.uniform(0.3, 0.5))

    return out
