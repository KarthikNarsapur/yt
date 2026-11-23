"""Narration with Kokoro-82M (Apache-2.0) via ONNX Runtime on CPU."""
import re

import numpy as np

from . import config as C

SAMPLE_RATE = 24000

# Spoken forms for tech words the voice tends to mangle. Captions keep the original text.
PRONOUNCE = {
    r"\bkubectl\b": "kube control", r"\bk8s\b": "kubernetes", r"\bnginx\b": "engine x",
    r"\bYAML\b": "yammel", r"\byaml\b": "yammel", r"\bJSON\b": "jason", r"\bsudo\b": "sue doo",
    r"\bchmod\b": "change mod", r"\bchown\b": "change own", r"\bsystemctl\b": "system control",
    r"\bjournalctl\b": "journal control", r"\bGCP\b": "G C P", r"\bAWS\b": "A W S", r"\bEC2\b": "E C 2",
    r"\bS3\b": "S 3", r"\bIAM\b": "I am", r"\bVPC\b": "V P C", r"\bVNet\b": "V net", r"\bAKS\b": "A K S",
    r"\bEKS\b": "E K S", r"\bGKE\b": "G K E", r"\bCI/CD\b": "C I C D", r"\bCLI\b": "C L I", r"\bAPI\b": "A P I",
    r"\bAPIs\b": "A P eyes", r"\bSSH\b": "S S H", r"\bDNS\b": "D N S", r"\bRBAC\b": "R back", r"\bHCL\b": "H C L",
    r"\bIaC\b": "I A C", r"\bSRE\b": "S R E", r"\bVM\b": "V M", r"\bVMs\b": "V Ms", r"\bTLS\b": "T L S",
    r"\bARN\b": "A R N", r"\bRDS\b": "R D S", r"\bSQS\b": "S Q S", r"\bSNS\b": "S N S", r"\bECS\b": "E C S",
    r"\bECR\b": "E C R", r"\bGUI\b": "gooey", r"\bUbuntu\b": "oo-boon-too", r"/etc\b": "slash E T C",
    r"\bArgoCD\b": "Argo C D", r"\bPostgreSQL\b": "postgres Q L", r"\bMySQL\b": "my S Q L",
}

_kokoro = None


def _engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(C.KOKORO_MODEL, C.KOKORO_VOICES)
    return _kokoro


def spoken(text):
    for pat, rep in PRONOUNCE.items():
        text = re.sub(pat, rep, text)
    return text


def sentences(text):
    text = re.sub(r"\s+", " ", (text or "").strip())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # keep very long sentences manageable for captions and TTS
        while len(p) > 260 and ", " in p[120:]:
            cut = p.index(", ", 120) + 1
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        out.append(p)
    return out


def synth(text):
    samples, sr = _engine().create(spoken(text), voice=C.VOICE, speed=C.VOICE_SPEED, lang="en-us")
    assert sr == SAMPLE_RATE
    return np.asarray(samples, dtype=np.float32)


def silence(seconds):
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
