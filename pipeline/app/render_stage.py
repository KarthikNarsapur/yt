"""Stage 2 (after you approve): voice, slides, captions, render long video + Short + thumbnail."""
import datetime as dt
import math
import re
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf

from . import captions, pexels, tts, video, visuals
from . import config as C
from .storage import Store, run_key

LONG = (1920, 1080)
SHORT = (1080, 1920)
PAUSE_SENT, PAUSE_SECTION = 0.28, 0.6


class Track:
    """Builds narration audio and records exact sentence timings."""

    def __init__(self):
        self.parts, self.t, self.cues = [], 0.0, []

    def say(self, text):
        a = tts.synth(text)
        start = self.t
        self.parts.append(a)
        self.t += len(a) / tts.SAMPLE_RATE
        self.cues.append((start, self.t, text))
        self.pause(PAUSE_SENT)
        return start, self.t

    def pause(self, s):
        self.parts.append(tts.silence(s))
        self.t += s

    def write(self, path):
        sf.write(path, np.concatenate(self.parts) if self.parts else tts.silence(1), tts.SAMPLE_RATE)
        return path


def _reveal(bullets, sent_times, t_from, t_to):
    """Return [(start, end, shown_count)] so bullets appear one per sentence group."""
    k = max(len(bullets), 1)
    starts = [s for s, _ in sent_times]
    m = len(starts)
    marks = [t_from] + [starts[min(m - 1, math.floor(j * m / k))] for j in range(1, k)]
    marks = sorted(set(max(t_from, x) for x in marks))
    out = []
    for i, s in enumerate(marks):
        e = marks[i + 1] if i + 1 < len(marks) else t_to
        if e > s:
            out.append((s, e, min(i + 1, k)))
    return out


def _plan_section(cat, sec, times, t0, t1, idx, total, portrait, title_text=None, kicker=None):
    """Turn one section (sentence timings) into visual events."""
    ev = []
    head_end = times[0][1] + PAUSE_SENT if len(times) > 1 else t1
    ev.append({"kind": "title", "heading": title_text or sec["heading"], "kicker": kicker,
               "broll": sec.get("broll"), "start": t0, "end": head_end, "counter": (idx, total)})
    rest = times[1:]
    if not rest:
        return ev
    code = sec.get("code")
    split = len(rest) if not code else max(1, math.ceil(len(rest) / 2))
    bullets = sec.get("bullets") or []
    b_end = rest[split][0] if split < len(rest) else t1
    if bullets:
        for s, e, shown in _reveal(bullets, rest[:split], head_end, b_end):
            ev.append({"kind": "bullets", "heading": sec["heading"], "bullets": bullets, "shown": shown,
                       "start": s, "end": e, "counter": (idx, total)})
    else:
        ev[-1]["end"] = b_end
    if code and split < len(rest):
        ev.append({"kind": "code", "heading": sec["heading"], "lang": code.get("lang", "bash"),
                   "code": code["content"], "start": b_end, "end": t1, "counter": (idx, total)})
    elif ev[-1]["end"] < t1:
        ev[-1]["end"] = t1
    return ev


def _draw(e, cat, size, wd, n):
    w, h = size
    path = os.path.join(wd, f"v{n:04d}.jpg")
    portrait = h > w
    if e["kind"] == "title":
        clip = pexels.fetch(e.get("broll"), portrait, wd) if e.get("broll") else None
        if clip:
            ov = visuals.lower_third_overlay(os.path.join(wd, f"o{n:04d}.png"), w, h, cat, e["heading"])
            return ("broll", clip, ov)
        visuals.title_card(path, w, h, cat, e["heading"], kicker=e.get("kicker"), counter=e.get("counter"))
    elif e["kind"] == "bullets":
        visuals.bullets_card(path, w, h, cat, e["heading"], e["bullets"], e["shown"], counter=e.get("counter"))
    elif e["kind"] == "code":
        visuals.code_card(path, w, h, cat, e["heading"], e["lang"], e["code"], counter=e.get("counter"))
    elif e["kind"] == "end":
        visuals.end_card(path, w, h, cat, e["line1"], e["line2"])
    return ("image", path, None)


