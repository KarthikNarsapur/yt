"""Review Lambda.

Invoked two ways:
  1. By Step Functions ({"action": ...}) to email you, record the approval token and update topics.
  2. By API Gateway (HTTP API) to serve the mobile review page and the download page.
Only boto3 + stdlib, so no packaging step is needed.
"""
import base64
import hmac
import html
import json
import os
import secrets
import time
import urllib.parse

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "ap-south-1")
# Regional endpoint + SigV4: the global bucket.s3.amazonaws.com name can route new buckets to us-east-1,
# which breaks pre-signed links ("the region 'ap-south-1' is wrong; expecting 'us-east-1'").
S3 = boto3.client("s3", region_name=REGION, endpoint_url=f"https://s3.{REGION}.amazonaws.com",
                  config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
SFN = boto3.client("stepfunctions")
SNS = boto3.client("sns")
DDB = boto3.resource("dynamodb")

BUCKET = os.environ["BUCKET"]
RUNS = DDB.Table(os.environ["RUNS_TABLE"])
TOPICS = DDB.Table(os.environ["TOPICS_TABLE"])
TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
API_URL = os.environ["API_URL"].rstrip("/")
PUBLISH_MODE = os.environ.get("PUBLISH_MODE", "none")


# ------------------------------------------------------------------ helpers
def _get_json(key):
    return json.loads(S3.get_object(Bucket=BUCKET, Key=key)["Body"].read())


def _run(run_id):
    return RUNS.get_item(Key={"run_id": run_id}).get("Item")


def _mail(subject, body):
    SNS.publish(TopicArn=TOPIC_ARN, Subject=subject[:99], Message=body)


def _page(title, body, status=200):
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0b1020;color:#e8ecf5;line-height:1.5}}
main{{max-width:760px;margin:0 auto;padding:18px}} h1{{font-size:1.35rem}} h2{{font-size:1.05rem;margin-top:1.6rem}}
.card{{background:#141b33;border-radius:12px;padding:14px;margin:12px 0}} .muted{{color:#97a3c0;font-size:.9rem}}
.warn{{background:#4a2f05;border:1px solid #f5a524;padding:12px;border-radius:10px}}
pre{{background:#1a1c22;padding:12px;border-radius:8px;overflow-x:auto;font-size:.85rem}}
textarea{{width:100%;box-sizing:border-box;background:#0f1428;color:#e8ecf5;border:1px solid #2b3560;border-radius:8px;padding:10px;font-family:ui-monospace,monospace;font-size:.85rem}}
button,a.btn{{display:inline-block;border:0;border-radius:10px;padding:12px 18px;font-size:1rem;font-weight:600;margin:6px 6px 6px 0;text-decoration:none;cursor:pointer}}
.ok{{background:#34a853;color:#fff}} .no{{background:#3a4366;color:#fff}} a.btn{{background:#2f8cff;color:#fff}}
ul{{padding-left:1.2rem}}
</style></head><body><main>{body}</main></body></html>"""
    return {"statusCode": status, "headers": {"content-type": "text/html; charset=utf-8"}, "body": doc}


def _authorised(run, key):
    return run and key and hmac.compare_digest(run.get("key", ""), key)


# ------------------------------------------------------------------ Step Functions actions
def request_approval(ev):
    run_id = ev["run_id"]
    script = _get_json(f"runs/{run_id}/script.json")
    key = secrets.token_urlsafe(24)
    RUNS.put_item(Item={"run_id": run_id, "token": ev["token"], "key": key, "status": "WAITING",
                        "title": script["title"], "ttl": int(time.time()) + 14 * 86400})
    link = f"{API_URL}/review/{run_id}?k={key}"
    stats = script.get("stats", {})
    warn = "" if script.get("has_my_points") else (
        "\n!! This topic has no points of your own yet. Add your experience before approving -"
        "\n   YouTube won't monetize mass-produced AI content.\n")
    _mail(f"Review today's video: {script['title']}",
          f"[{script['category'].upper()}] {script['title']}\n"
          f"Long: ~{stats.get('long_minutes_est', '?')} min, Short: {stats.get('short_words', '?')} words\n{warn}\n"
          f"Review, edit and approve (link valid ~20 hours):\n{link}\n")
    return {"ok": True}


def _ensure_run(run_id):
    """Auto-approved runs never went through request_approval: create the run record + page key now."""
    run = _run(run_id)
    if run:
        return run
    script = _get_json(f"runs/{run_id}/script.json")
    run = {"run_id": run_id, "key": secrets.token_urlsafe(24), "status": "AUTO_APPROVED",
           "title": script["title"], "ttl": int(time.time()) + 14 * 86400}
    RUNS.put_item(Item=run)
    return run


def notify_ready(ev):
    run_id = ev["run_id"]
    run = _ensure_run(run_id)
    link = f"{API_URL}/ready/{run_id}?k={run['key']}"
    how = {"youtube": "Uploaded to YouTube and scheduled (Short 12:30, long video 18:30 by default).",
           "webhook": "Sent to your publishing webhook."}.get(
        PUBLISH_MODE, "Download both videos and upload them in the YouTube Studio app (title/description are on the page).")
    notes = ""
    try:
        s = _get_json(f"runs/{run_id}/script.json")
        if s.get("review_notes"):
            notes = "\nThe AI reviewer fixed:\n" + "\n".join(f"- {n}" for n in s["review_notes"][:10]) + "\n"
    except Exception:
        pass
    _mail(f"Ready: {run['title']}", f"{how}\n{notes}\n{link}\n")
    return {"ok": True}


def finish(ev):
    run_id, outcome = ev["run_id"], ev["outcome"]          # DONE | PENDING | SKIPPED
    try:
        info = _get_json(f"runs/{run_id}/run.json")
        TOPICS.update_item(Key={"topic_id": info["topic_id"]},
                           UpdateExpression="SET #s = :s, updated_at = :u, last_run = :r",
                           ExpressionAttributeNames={"#s": "status"},
                           ExpressionAttributeValues={":s": outcome, ":u": int(time.time()), ":r": run_id})
    except S3.exceptions.NoSuchKey:
        pass
    if _run(run_id):
        RUNS.update_item(Key={"run_id": run_id}, UpdateExpression="SET #s = :s",
                         ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": outcome})
    return {"ok": True}


def notify_failure(ev):
    err = ev.get("error") or {}
    _mail(f"Pipeline failed: {ev.get('run_id')}",
          f"Run {ev.get('run_id')} failed.\n\n{err.get('Error', '')}\n{str(err.get('Cause', ''))[:3000]}\n\n"
          f"Check the Step Functions console and the /ecs/yt-pipeline log group.")
    return {"ok": True}


# ------------------------------------------------------------------ HTTP pages
def review_get(run_id, run, key):
    s = _get_json(f"runs/{run_id}/script.json")
    if run.get("status") != "WAITING":
        return _page("Already decided", f"<h1>Already {html.escape(run.get('status', '').lower())}</h1>")
    parts = [f"<p class='muted'>{html.escape(s['category'].upper())} · ~{s.get('stats', {}).get('long_minutes_est', '?')} min</p>",
             f"<h1>{html.escape(s['title'])}</h1>"]
    if not s.get("has_my_points"):
        parts.append("<div class='warn'><b>No points of your own for this topic.</b> Add your real experience, an example "
                     "from work, or a mistake you've seen, into the narration below. That is what keeps the channel "
                     "monetizable.</div>")
    parts.append("<div class='warn'>Check every command and code block - small local models can get flags wrong.</div>")
    for i, sec in enumerate(s["sections"], 1):
        code = (f"<pre>{html.escape(sec['code']['content'])}</pre>" if sec.get("code") else "")
        bullets = "".join(f"<li>{html.escape(b)}</li>" for b in sec.get("bullets", []))
        parts.append(f"<div class='card'><h2>{i}. {html.escape(sec['heading'])}</h2><ul>{bullets}</ul>"
                     f"<p>{html.escape(sec['narration'])}</p>{code}</div>")
    sh = s["short"]
    sc = f"<pre>{html.escape(sh['code']['content'])}</pre>" if sh.get("code") else ""
    parts.append(f"<div class='card'><h2>Short: {html.escape(sh['title'])}</h2><p><b>{html.escape(sh['hook'])}</b></p>"
                 f"<p>{html.escape(sh['narration'])}</p>{sc}</div>")
    q = urllib.parse.quote(key)
    parts.append(f"""<form method="post" action="/review/{run_id}?k={q}">
<h2>Edit (optional)</h2><p class="muted">Change narration, bullets or code in the JSON, then approve.</p>
<textarea name="script" rows="18">{html.escape(json.dumps(s, indent=2, ensure_ascii=False))}</textarea>
<p><button class="ok" name="action" value="approve">Approve &amp; render</button>
<button class="no" name="action" value="reject">Reject (topic goes back in the queue)</button></p></form>""")
    return _page("Review", "".join(parts))


def review_post(run_id, run, body):
    if run.get("status") != "WAITING":
        return _page("Already decided", "<h1>This run was already decided.</h1>")
    form = urllib.parse.parse_qs(body)
    action = (form.get("action") or [""])[0]
    if action == "approve":
        try:
            s = json.loads((form.get("script") or ["{}"])[0])
            assert s.get("title") and s.get("sections") and s.get("short")
        except Exception as e:
            return _page("Invalid JSON", f"<h1>That JSON didn't parse</h1><pre>{html.escape(str(e))}</pre>"
                                         f"<p>Go back and fix it.</p>", 400)
        S3.put_object(Bucket=BUCKET, Key=f"runs/{run_id}/script.json",
                      Body=json.dumps(s, indent=2, ensure_ascii=False).encode(), ContentType="application/json")
        SFN.send_task_success(taskToken=run["token"], output=json.dumps({"approved": True}))
        RUNS.update_item(Key={"run_id": run_id}, UpdateExpression="SET #s = :s",
                         ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "APPROVED"})
        return _page("Approved", "<h1>Approved ✅</h1><p>Rendering now (about 15-30 minutes). You'll get an email when "
                                 "the videos are ready.</p>")
    if action == "reject":
        SFN.send_task_success(taskToken=run["token"], output=json.dumps({"approved": False}))
        RUNS.update_item(Key={"run_id": run_id}, UpdateExpression="SET #s = :s",
                         ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": "REJECTED"})
        return _page("Rejected", "<h1>Rejected</h1><p>The topic goes back into the queue. Tip: add your own points to "
                                 "it in DynamoDB so the next script is better.</p>")
    return _page("Unknown", "<h1>Unknown action</h1>", 400)


def ready_get(run_id):
    meta = _get_json(f"runs/{run_id}/out/metadata.json")

    def url(name):
        return S3.generate_presigned_url("get_object", ExpiresIn=3600,
                                         Params={"Bucket": BUCKET, "Key": f"runs/{run_id}/out/{name}"})

    def block(label, m):
        return (f"<div class='card'><h2>{label} · {m['duration_s']:.0f}s</h2>"
                f"<p class='muted'>Title</p><textarea rows='2'>{html.escape(m['title'])}</textarea>"
                f"<p class='muted'>Description</p><textarea rows='8'>{html.escape(m['description'])}</textarea>"
                f"<p class='muted'>Tags</p><textarea rows='2'>{html.escape(', '.join(m['tags']))}</textarea></div>")

    pub = ""
    try:
        p = _get_json(f"runs/{run_id}/out/published.json")
        if p.get("mode") == "youtube":
            pub = (f"<div class='card'>Scheduled: <a href='https://youtu.be/{p['long_id']}'>long video</a> · "
                   f"<a href='https://youtube.com/shorts/{p['short_id']}'>Short</a></div>")
        else:
            pub = "<div class='card'>Sent to your publishing webhook.</div>"
    except Exception:
        pass
    body = (f"<h1>{html.escape(meta['long']['title'])}</h1>{pub}"
            f"<p><a class='btn' href='{url('long.mp4')}'>Long video</a><a class='btn' href='{url('short.mp4')}'>Short</a>"
            f"<a class='btn' href='{url('thumb.jpg')}'>Thumbnail</a><a class='btn' href='{url('long.srt')}'>Captions (.srt)</a></p>"
            f"<p class='muted'>Links expire in 1 hour; reload this page for fresh ones.</p>"
            + block("Long video", meta["long"]) + block("Short", meta["short"]))
    return _page("Ready", body)


def http(ev):
    method = ev["requestContext"]["http"]["method"]
    path = ev.get("rawPath", "")
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2:
        return _page("Not found", "<h1>Not found</h1>", 404)
    kind, run_id = parts
    key = (ev.get("queryStringParameters") or {}).get("k", "")
    run = _run(run_id)
    if not _authorised(run, key):
        return _page("Forbidden", "<h1>Link invalid or expired</h1>", 403)
    body = ev.get("body") or ""
    if ev.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    if kind == "review" and method == "GET":
        return review_get(run_id, run, key)
    if kind == "review" and method == "POST":
        return review_post(run_id, run, body)
    if kind == "ready" and method == "GET":
        return ready_get(run_id)
    return _page("Not found", "<h1>Not found</h1>", 404)


ACTIONS = {"request_approval": request_approval, "notify_ready": notify_ready,
           "finish": finish, "notify_failure": notify_failure}


def lambda_handler(event, context):
    if "requestContext" in event:
        return http(event)
    return ACTIONS[event["action"]](event)
