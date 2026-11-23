"""Stage 1: pick today's topic (challenge day first), write the long-video + Short script,
then run an automatic quality gate instead of a human approval:

  1. generate   - Claude (your Pro subscription) writes the whole script in one pass
                  (or the local Ollama model, section by section, as a fallback)
  2. validate   - code checks: bash -n, YAML/JSON/HCL/Python parsing, lengths, formatting
  3. review     - a second Claude pass acts as a senior engineer: fixes wrong commands/flags/facts
  4. validate   - again; if it still fails, regenerate once, otherwise the run fails and the
                  topic (or challenge day) is retried tomorrow
"""
import ast
import json
import os
import re
import subprocess
import tempfile

import yaml

from . import config as C
from . import llm
from .storage import Store, Topics, run_key

SYSTEM = (
    "You are the scriptwriter for '{channel}', an English YouTube channel teaching Linux, AWS, Azure, "
    "Google Cloud and DevOps tools to working engineers, students and job seekers in India and worldwide. "
    "Style: clear, practical, friendly, confident; no hype, no filler, no fake statistics, no made-up prices or limits. "
    "Explain the 'why' before the 'how' and use real production examples. Only use commands, flags and service "
    "names that you are certain exist today; if unsure, explain the concept instead of inventing syntax. "
    "Write narration for the ear: short sentences, no markdown, no emojis, no URLs, no code read out symbol by symbol. "
    "Never recommend insecure shortcuts (chmod 777, disabling SELinux/firewalls, hard-coded keys) except to warn against them."
)

CODE = {"type": "object", "properties": {"lang": {"type": "string"}, "content": {"type": "string"}},
        "required": ["lang", "content"]}
SECTION = {"type": "object", "properties": {
    "heading": {"type": "string"}, "narration": {"type": "string"},
    "bullets": {"type": "array", "items": {"type": "string"}}, "code": CODE, "broll": {"type": "string"}},
    "required": ["heading", "narration", "bullets", "code", "broll"]}
SHORT = {"type": "object", "properties": {
    "title": {"type": "string"}, "hook": {"type": "string"}, "narration": {"type": "string"},
    "bullets": {"type": "array", "items": {"type": "string"}}, "code": CODE},
    "required": ["title", "hook", "narration", "bullets", "code"]}
FULL_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "thumbnail_text": {"type": "string"}, "description": {"type": "string"},
    "tags": {"type": "array", "items": {"type": "string"}},
    "sections": {"type": "array", "items": SECTION}, "short": SHORT},
    "required": ["title", "thumbnail_text", "description", "tags", "sections", "short"]}
REVIEW_SCHEMA = {"type": "object", "properties": {
    "issues_found": {"type": "array", "items": {"type": "string"}}, "script": FULL_SCHEMA},
    "required": ["issues_found", "script"]}

# Ollama (small model) works better section by section
OUTLINE_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "thumbnail_text": {"type": "string"},
    "sections": {"type": "array", "items": {"type": "object", "properties": {
        "heading": {"type": "string"}, "goal": {"type": "string"}, "needs_code": {"type": "boolean"}},
        "required": ["heading", "goal", "needs_code"]}}},
    "required": ["title", "thumbnail_text", "sections"]}
SECTION_ONLY = {"type": "object", "properties": {k: SECTION["properties"][k] for k in ("narration", "bullets", "code", "broll")},
                "required": ["narration", "bullets", "code", "broll"]}
META_SCHEMA = {"type": "object", "properties": {
    "description": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "short": SHORT},
    "required": ["description", "tags", "short"]}

CTA = "Full video on the channel."


def _words(s):
    return len(re.findall(r"\w+", s or ""))


