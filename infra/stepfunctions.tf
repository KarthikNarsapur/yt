resource "aws_iam_role" "sfn" {
  name = "${local.name}-sfn"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = "${aws_ecs_task_definition.pipeline.arn_without_revision}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:StopTask", "ecs:DescribeTasks"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.exec.arn, aws_iam_role.task.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
        Resource = "arn:aws:events:${var.region}:${local.account_id}:rule/StepFunctionsGetEventsForECSTaskRule"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.review.arn, "${aws_lambda_function.review.arn}:*"]
      }
    ]
  })
}

locals {
  asl_raw = jsondecode(templatefile("${path.module}/statemachine.asl.json", {
    cluster_arn       = aws_ecs_cluster.this.arn
    task_definition   = aws_ecs_task_definition.pipeline.arn_without_revision
    capacity_provider = var.use_fargate_spot ? "FARGATE_SPOT" : "FARGATE"
    subnets           = jsonencode(data.aws_subnets.default.ids)
    security_group    = aws_security_group.task.id
    review_function   = aws_lambda_function.review.arn
    after_script      = var.require_approval ? "WaitForApproval" : "Render"
    after_render      = var.publish_mode == "none" ? "NotifyReady" : "Publish"
  }))
  # Step Functions rejects unreachable states, so drop the ones this configuration never uses.
  asl_drop = concat(
    var.require_approval ? [] : ["WaitForApproval", "Approved?", "ReturnTopicToQueue"],
    var.publish_mode == "none" ? ["Publish"] : []
  )
  asl = merge(local.asl_raw, {
    States = { for k, v in local.asl_raw.States : k => v if !contains(local.asl_drop, k) }
  })
}

resource "aws_sfn_state_machine" "daily" {
  name       = "${local.name}-daily"
  role_arn   = aws_iam_role.sfn.arn
  definition = jsonencode(local.asl)
  depends_on = [aws_ecs_cluster_capacity_providers.this]
}

# ------------------------------------------------------------ daily schedule
resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["states:StartExecution"]
      Resource = aws_sfn_state_machine.daily.arn
    }]
  })
}

resource "aws_scheduler_schedule" "daily" {
  name                         = "${local.name}-daily"
  state                        = var.schedule_enabled ? "ENABLED" : "DISABLED"
  schedule_expression          = var.schedule_cron
  schedule_expression_timezone = var.schedule_timezone
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_sfn_state_machine.daily.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = "{}"
    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