def _render_events(events, cat, size, wd, out):
    os.makedirs(wd, exist_ok=True)
    jobs = []
    for n, e in enumerate(events):
        frames = round(e["end"] * C.FPS) - round(e["start"] * C.FPS)
        if frames < 1:
            continue
        jobs.append((n, e, frames))

    def work(job):
        n, e, frames = job
        kind, src, ov = _draw(e, cat, size, wd, n)
        seg = os.path.join(wd, f"s{n:04d}.mp4")
        if kind == "broll":
            try:
                return video.broll_segment(src, ov, frames, size[0], size[1], seg)
            except RuntimeError as err:
                print(f"[render] b-roll failed, using title card: {err}")
                p = visuals.title_card(os.path.join(wd, f"v{n:04d}.jpg"), size[0], size[1], cat, e["heading"])
                return video.image_segment(p, frames, seg)
        return video.image_segment(src, frames, seg)

    with ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 2) // 2)) as ex:
        segs = list(ex.map(work, jobs))
    return video.concat(segs, out)


def _music(store, wd):
    try:
        keys = [k for k in store.list(C.MUSIC_PREFIX + "/") if k.lower().endswith((".mp3", ".m4a", ".wav"))]
    except Exception:
        keys = []
    if not keys:
        return None
    k = keys[dt.date.today().toordinal() % len(keys)]
    p = os.path.join(wd, "music" + os.path.splitext(k)[1])
    store.download(k, p)
    return p