# ---------------------------------------------------------------- prompt context
def context(topic, topics):
    label = C.CATEGORY_LABEL.get(topic["category"], topic["category"].upper())
    lines = [f"Category: {label}", f"Topic: {topic['topic']}"]
    rules = []
    if topic.get("challenge"):
        day, total, name = int(topic["day"]), int(topic["total"]), topic["challenge_name"]
        prev, nxt = topics.find(topic["challenge"], day - 1), topics.find(topic["challenge"], day + 1)
        lines.append(f"This is Day {day} of {total} in the '{name}' series. Viewers follow along every day.")
        if prev:
            lines.append(f"Yesterday (Day {day - 1}) was: {prev['topic']}")
        if nxt:
            lines.append(f"Tomorrow (Day {day + 1}) is: {nxt['topic']}")
        if topic.get("task"):
            lines.append(f"Today's hands-on task for viewers: {topic['task']}")
        rules = [
            f"The first sentence says this is Day {day} of {name}. Connect to yesterday in one sentence if there was one.",
            f"The LAST section is titled 'Your Day {day} task': walk through the task step by step, say how to check it "
            f"worked, and ask viewers to comment 'Day {day} done' when they finish.",
            "The very last sentence teases tomorrow's topic." if nxt else "The very last sentence congratulates viewers on finishing the challenge.",
            f"The Short mentions 'Day {day} of {total}' once.",
            "Do NOT put 'Day N' in the title; it is added automatically.",
        ]
    mine = (topic.get("my_points") or "").strip()
    if mine:
        lines.append(f"The creator's own experience - weave this in naturally, in the first person:\n{mine}")
    return "\n".join(lines), rules


def _spec(rules):
    secs = C.LONG_SECTIONS
    base = [
        f"Long video: exactly {secs} sections, each about {C.SECTION_WORDS} words of narration "
        f"(total {secs * C.SECTION_WORDS - 150}-{secs * C.SECTION_WORDS + 150} words, about 9-10 minutes).",
        "Section 1 opens with a hook and says what the viewer will be able to do by the end.",
        "Each section: heading (max 6 words), narration, 2-4 on-screen bullets (max 7 words each), "
        "code (lang + content, max 12 lines, max 60 characters per line; use empty strings when a section has no code), "
        "broll (2-4 word stock-footage search like 'server room', or empty string).",
        "Use code in 3-5 sections where a real command or config genuinely helps. Code must be correct and runnable.",
        "title: max 65 characters, specific and searchable, no clickbait, no ALL CAPS.",
        "thumbnail_text: 2-4 punchy words. description: 2 short paragraphs, no links, no timestamps, no hashtags. "
        "tags: 10-15.",
        f"short: a standalone vertical Short of about {C.SHORT_WORDS} words (45-50 s) teaching the single most useful idea. "
        f"title max 60 chars; hook max 8 words; narration starts with the hook and ends with '{CTA}'; "
        "3 bullets max 6 words; code: a tiny snippet (max 4 lines) or empty strings.",
    ]
    return "\n".join(f"- {r}" for r in base + rules)


# ---------------------------------------------------------------- generation
def generate_claude(ctx, rules):
    system = SYSTEM.format(channel=C.CHANNEL_NAME)
    return llm.chat_json(system, f"{ctx}\n\nWrite the full script. Requirements:\n{_spec(rules)}\n\nReturn only JSON.",
                         FULL_SCHEMA)


def generate_ollama(ctx, rules):
    system = SYSTEM.format(channel=C.CHANNEL_NAME)
    extra = "\n".join(f"- {r}" for r in rules)
    outline = llm.chat_json(system, (
        f"{ctx}\n{extra}\nPlan a 9-10 minute video: a title (max 65 chars), thumbnail_text (2-4 words) and exactly "
        f"{C.LONG_SECTIONS} sections. Mark needs_code=true only where a command or config genuinely helps."), OUTLINE_SCHEMA)
    plan = outline["sections"][:C.LONG_SECTIONS]
    plan_txt = "\n".join(f"{i + 1}. {s['heading']} - {s['goal']}" for i, s in enumerate(plan))
    sections = []
    for i, s in enumerate(plan):
        prev = sections[-1]["narration"][-400:] if sections else "(this is the opening)"
        out = llm.chat_json(system, (
            f"{ctx}\n{extra}\nTitle: {outline['title']}\nOutline:\n{plan_txt}\n\nWrite section {i + 1}: '{s['heading']}' "
            f"(goal: {s['goal']}). End of previous section: ...{prev}\nnarration: about {C.SECTION_WORDS} words, continuing "
            f"naturally. bullets: 2-4, max 7 words. code: {'a correct snippet, max 12 lines' if s['needs_code'] else 'empty strings'}. "
            f"broll: 2-4 word stock search or empty string."), SECTION_ONLY)
        if not s["needs_code"]:
            out["code"] = {"lang": "", "content": ""}
        sections.append({"heading": s["heading"], **out})
    summary = "\n".join(f"- {s['heading']}: {' '.join(s['bullets'])}" for s in sections)
    meta = llm.chat_json(system, (
        f"{ctx}\n{extra}\nTitle: {outline['title']}\nSections:\n{summary}\n\ndescription: 2 short paragraphs, no links. "
        f"tags: 10-15. short: standalone Short, about {C.SHORT_WORDS} words, hook max 8 words, narration starts with the hook "
        f"and ends with '{CTA}', 3 bullets max 6 words, code tiny or empty strings."), META_SCHEMA)
    return {"title": outline["title"], "thumbnail_text": outline["thumbnail_text"], "sections": sections, **meta}


