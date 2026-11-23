# yt-autopilot

A fully automatic daily pipeline for a Linux / AWS / Azure / GCP / DevOps YouTube channel.
Every night it makes **one ~9–10 minute video and one Short**, working through the
**100 Days of Cloud & DevOps** challenge one day at a time. It runs on AWS, on CPU only:

- the script is written by **Claude, using your Claude Pro subscription** (Claude Code in headless mode), with an
  open model (Ollama + Qwen2.5-7B) on CPU as a fallback;
- a **second Claude pass acts as a senior engineer** and fixes wrong commands, flags and facts, and automatic code
  checks (`bash -n`, YAML/JSON/HCL/Python parsers, lengths) gate the result. No human approval is needed;
- the voice is **Kokoro** (open, Apache-2.0), the slides and code cards are drawn with Pillow, and ffmpeg renders;
- it **publishes from the workflow**: YouTube Data API, a webhook (Make/Zapier/n8n), or a download page.

```
EventBridge Scheduler 00:30 IST
   │
Step Functions
   ├─ WriteScript        Fargate Spot 1 vCPU  · claude -p (Pro token) → script → Claude technical review → code checks
   │     └─ on failure → WriteScriptLocal   8 vCPU · Ollama/Qwen on CPU (e.g. Pro usage limit reached)
   ├─ [WaitForApproval]  only if require_approval = true
   ├─ Render             Fargate Spot 8 vCPU · Kokoro voice, slides, code cards, captions → long.mp4, short.mp4, thumbnail
   ├─ Publish            YouTube API (scheduled 12:30 Short / 18:30 long, playlist) or webhook
   └─ Email "ready"      links, metadata, and what the AI reviewer fixed
```

## The 100-day challenge
`challenges/100-days-cloud-devops.yaml` has 100 ordered days, each with a title and a hands-on task:

| Days | Track |
|---|---|
| 1–18 | Linux, Bash, networking |
| 19–20 | Git |
| 21–40 | AWS |
| 41–52 | Azure |
| 53–64 | Google Cloud |
| 65–72 | Docker |
| 73–82 | Kubernetes |
| 83–88 | Terraform, Ansible |
| 89–94 | CI/CD, GitOps |
| 95–98 | Observability, DevSecOps, deployments |
| 99–100 | Capstone |

- Days run **strictly in order**. If a day fails, the same day is retried the next night, so there are no gaps.
- Each video opens with "Day N of 100", links back to yesterday, and ends with a **"Your Day N task"** section,
  asking viewers to comment "Day N done". The end card teases tomorrow.
- Titles look like `Day 12/100: …`. Every slide carries a `DAY 12 / 100` badge, and the thumbnail has a big DAY 12 with a progress bar.
- With `publish_mode = youtube`, long videos go into a "100 Days of Cloud & DevOps" playlist, which is created automatically.
- After day 100, the pipeline continues with the 77 general topics in `topics/topics.yaml`. To queue another challenge,
  add another file (e.g. `30-days-kubernetes.yaml` with `order: 2`).
- Optional: add `my_points:` (your own experience) to any day; it's woven in first-person.

## Daily cost (Mumbai, ap-south-1), estimated
| Item | USD/day |
|---|---|
| Script: Claude writes + reviews (1 vCPU / 2 GB Spot, ~8 min) | 0.002 |
| Render: long + Short (8 vCPU / 16 GB Spot, ~25 min) | 0.054 |
| Publish upload (1 vCPU / 2 GB on-demand, ~5 min) | 0.004 |
| Public IPv4 while tasks run | 0.003 |
| ECR image (~3 GB) + S3 (model cache, 14 days of renders) | 0.014 |
| Step Functions, Lambda, API Gateway, DynamoDB, SNS, logs | 0.002 |
| **Total** | **≈ 0.08 (≈ $2.40/month)** |

Assumptions: Fargate Spot x86 in ap-south-1 at $0.01324 per vCPU-hour and $0.001448 per GB-hour, on-demand at
$0.04256 and $0.004655. The 25-minute render is an estimate; 15–35 minutes means $0.03–0.075. With `use_fargate_spot = false`
the total is about $0.20/day. A day where the Ollama fallback runs adds about $0.04. Secrets use SSM Parameter Store
(free, standard tier), and uploads to YouTube fall within AWS's free 100 GB/month of outbound traffic.
**Claude costs nothing extra**: it uses your Pro plan, and shares that plan's usage limits with your normal Claude use.

---

