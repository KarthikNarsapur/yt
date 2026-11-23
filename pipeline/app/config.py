"""Runtime configuration, read from environment variables.

Local mode: set LOCAL_DIR to a folder and the pipeline uses the filesystem
instead of S3/DynamoDB (topics come from topics/topics.yaml).
"""
import os

def _env(name, default=None):
    v = os.environ.get(name, default)
    if isinstance(v, str) and v.strip() in ("", "CHANGE_ME"):
        return default
    return v

RUN_ID = _env("RUN_ID", "local-run")
LOCAL_DIR = _env("LOCAL_DIR")            # if set -> local mode
BUCKET = _env("BUCKET")
TOPICS_TABLE = _env("TOPICS_TABLE")
TOPICS_FILE = _env("TOPICS_FILE", os.path.join(os.path.dirname(__file__), "..", "..", "topics", "topics.yaml"))

CHALLENGES_DIR = _env("CHALLENGES_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "challenges"))

# Script writer: "claude" (your Claude Pro/Max subscription via Claude Code) or "ollama" (local CPU model)
LLM_PROVIDER = _env("LLM_PROVIDER", "claude")
CLAUDE_MODEL = _env("CLAUDE_MODEL", "sonnet")
CLAUDE_TIMEOUT = int(_env("CLAUDE_TIMEOUT", "900"))

# LLM (Ollama, CPU) - fallback
OLLAMA_URL = _env("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_NUM_THREADS = int(_env("OLLAMA_NUM_THREADS", str(os.cpu_count() or 4)))
MODEL_CACHE_PREFIX = _env("MODEL_CACHE_PREFIX", "cache/ollama")

# Voice (Kokoro, CPU)
KOKORO_MODEL = _env("KOKORO_MODEL", "/opt/models/kokoro-v1.0.int8.onnx")
KOKORO_VOICES = _env("KOKORO_VOICES", "/opt/models/voices-v1.0.bin")
VOICE = _env("VOICE", "am_michael")
VOICE_SPEED = float(_env("VOICE_SPEED", "1.0"))

# Visuals
FPS = int(_env("FPS", "30"))
PEXELS_API_KEY = _env("PEXELS_API_KEY")   # optional: stock b-roll
CHANNEL_NAME = _env("CHANNEL_NAME", "Cloud & DevOps Daily")
FONT_SANS = _env("FONT_SANS", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD = _env("FONT_BOLD", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FONT_MONO = _env("FONT_MONO", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
MUSIC_PREFIX = _env("MUSIC_PREFIX", "assets/music")   # optional royalty-free tracks you upload

# Content targets
LONG_SECTIONS = int(_env("LONG_SECTIONS", "8"))        # ~8 sections x ~160 words = ~9-10 min
SECTION_WORDS = int(_env("SECTION_WORDS", "160"))
SHORT_WORDS = int(_env("SHORT_WORDS", "120"))          # ~45-50 s

# Publishing: none (download page) | youtube (direct API upload) | webhook (Make / Zapier / n8n ...)
PUBLISH_MODE = _env("PUBLISH_MODE", "none")
PUBLISH_WEBHOOK_URL = _env("PUBLISH_WEBHOOK_URL")
YT_OAUTH = _env("YT_OAUTH")                            # JSON: client_id, client_secret, refresh_token
PUBLISH_TZ = _env("PUBLISH_TZ", "Asia/Kolkata")
PUBLISH_TIME_LONG = _env("PUBLISH_TIME_LONG", "18:30")
PUBLISH_TIME_SHORT = _env("PUBLISH_TIME_SHORT", "12:30")
YT_CATEGORY_ID = _env("YT_CATEGORY_ID", "28")          # Science & Technology
CONTAINS_SYNTHETIC_MEDIA = _env("CONTAINS_SYNTHETIC_MEDIA", "false").lower() == "true"

WORK_DIR = _env("WORK_DIR", "/tmp/work")

CATEGORIES = ["linux", "aws", "azure", "gcp", "devops"]
CATEGORY_LABEL = {"linux": "LINUX", "aws": "AWS", "azure": "AZURE", "gcp": "GOOGLE CLOUD", "devops": "DEVOPS"}
