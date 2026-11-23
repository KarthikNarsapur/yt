variable "project" {
  type    = string
  default = "yt-autopilot"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "notify_email" {
  description = "Where review / ready / failure emails go (confirm the SNS subscription email once)."
  type        = string
}

variable "channel_name" {
  type    = string
  default = "Cloud & DevOps Daily"
}

variable "schedule_cron" {
  description = "When the daily script is written. Default 00:30 so it's waiting for you in the morning."
  type        = string
  default     = "cron(30 0 * * ? *)"
}

variable "schedule_timezone" {
  type    = string
  default = "Asia/Kolkata"
}

variable "schedule_enabled" {
  description = "Turn off to pause the daily run without destroying anything."
  type        = bool
  default     = true
}

variable "require_approval" {
  description = "false = fully automatic (AI technical review + code checks replace you). true = email review page, wait for your approval."
  type        = bool
  default     = false
}

variable "publish_mode" {
  description = "none = download page; youtube = direct API upload (needs the API audit, or uploads are locked private); webhook = POST to Make/Zapier/n8n."
  type        = string
  default     = "none"
  validation {
    condition     = contains(["none", "youtube", "webhook"], var.publish_mode)
    error_message = "publish_mode must be none, youtube or webhook."
  }
}

variable "llm_provider" {
  description = "claude = your Claude Pro/Max subscription via Claude Code (token from `claude setup-token`); ollama = local CPU model."
  type        = string
  default     = "claude"
}

variable "claude_model" {
  description = "Claude Code model alias. Pro plans use Sonnet."
  type        = string
  default     = "sonnet"
}

variable "ollama_model" {
  description = "Fallback model if the Claude step fails. 7-8B quantized models fit 8 vCPU / 16 GB on CPU."
  type        = string
  default     = "qwen2.5:7b-instruct"
}

variable "voice" {
  description = "Kokoro voice, e.g. am_michael, am_adam, af_heart, bm_george, bf_emma."
  type        = string
  default     = "am_michael"
}

variable "task_cpu" {
  type    = number
  default = 8192
}

variable "task_memory" {
  type    = number
  default = 16384
}

variable "use_fargate_spot" {
  description = "Fargate Spot is much cheaper; an interrupted task is retried by Step Functions."
  type        = bool
  default     = true
}

variable "publish_time_long" {
  type    = string
  default = "18:30"
}

variable "publish_time_short" {
  type    = string
  default = "12:30"
}

variable "github_repo" {
  description = "owner/repo allowed to push images via GitHub Actions OIDC. Empty = skip."
  type        = string
  default     = ""
}

variable "create_github_oidc_provider" {
  description = "Set false if your account already has the token.actions.githubusercontent.com provider."
  type        = bool
  default     = true
}