## Read this before going fully automatic
1. **Direct uploads need the YouTube API audit.** Videos uploaded through the API from an *unverified* Google Cloud project
   are locked to private, and you can't appeal that. So `publish_mode` starts at `none`. Submit the audit early
   ([form](https://support.google.com/youtube/contact/yt_api_form)), then switch to `youtube`. Until then you can use a
   `webhook` to a service with its own verified YouTube connection (check its file-size limits; e.g. Make's free plan
   caps files at 5 MB), or upload from the ready page.
2. **Monetization.** YouTube won't monetize generic, mass-produced AI content without original insight, and it judges
   the whole channel. The challenge format (a structured curriculum with hands-on tasks), the AI technical review, and
   adding `my_points` now and then are what make this channel more than a content farm. If a video ever looks
   off, set `require_approval = true` for a while.
3. From **1 Feb 2027**, new channels need 1,000 subscribers plus 8,000 long-form watch hours in 12 months, or 20M Shorts
   views in 90 days, to join the Partner Program.
4. Verify your channel with a phone number (YouTube Studio → Settings → Channel → Feature eligibility) so custom
   thumbnails work.

---

## Setup (about 30 minutes)
**You need:** AWS CLI, Terraform ≥ 1.6, Docker (or GitHub Actions), Python 3.10+, Claude Code on your laptop.

### 1. Infrastructure
```bash
cd infra
cp terraform.tfvars.example terraform.tfvars      # notify_email, github_repo
terraform init && terraform apply
```
Confirm the SNS subscription email.

### 2. Connect your Claude Pro subscription
On your laptop (it opens a browser once):
```bash
claude setup-token          # prints a long-lived token for scripts/CI (valid about a year)
aws ssm put-parameter --overwrite --type SecureString \
  --name /yt-autopilot/claude-oauth-token --value "<paste token>"
```
Set a calendar reminder to rotate the token before it expires.

### 3. Build the image
**GitHub Actions** (recommended): in the repo settings, add the variables `ECR_REPOSITORY_URL` and `AWS_ROLE_ARN`
(from `terraform output`), then push to `main`. **Or from your laptop:**
```bash
ECR=$(terraform -chdir=infra output -raw ecr_repository_url)
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin ${ECR%%/*}
docker build --platform linux/amd64 -f pipeline/Dockerfile -t $ECR:latest . && docker push $ECR:latest
```

### 4. Load the challenge and topics
```bash
pip install boto3 pyyaml
python scripts/seed_topics.py --table yt-autopilot-topics
python scripts/seed_topics.py --table yt-autopilot-topics --list     # progress + next days
```

### 5. First run
```bash
aws stepfunctions start-execution --state-machine-arn $(terraform -chdir=infra output -raw state_machine_arn)
```
After that it runs every night at 00:30 IST. Pause with `schedule_enabled = false`.

### 6. Turn on direct publishing
**YouTube API** (after the audit passes):
1. Follow the steps at the top of `scripts/youtube_auth.py`. Publish the OAuth app to "In production",
   or refresh tokens expire after 7 days.
2. `aws ssm put-parameter --overwrite --type SecureString --name /yt-autopilot/youtube-oauth --value file://youtube_oauth.json`
3. `publish_mode = "youtube"` → `terraform apply`. The Short publishes at 12:30, the long video at 18:30, and the Short links to the long video.

**Webhook** (Make / Zapier / n8n): store the URL in `/yt-autopilot/publish-webhook-url`, then set `publish_mode = "webhook"`.
The POST body has `long` and `short` objects, each with `title`, `description`, `tags`, `publish_at` and a `video_url`
(pre-signed S3 link that expires within a few hours), plus `thumbnail_url` and `captions_url` for the long video.

### Optional
- Pexels key for stock b-roll: `/yt-autopilot/pexels-api-key`
- Royalty-free music: upload to `s3://<bucket>/assets/music/`; one track a day is mixed quietly under the voice.

## Settings
| Variable | Default | Notes |
|---|---|---|
| `require_approval` | `false` | `true` = email review page; the run waits up to 20 h for your approval |
| `publish_mode` | `none` | `youtube` / `webhook` / `none` |
| `llm_provider` / `claude_model` | `claude` / `sonnet` | Pro plans use Sonnet in Claude Code |
| `ollama_model` | `qwen2.5:7b-instruct` | fallback only |
| `voice` | `am_michael` | Kokoro: `am_adam`, `af_heart`, `bm_george`, `bf_emma`, … |
| `schedule_cron` | `cron(30 0 * * ? *)` | Asia/Kolkata |
| `publish_time_short` / `_long` | `12:30` / `18:30` | IST |
| `use_fargate_spot` | `true` | about 3x cheaper; interrupted tasks are retried |
| env `LONG_SECTIONS` / `SECTION_WORDS` | 8 / 160 | about 9–10 minutes |

## Test locally (no AWS)
```bash
./scripts/local_render.sh      # renders tests/sample_script.json (a Day 85 sample) → local-out/
```

## Layout
```
challenges/   100-days-cloud-devops.yaml (+ any future challenges)
topics/       topics.yaml: 77 general topics used after the challenge
infra/        Terraform: S3, DynamoDB, ECR, ECS Fargate, Step Functions, Scheduler, SNS, HTTP API, SSM, GitHub OIDC
pipeline/     Container: script_stage (Claude + review + checks), render_stage, publish_stage, tts, visuals, captions
lambdas/      review/handler.py: emails, optional approval page, download page
scripts/      seed_topics.py, youtube_auth.py, local_render.sh
```

## Known limits
- The AI reviewer and the parsers catch most mistakes, not all. Commands are checked for syntax, not run in a real cloud.
- If you hit your Pro usage limit, that day's script comes from the local 7B model, which writes weaker scripts.
- Visuals are slides, code cards and optional stock footage. Adding your own terminal recordings now and then helps the channel.
