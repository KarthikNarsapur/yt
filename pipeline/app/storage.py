"""Storage + topic queue. S3/DynamoDB in AWS, plain files in local mode."""
import datetime as dt
import json
import os
import shutil

from . import config as C


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- objects
class Store:
    def __init__(self):
        self.local = bool(C.LOCAL_DIR)
        if not self.local:
            import boto3
            self.s3 = boto3.client("s3")

    def _lp(self, key):
        p = os.path.join(C.LOCAL_DIR, key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def put_json(self, key, obj):
        data = json.dumps(obj, indent=2, ensure_ascii=False)
        if self.local:
            with open(self._lp(key), "w") as f:
                f.write(data)
        else:
            self.s3.put_object(Bucket=C.BUCKET, Key=key, Body=data.encode(),
                               ContentType="application/json")

    def get_json(self, key):
        if self.local:
            with open(self._lp(key)) as f:
                return json.load(f)
        body = self.s3.get_object(Bucket=C.BUCKET, Key=key)["Body"].read()
        return json.loads(body)

    def upload(self, path, key, content_type=None):
        if self.local:
            shutil.copyfile(path, self._lp(key))
            return
        extra = {"ContentType": content_type} if content_type else None
        self.s3.upload_file(path, C.BUCKET, key, ExtraArgs=extra)

    def download(self, key, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if self.local:
            shutil.copyfile(self._lp(key), path)
        else:
            self.s3.download_file(C.BUCKET, key, path)

    def presign(self, key, expires=6 * 3600):
        if self.local:
            return "file://" + os.path.abspath(self._lp(key))
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": C.BUCKET, "Key": key}, ExpiresIn=expires)

    def list(self, prefix):
        if self.local:
            root = os.path.join(C.LOCAL_DIR, prefix)
            out = []
            for d, _, files in os.walk(root):
                for f in files:
                    out.append(os.path.relpath(os.path.join(d, f), C.LOCAL_DIR))
            return sorted(out)
        keys, token = [], None
        while True:
            kw = {"Bucket": C.BUCKET, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            r = self.s3.list_objects_v2(**kw)
            keys += [o["Key"] for o in r.get("Contents", [])]
            if not r.get("IsTruncated"):
                return keys
            token = r["NextContinuationToken"]


def run_key(name):
    return f"runs/{C.RUN_ID}/{name}"


# ---------------------------------------------------------------- topics
def load_challenges(directory=None):
    """Flatten challenges/*.yaml into topic items (one per day)."""
    import glob
    import yaml
    out = []
    for path in sorted(glob.glob(os.path.join(directory or C.CHALLENGES_DIR, "*.yaml"))):
        with open(path) as f:
            ch = yaml.safe_load(f)
        for d in ch["days"]:
            out.append({
                "topic_id": f"{ch['slug']}-d{int(d['day']):03d}", "category": d["category"], "topic": d["title"],
                "task": d.get("task", ""), "my_points": d.get("my_points", ""), "priority": 5,
                "challenge": ch["slug"], "challenge_name": ch["name"], "challenge_order": int(ch.get("order", 1)),
                "day": int(d["day"]), "total": int(ch.get("total", len(ch["days"]))),
            })
    return out


class Topics:
    """Topic queue. Challenge days run first, strictly in order; then general topics rotate by category.
    Item fields: topic_id, category, topic, my_points, priority, status (+ challenge, day, total, task)."""

    def __init__(self):
        self.local = bool(C.LOCAL_DIR)
        if self.local:
            import yaml
            self.state_file = os.path.join(C.LOCAL_DIR, "topics_state.json")
            if os.path.exists(self.state_file):
                with open(self.state_file) as f:
                    self.items = json.load(f)
            else:
                with open(C.TOPICS_FILE) as f:
                    general = yaml.safe_load(f)["topics"]
                self.items = [dict(t, status="PENDING") for t in load_challenges() + general]
        else:
            import boto3
            self.table = boto3.resource("dynamodb").Table(C.TOPICS_TABLE)
        self._cache = None

    def _all(self):
        if self.local:
            return self.items
        if self._cache is not None:
            return self._cache
        items, kw = [], {}
        while True:
            r = self.table.scan(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                self._cache = items
                return items
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]

    def find(self, challenge, day):
        for t in self._all():
            if t.get("challenge") == challenge and int(t.get("day", 0)) == int(day):
                return t
        return None

    def pick_next(self):
        """Rotate categories by day so the channel covers Linux, AWS, Azure, GCP and DevOps evenly.
        Topics where you've written your own points are preferred, then by priority."""
        items = self._all()
        retry = [t for t in items if t.get("status") == "IN_PROGRESS" and t.get("run_id") == C.RUN_ID]
        if retry:                       # Step Functions retried this run: keep the same topic
            return retry[0]
        pending = [t for t in items if t.get("status", "PENDING") == "PENDING"]
        challenge_days = sorted([t for t in pending if t.get("challenge")],
                                key=lambda t: (int(t.get("challenge_order", 1)), t["challenge"], int(t["day"])))
        if challenge_days:              # never skip a day: a failed day is retried tomorrow
            return challenge_days[0]
        if not pending:
            raise SystemExit("No PENDING topics left - add more with scripts/seed_topics.py")
        day = dt.date.today().toordinal()
        order = C.CATEGORIES[day % 5:] + C.CATEGORIES[:day % 5]

        def rank(t):
            return (0 if (t.get("my_points") or "").strip() else 1, -int(t.get("priority", 5)), t["topic_id"])

        for cat in order:
            cands = sorted([t for t in pending if t.get("category") == cat], key=rank)
            if cands:
                return cands[0]
        return sorted(pending, key=rank)[0]

    def set_status(self, topic_id, status, **extra):
        if self.local:
            for t in self.items:
                if t["topic_id"] == topic_id:
                    t.update(status=status, updated_at=_now(), **extra)
            with open(self.state_file, "w") as f:
                json.dump(self.items, f, indent=2)
            return
        names = {"#s": "status", "#u": "updated_at"}
        values = {":s": status, ":u": _now()}
        expr = "SET #s = :s, #u = :u"
        for i, (k, v) in enumerate(extra.items()):
            names[f"#e{i}"] = k
            values[f":e{i}"] = v
            expr += f", #e{i} = :e{i}"
        self.table.update_item(Key={"topic_id": topic_id}, UpdateExpression=expr,
                               ExpressionAttributeNames=names, ExpressionAttributeValues=values)
