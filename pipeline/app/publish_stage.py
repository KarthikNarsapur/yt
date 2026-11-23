"""Stage 3: publish straight from the workflow.

PUBLISH_MODE
  youtube  Upload with the YouTube Data API (your own Google Cloud project), schedule publish times,
           add the long video to the challenge playlist. Uploads from an UNVERIFIED project are
           locked to private - pass the API audit first.
  webhook  POST the files (pre-signed links) + metadata to PUBLISH_WEBHOOK_URL, e.g. a Make, Zapier or
           n8n flow whose YouTube connection is already verified. Check that service's file-size limits.
  none     Do nothing (you download from the "ready" page).
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import requests

from . import config as C
from .storage import Store, run_key

PLAYLIST_STATE = "state/playlists.json"


def _publish_at(hhmm):
    tz = ZoneInfo(C.PUBLISH_TZ)
    h, m = map(int, hhmm.split(":"))
    now = dt.datetime.now(tz)
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= now + dt.timedelta(minutes=30):
        t += dt.timedelta(days=1)
    return t.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ YouTube API
def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    cfg = json.loads(C.YT_OAUTH or "{}")
    if not cfg.get("refresh_token"):
        raise SystemExit("YT_OAUTH is not set - run scripts/youtube_auth.py and store its output in SSM")
    creds = Credentials(None, refresh_token=cfg["refresh_token"], client_id=cfg["client_id"],
                        client_secret=cfg["client_secret"], token_uri="https://oauth2.googleapis.com/token",
                        scopes=["https://www.googleapis.com/auth/youtube.upload",
                                "https://www.googleapis.com/auth/youtube.force-ssl"])
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _upload(yt, path, meta, publish_at):
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                    "categoryId": C.YT_CATEGORY_ID, "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": C.CONTAINS_SYNTHETIC_MEDIA},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(path, chunksize=16 << 20, resumable=True, mimetype="video/mp4"))
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            print(f"[publish] {int(status.progress() * 100)}%")
    return resp["id"]


def _playlist_id(yt, store, ch):
    try:
        state = store.get_json(PLAYLIST_STATE)
    except Exception:
        state = {}
    if ch["slug"] in state:
        return state[ch["slug"]]
    pl = yt.playlists().insert(part="snippet,status", body={
        "snippet": {"title": ch["name"],
                    "description": f"{ch['name']}: one hands-on lesson a day across Linux, AWS, Azure, Google Cloud "
                                   f"and DevOps tools. Start at Day 1 and follow along."},
        "status": {"privacyStatus": "public"}}).execute()
    state[ch["slug"]] = pl["id"]
    store.put_json(PLAYLIST_STATE, state)
    return pl["id"]


def publish_youtube(store, meta, files):
    from googleapiclient.http import MediaFileUpload
    yt = _client()
    long_id = _upload(yt, files["long.mp4"], meta["long"], _publish_at(C.PUBLISH_TIME_LONG))
    print(f"[publish] long video: https://youtu.be/{long_id}")
    for what, fn in [
        ("thumbnail", lambda: yt.thumbnails().set(videoId=long_id, media_body=MediaFileUpload(
            files["thumb.jpg"], mimetype="image/jpeg")).execute()),           # needs a phone-verified channel
        ("captions", lambda: yt.captions().insert(part="snippet", body={"snippet": {
            "videoId": long_id, "language": "en", "name": "English"}}, media_body=MediaFileUpload(
            files["long.srt"], mimetype="application/octet-stream")).execute()),
    ]:
        try:
            fn()
        except Exception as e:
            print(f"[publish] {what} skipped: {e}")
    ch = meta.get("challenge")
    if ch:
        try:
            pid = _playlist_id(yt, store, ch)
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": pid,
                "resourceId": {"kind": "youtube#video", "videoId": long_id}}}).execute()
        except Exception as e:
            print(f"[publish] playlist skipped: {e}")
    short_meta = dict(meta["short"])
    short_meta["description"] = short_meta["description"].replace(
        "Full video on the channel.", f"Full video: https://youtu.be/{long_id}")
    short_id = _upload(yt, files["short.mp4"], short_meta, _publish_at(C.PUBLISH_TIME_SHORT))
    print(f"[publish] short: https://youtube.com/shorts/{short_id}")
    return {"mode": "youtube", "long_id": long_id, "short_id": short_id}


# ------------------------------------------------------------------ webhook
def publish_webhook(store, meta):
    if not C.PUBLISH_WEBHOOK_URL:
        raise SystemExit("PUBLISH_WEBHOOK_URL is not set")
    payload = {
        "run_id": C.RUN_ID,
        "challenge": meta.get("challenge"),
        "long": {**meta["long"], "video_url": store.presign(run_key("out/long.mp4")),
                 "thumbnail_url": store.presign(run_key("out/thumb.jpg")),
                 "captions_url": store.presign(run_key("out/long.srt")),
                 "publish_at": _publish_at(C.PUBLISH_TIME_LONG)},
        "short": {**meta["short"], "video_url": store.presign(run_key("out/short.mp4")),
                  "publish_at": _publish_at(C.PUBLISH_TIME_SHORT)},
    }
    r = requests.post(C.PUBLISH_WEBHOOK_URL, json=payload, timeout=60)
    r.raise_for_status()
    print(f"[publish] webhook accepted: HTTP {r.status_code}")
    return {"mode": "webhook", "status": r.status_code}


def run():
    store = Store()
    if C.PUBLISH_MODE == "none":
        print("[publish] PUBLISH_MODE=none, nothing to do")
        return
    meta = store.get_json(run_key("out/metadata.json"))
    if C.PUBLISH_MODE == "webhook":
        result = publish_webhook(store, meta)
    elif C.PUBLISH_MODE == "youtube":
        wd = os.path.join(C.WORK_DIR, C.RUN_ID, "publish")
        files = {}
        for n in ["long.mp4", "short.mp4", "thumb.jpg", "long.srt"]:
            files[n] = os.path.join(wd, n)
            store.download(run_key(f"out/{n}"), files[n])
        result = publish_youtube(store, meta, files)
    else:
        raise SystemExit(f"Unknown PUBLISH_MODE {C.PUBLISH_MODE}")
    store.put_json(run_key("out/published.json"), result)
