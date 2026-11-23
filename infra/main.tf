locals {
  name       = var.project
  account_id = data.aws_caller_identity.me.account_id
}

resource "random_id" "suffix" {
  byte_length = 3
}

# ------------------------------------------------------------ network
# Default VPC + public IP on the task: no NAT gateway to pay for. No inbound rules at all.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "task" {
  name        = "${local.name}-task"
  description = "Outbound only (Pexels, Ollama registry, YouTube API, AWS APIs)"
  vpc_id      = data.aws_vpc.default.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ------------------------------------------------------------ storage
resource "aws_s3_bucket" "data" {
  bucket = "${local.name}-${local.account_id}-${random_id.suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "expire-renders"
    status = "Enabled"
    filter {
      prefix = "runs/"
    }
    expiration {
      days = 14
    }
  }
}

resource "aws_dynamodb_table" "topics" {
  name         = "${local.name}-topics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "topic_id"
  attribute {
    name = "topic_id"
    type = "S"
  }
  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "runs" {
  name         = "${local.name}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  attribute {
    name = "run_id"
    type = "S"
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# ------------------------------------------------------------ image + secrets
resource "aws_ecr_repository" "pipeline" {
  name                 = "${local.name}/pipeline"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "pipeline" {
  repository = aws_ecr_repository.pipeline.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# Secrets live in SSM Parameter Store (SecureString, standard tier = free). Terraform only creates
# placeholders; you set the real values with `aws ssm put-parameter --overwrite` (see README).
locals {
  params = {
    claude_token = "claude-oauth-token"   # from `claude setup-token`
    pexels       = "pexels-api-key"       # optional
    youtube      = "youtube-oauth"        # for publish_mode = youtube
    webhook      = "publish-webhook-url"  # for publish_mode = webhook
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.params
  name     = "/${local.name}/${each.value}"
  type     = "SecureString"
  value    = "CHANGE_ME"
  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/ecs/${local.name}"
  retention_in_days = 14
}
