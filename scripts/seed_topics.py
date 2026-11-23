"""Load the 100-day challenge(s) and general topics into DynamoDB. Safe to re-run: it updates text,
tasks and my_points, but never resets the status of days/topics that were already used.

  python scripts/seed_topics.py --table yt-autopilot-topics --region ap-south-1
  python scripts/seed_topics.py --table yt-autopilot-topics --list        # show the queue
"""
import argparse
import glob
import os

import boto3
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def challenge_items():
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "challenges", "*.yaml"))):
        with open(path) as f:
            ch = yaml.safe_load(f)
        for d in ch["days"]:
            out.append({"topic_id": f"{ch['slug']}-d{int(d['day']):03d}", "category": d["category"], "topic": d["title"],
                        "task": d.get("task", ""), "my_points": d.get("my_points", "") or "", "priority": 5,
                        "challenge": ch["slug"], "challenge_name": ch["name"], "challenge_order": int(ch.get("order", 1)),
                        "day": int(d["day"]), "total": int(ch.get("total", len(ch["days"])))})
    return out


def general_items():
    with open(os.path.join(ROOT, "topics", "topics.yaml")) as f:
        return [dict(t, my_points=t.get("my_points") or "", priority=int(t.get("priority", 5)))
                for t in yaml.safe_load(f)["topics"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "ap-south-1"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    table = boto3.resource("dynamodb", region_name=a.region).Table(a.table)

    if a.list:
        items, kw = [], {}
        while True:
            r = table.scan(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        ch = sorted([t for t in items if t.get("challenge")], key=lambda t: (t["challenge"], int(t["day"])))
        done = sum(t.get("status") == "DONE" for t in ch)
        print(f"Challenge progress: {done}/{len(ch)} days done")
        for t in [t for t in ch if t.get("status") != "DONE"][:7]:
            print(f"  next  Day {int(t['day']):3d}  {t.get('status', '?'):11} {t['category']:6} {t['topic']}")
        gen = [t for t in items if not t.get("challenge")]
        print(f"General topics: {sum(t.get('status') == 'PENDING' for t in gen)} pending of {len(gen)}")
        return

    items = challenge_items() + general_items()
    for t in items:
        fields = {k: v for k, v in t.items() if k != "topic_id"}
        names = {f"#k{i}": k for i, k in enumerate(fields)}
        values = {f":v{i}": v for i, v in enumerate(fields.values())}
        expr = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(fields))) + ", #s = if_not_exists(#s, :pending)"
        names["#s"] = "status"
        values[":pending"] = "PENDING"
        table.update_item(Key={"topic_id": t["topic_id"]}, UpdateExpression=expr,
                          ExpressionAttributeNames=names, ExpressionAttributeValues=values)
    print(f"Loaded {len(items)} items ({len(challenge_items())} challenge days) into {a.table}")


if __name__ == "__main__":
    main()