def review(script, problems, ctx, rules):
    system = ("You are a senior cloud and DevOps engineer and a strict technical editor for a YouTube channel. "
              "You fix scripts so that every command, flag, file path, service name, limit and claim is correct and current, "
              "and nothing unsafe is recommended. You keep the structure, tone and length.")
    probs = "\n".join(f"- {p}" for p in problems) or "- none"
    user = (f"{ctx}\n\nRequirements the script must meet:\n{_spec(rules)}\n\nAutomatic checks found these problems:\n{probs}\n\n"
            f"Review this script. List every issue you find in issues_found (empty list if none), then return the full "
            f"corrected script in 'script' (same JSON shape).\n\n{json.dumps(script, ensure_ascii=False)}")
    return llm.chat_json(system, user, REVIEW_SCHEMA)


# ---------------------------------------------------------------- checks
def _code(c):
    if not c or not (c.get("content") or "").strip():
        return None
    return {"lang": (c.get("lang") or "text").strip().lower(), "content": c["content"].rstrip()}


def normalize(s):
    s = json.loads(json.dumps(s))
    for sec in s.get("sections", []):
        sec["heading"] = sec.get("heading", "").strip()
        sec["narration"] = re.sub(r"\s+", " ", sec.get("narration", "")).strip()
        sec["bullets"] = [b.strip().rstrip(".") for b in sec.get("bullets", []) if b.strip()][:4]
        sec["code"] = _code(sec.get("code"))
        sec["broll"] = (sec.get("broll") or "").strip() or None
    sh = s.get("short", {})
    sh["narration"] = re.sub(r"\s+", " ", sh.get("narration", "")).strip()
    if sh["narration"] and not sh["narration"].endswith(CTA):
        sh["narration"] = sh["narration"].rstrip() + " " + CTA
    sh["bullets"] = [b.strip().rstrip(".") for b in sh.get("bullets", []) if b.strip()][:3]
    sh["code"] = _code(sh.get("code"))
    s["tags"] = [t.strip().lstrip("#") for t in s.get("tags", []) if t.strip()][:15]
    s["title"] = re.sub(r"^\s*day\s*\d+\s*(/\s*\d+)?\s*[:\-–]\s*", "", s.get("title", ""), flags=re.I).strip()
    return s


def check_code(lang, content):
    """Return an error string, or None if the snippet parses."""
    lang = {"sh": "bash", "shell": "bash", "console": "bash", "zsh": "bash", "yml": "yaml",
            "terraform": "hcl", "tf": "hcl", "py": "python"}.get(lang, lang)
    lines = content.split("\n")
    if len(lines) > 14:
        return f"{len(lines)} lines (max 12)"
    if max(len(l) for l in lines) > 72:
        return "a line is longer than 72 characters (won't fit on the slide)"
    try:
        if lang == "bash":
            body = "\n".join(re.sub(r"^\s*\$ ", "", l) for l in lines)
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
                f.write(body)
            r = subprocess.run(["bash", "-n", f.name], capture_output=True, text=True)
            os.unlink(f.name)
            if r.returncode:
                return "bash syntax: " + r.stderr.strip().split("\n")[-1][:200]
        elif lang == "yaml":
            list(yaml.safe_load_all(content))
        elif lang == "json":
            json.loads(content)
        elif lang == "python":
            ast.parse(content)
        elif lang == "hcl":
            try:
                import hcl2
                hcl2.loads(content)
            except ImportError:
                pass
    except Exception as e:
        return f"{lang} does not parse: {str(e)[:200]}"
    return None