def _ts(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def render_long(script, wd, music=None):
    cat, secs = script["category"], script["sections"]
    tr, events, chapters = Track(), [], []
    total = len(secs)
    for i, sec in enumerate(secs):
        t0 = tr.t
        chapters.append((t0, sec["heading"]))
        times = [tr.say(s) for s in tts.sentences(sec["narration"])]
        tr.pause(PAUSE_SECTION)
        first = i == 0
        ch = script.get("challenge")
        events += _plan_section(cat, sec, times, t0, tr.t, i + 1, total, False,
                                title_text=re.sub(r"^Day \d+/\d+:\s*", "", script["title"]) if first else None,
                                kicker=(ch["name"] if ch else "Today") if first else f"Part {i + 1}")
    t_end = tr.t
    tr.pause(3.5)
    ch = script.get("challenge")
    if ch and ch.get("next_title"):
        line1, line2 = f"Tomorrow, Day {ch['day'] + 1}: {ch['next_title']}", "Subscribe so you don't miss it"
    elif ch:
        line1, line2 = f"You finished {ch['name']}!", "Subscribe for what's next"
    else:
        line1, line2 = "Thanks for watching.", "Subscribe for daily Cloud & DevOps"
    events.append({"kind": "end", "line1": line1, "line2": line2, "start": t_end, "end": tr.t})
    wav = tr.write(os.path.join(wd, "long.wav"))
    silent = _render_events(events, cat, LONG, os.path.join(wd, "long_seg"), os.path.join(wd, "long_v.mp4"))
    out = video.final_mux(silent, wav, os.path.join(wd, "long.mp4"), music=music)
    captions.write_srt(tr.cues, os.path.join(wd, "long.srt"))
    return out, chapters


def render_short(script, wd, music=None):
    cat, sh = script["category"], script["short"]
    tr = Track()
    sents = tts.sentences(sh["narration"])
    times = [tr.say(s) for s in sents]
    t_end = tr.t
    tr.pause(0.4)
    sec = {"heading": sh.get("title") or script["title"], "bullets": sh.get("bullets") or [], "code": sh.get("code")}
    body = times[:-1] if len(times) > 2 else times
    events = _plan_section(cat, sec, body, 0.0, body[-1][1] + PAUSE_SENT, 1, 1, True, title_text=sh["hook"])
    for e in events:
        e.pop("counter", None)
        e.pop("broll", None)          # Shorts stay on clean, readable cards
    if len(times) > 2:
        events.append({"kind": "end", "line1": sh.get("title") or script["title"], "line2": "Full video on the channel",
                       "start": events[-1]["end"], "end": tr.t})
    else:
        events[-1]["end"] = tr.t
    wav = tr.write(os.path.join(wd, "short.wav"))
    ass = captions.write_ass(tr.cues, os.path.join(wd, "short.ass"))
    silent = _render_events(events, cat, SHORT, os.path.join(wd, "short_seg"), os.path.join(wd, "short_v.mp4"))
    out = video.final_mux(silent, wav, os.path.join(wd, "short.mp4"), ass=ass, music=music, music_volume=0.05)
    if t_end > 170:
        print(f"[render] WARNING: Short is {t_end:.0f}s; Shorts must be 3 minutes or less")
    return out


def build_metadata(script, chapters, long_dur, short_dur, used_pexels):
    chap = "\n".join(f"{_ts(t)} {h}" for t, h in chapters) if len(chapters) >= 3 else ""
    footer = ("\n\nMade with AI assistance: the script is AI-written and technically reviewed, and the narration voice is AI-generated."
              + ("\nStock footage: Pexels." if used_pexels else ""))
    tags = [t.strip().lstrip("#") for t in script.get("tags", []) if t.strip()]
    ch = script.get("challenge")
    head = ""
    if ch:
        head = (f"Day {ch['day']} of {ch['total']} - {ch['name']}\n"
                + (f"Today's task: {ch['task']}\n" if ch.get("task") else "")
                + f"Finished it? Comment \"Day {ch['day']} done\" below.\n\n")
    long_desc = head + script["description"].strip() + ("\n\nChapters\n" + chap if chap else "") + footer
    sh = script["short"]
    short_title = (sh.get("title") or script["title"])[:90]
    if "#shorts" not in short_title.lower():
        short_title = f"{short_title} #Shorts"
    if ch:
        tags = list(dict.fromkeys(tags + ["100daysofcloud", "100daysofdevops", "cloud computing", "devops"]))[:20]
    return {
        "challenge": ch,
        "long": {"title": script["title"][:100], "description": long_desc[:4900], "tags": tags,
                 "duration_s": round(long_dur, 1)},
        "short": {"title": short_title[:100],
                  "description": (sh.get("hook", "") + "\n\nFull video on the channel." + footer)[:4900],
                  "tags": tags[:8] + ["shorts"], "duration_s": round(short_dur, 1)},
    }


def run():
    store = Store()
    wd = os.path.join(C.WORK_DIR, C.RUN_ID)
    shutil.rmtree(wd, ignore_errors=True)
    os.makedirs(wd)
    script = store.get_json(run_key("script.json"))     # the version you approved (and maybe edited)
    print(f"[render] {script['title']}")
    ch = script.get("challenge")
    visuals.DAY_BADGE = f"DAY {ch['day']} / {ch['total']}" if ch else None
    music = _music(store, wd)
    long_mp4, chapters = render_long(script, wd, music)
    short_mp4 = render_short(script, wd, music)
    thumb = visuals.thumbnail(os.path.join(wd, "thumb.jpg"), script["category"], script["thumbnail_text"],
                              day=ch["day"] if ch else None, total=ch["total"] if ch else None)
    used_pexels = any(f.startswith("broll_") for f in os.listdir(os.path.join(wd, "long_seg")))
    meta = build_metadata(script, chapters, video.duration(long_mp4), video.duration(short_mp4), used_pexels)
    for path, name, ct in [(long_mp4, "long.mp4", "video/mp4"), (short_mp4, "short.mp4", "video/mp4"),
                           (thumb, "thumb.jpg", "image/jpeg"), (os.path.join(wd, "long.srt"), "long.srt", "text/plain")]:
        store.upload(path, run_key(f"out/{name}"), ct)
    store.put_json(run_key("out/metadata.json"), meta)
    print(f"[render] done: long {meta['long']['duration_s']}s, short {meta['short']['duration_s']}s")
