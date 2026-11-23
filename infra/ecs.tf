resource "aws_ecs_cluster" "this" {
  name = local.name
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# ---- roles
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "exec" {
  name               = "${local.name}-ecs-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "exec_secrets" {
  role = aws_iam_role.exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = [for p in aws_ssm_parameter.secret : p.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.data.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.data.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.topics.arn
      }
    ]
  })
}

# ---- task definition (one image, three commands: script | render | publish)
resource "aws_ecs_task_definition" "pipeline" {
  family                   = "${local.name}-pipeline"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.exec.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  ephemeral_storage {
    size_in_gib = 30 # image + fallback model (~4.7 GB) + renders
  }

  container_definitions = jsonencode([{
    name      = "pipeline"
    image     = "${aws_ecr_repository.pipeline.repository_url}:latest"
    essential = true
    command   = ["render"]
    environment = [
      { name = "BUCKET", value = aws_s3_bucket.data.bucket },
      { name = "TOPICS_TABLE", value = aws_dynamodb_table.topics.name },
      { name = "LLM_PROVIDER", value = var.llm_provider },
      { name = "CLAUDE_MODEL", value = var.claude_model },
      { name = "OLLAMA_MODEL", value = var.ollama_model },
      { name = "PUBLISH_MODE", value = var.publish_mode },
      { name = "VOICE", value = var.voice },
      { name = "CHANNEL_NAME", value = var.channel_name },
      { name = "PUBLISH_TZ", value = var.schedule_timezone },
      { name = "PUBLISH_TIME_LONG", value = var.publish_time_long },
      { name = "PUBLISH_TIME_SHORT", value = var.publish_time_short },
    ]
    secrets = [
      { name = "CLAUDE_CODE_OAUTH_TOKEN", valueFrom = aws_ssm_parameter.secret["claude_token"].arn },
      { name = "PEXELS_API_KEY", valueFrom = aws_ssm_parameter.secret["pexels"].arn },
      { name = "YT_OAUTH", valueFrom = aws_ssm_parameter.secret["youtube"].arn },
      { name = "PUBLISH_WEBHOOK_URL", valueFrom = aws_ssm_parameter.secret["webhook"].arn },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.pipeline.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "pipeline"
      }
    }
  }])
}
