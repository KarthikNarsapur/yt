"""ffmpeg helpers. Segments are encoded fast (ultrafast) and the final pass encodes once at -preset veryfast."""
import os
import subprocess

from . import config as C


def _run(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args)[:300]}\n{r.stderr[-2000:]}")


SEG = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", "-pix_fmt", "yuv420p"]


def image_segment(img, frames, out):
    _run(["-loop", "1", "-framerate", str(C.FPS), "-i", img, "-frames:v", str(frames), *SEG, "-r", str(C.FPS), out])
    return out


def broll_segment(clip, overlay_png, frames, w, h, out):
    vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={C.FPS},"
          f"eq=brightness=-0.10:saturation=0.85,setsar=1[b];[b][1:v]overlay=0:0[v]")
    _run(["-stream_loop", "-1", "-i", clip, "-i", overlay_png, "-filter_complex", vf, "-map", "[v]",
          "-frames:v", str(frames), "-an", *SEG, out])
    return out


def concat(segments, out):
    lst = out + ".txt"
    with open(lst, "w") as f:
        for s in segments:
            f.write(f"file '{os.path.abspath(s)}'\n")
    _run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])
    return out


def final_mux(video, wav, out, ass=None, music=None, music_volume=0.07):
    args = ["-i", video, "-i", wav]
    afilter = None
    if music:
        args += ["-stream_loop", "-1", "-i", music]
        afilter = (f"[2:a]volume={music_volume},afade=t=in:d=2[m];"
                   f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    vf = f"ass={ass}" if ass else "null"
    if afilter:
        args += ["-filter_complex", f"[0:v]{vf}[v];{afilter}", "-map", "[v]", "-map", "[a]"]
    else:
        args += ["-vf", vf, "-map", "0:v", "-map", "1:a"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", out]
    _run(args)
    return out


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)