def validate(s, min_total_words):
    p = []
    secs = s.get("sections", [])
    if not 6 <= len(secs) <= 10:
        p.append(f"long video has {len(secs)} sections (need {C.LONG_SECTIONS})")
    total = sum(_words(x["narration"]) for x in secs)
    if total < min_total_words:
        p.append(f"long narration is only {total} words (need at least {min_total_words})")
    if len(s.get("title", "")) > 75:
        p.append("title longer than 75 characters")
    for i, x in enumerate(secs, 1):
        if _words(x["narration"]) < 50:
            p.append(f"section {i} narration is too short")
        if re.search(r"https?://|```|\*\*|^#", x["narration"]):
            p.append(f"section {i} narration contains markdown or a URL")
        if not x["bullets"]:
            p.append(f"section {i} has no bullets")
        if x["code"]:
            err = check_code(x["code"]["lang"], x["code"]["content"])
            if err:
                p.append(f"section {i} code: {err}")
    sh = s.get("short", {})
    w = _words(sh.get("narration"))
    if not 60 <= w <= 180:
        p.append(f"Short narration is {w} words (need 90-150)")
    if sh.get("code"):
        err = check_code(sh["code"]["lang"], sh["code"]["content"])
        if err:
            p.append(f"Short code: {err}")
    return p


# ---------------------------------------------------------------- main
def produce(topic, topics):
    ctx, rules = context(topic, topics)
    gen = generate_claude if C.LLM_PROVIDER == "claude" else generate_ollama
    min_words = int(C.LONG_SECTIONS * C.SECTION_WORDS * (0.7 if C.LLM_PROVIDER == "claude" else 0.45))
    problems = []
    for attempt in range(2):
        s = normalize(gen(ctx, rules))
        problems = validate(s, min_words)
        notes = []
        if C.LLM_PROVIDER == "claude" or problems:      # Claude always gets a technical review pass
            rev = review(s, problems, ctx, rules)
            notes = rev.get("issues_found", [])
            s = normalize(rev["script"])
            problems = validate(s, min_words)
        print(f"[script] attempt {attempt + 1}: review fixed {len(notes)} issue(s); {len(problems)} problem(s) left")
        if not problems:
            s["review_notes"] = notes
            return s
        for pr in problems:
            print(f"   - {pr}")
    raise RuntimeError("Quality gate failed: " + "; ".join(problems))


def finalize(s, topic, topics=None):
    s.update({"topic_id": topic["topic_id"], "category": topic["category"], "topic": topic["topic"],
              "has_my_points": bool((topic.get("my_points") or "").strip()), "provider": C.LLM_PROVIDER})
    if topic.get("challenge"):
        day, total = int(topic["day"]), int(topic["total"])
        s["challenge"] = {"slug": topic["challenge"], "name": topic["challenge_name"], "day": day, "total": total,
                          "task": topic.get("task", "")}
        nxt = topics.find(topic["challenge"], day + 1) if topics else None
        s["challenge"]["next_title"] = nxt["topic"] if nxt else ""
        s["title"] = f"Day {day}/{total}: {s['title']}"
        s["short"]["title"] = f"Day {day}/{total}: {s['short']['title']}"
    s["title"] = s["title"][:100]
    words = sum(_words(x["narration"]) for x in s["sections"])
    s["stats"] = {"long_words": words, "long_minutes_est": round(words / 150, 1),
                  "short_words": _words(s["short"]["narration"])}
    return s


def run():
    store, topics = Store(), Topics()
    topic = topics.pick_next()
    label = f"Day {topic['day']}/{topic['total']} " if topic.get("challenge") else ""
    print(f"[script] {label}[{topic['category']}] {topic['topic']} via {C.LLM_PROVIDER}")
    topics.set_status(topic["topic_id"], "IN_PROGRESS", run_id=C.RUN_ID)
    # written first so a failed run can always put the topic back in the queue
    store.put_json(run_key("run.json"), {"run_id": C.RUN_ID, "topic_id": topic["topic_id"],
                                         "category": topic["category"], "topic": topic["topic"]})
    try:
        llm.start(store)
        script = finalize(produce(topic, topics), topic, topics)
    except Exception:
        topics.set_status(topic["topic_id"], "PENDING")
        raise
    store.put_json(run_key("script.json"), script)
    print(f"[script] done: {script['title']} ({script['stats']})")
