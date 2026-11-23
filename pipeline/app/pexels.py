"""Optional stock b-roll from Pexels (free API key: https://www.pexels.com/api/).
Without a key, the pipeline uses title cards instead."""
import hashlib
import os

import requests

from . import config as C


def fetch(query, portrait, workdir):
    if not C.PEXELS_API_KEY or not query:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search", timeout=20,
                         headers={"Authorization": C.PEXELS_API_KEY},
                         params={"query": query, "orientation": "portrait" if portrait else "landscape",
                                 "size": "medium", "per_page": 8})
        r.raise_for_status()
        for v in r.json().get("videos", []):
            files = sorted([f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                            and (f.get("height") or 0) >= 720], key=lambda f: f.get("height") or 0)
            if not files:
                continue
            f = files[0] if (files[0].get("height") or 0) >= 1080 or len(files) == 1 else files[1]
            path = os.path.join(workdir, "broll_" + hashlib.md5(f["link"].encode()).hexdigest()[:10] + ".mp4")
            if not os.path.exists(path):
                with requests.get(f["link"], stream=True, timeout=60) as d:
                    d.raise_for_status()
                    with open(path, "wb") as out:
                        for chunk in d.iter_content(1 << 20):
                            out.write(chunk)
            return path
    except Exception as e:  # b-roll is a nice-to-have; never fail the run for it
        print(f"[pexels] skipped '{query}': {e}")
    return None
