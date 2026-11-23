"""Captions: SRT (uploaded as a caption track for long videos) and ASS (burned into Shorts).
Timing comes from the exact length of each synthesized sentence, spread across words by length."""


def _chunks(text, start, end, max_words):
    words = text.split()
    groups = [words[i:i + max_words] for i in range(0, len(words), max_words)] or [[""]]
    weights = [sum(len(w) + 1 for w in g) for g in groups]
    total, t, out = sum(weights) or 1, start, []
    for g, wt in zip(groups, weights):
        d = (end - start) * wt / total
        out.append((t, t + d, " ".join(g)))
        t += d
    return out


def _srt_ts(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues, path, max_words=12):
    """cues: list of (start, end, sentence_text)."""
    n, lines = 0, []
    for s, e, txt in cues:
        for a, b, chunk in _chunks(txt, s, e, max_words):
            n += 1
            lines += [str(n), f"{_srt_ts(a)} --> {_srt_ts(b)}", chunk, ""]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def _ass_ts(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(cues, path, w=1080, h=1920, font_name="DejaVu Sans", max_words=3, y_frac=0.70):
    """Big, bold, centred word-group captions for vertical video."""
    margin_v = int(h * (1 - y_frac))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font_name},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for s, e, txt in cues:
        for a, b, chunk in _chunks(txt, s, e, max_words):
            safe = chunk.replace("{", "(").replace("}", ")").upper()
            ev.append(f"Dialogue: 0,{_ass_ts(a)},{_ass_ts(b)},Cap,,0,0,0,,{{\\fad(40,0)}}{safe}")
    with open(path, "w") as f:
        f.write(header + "\n".join(ev) + "\n")
    return path
