# Emails + the mobile review page (approve / edit / reject) + download page.

resource "aws_sns_topic" "notify" {
  name = "${local.name}-notify"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.notify.arn
  protocol  = "email"
  endpoint  = var.notify_email
}

resource "aws_apigatewayv2_api" "review" {
  name          = "${local.name}-review"
  protocol_type = "HTTP"
}

data "archive_file" "review" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/review"
  output_path = "${path.module}/.build/review.zip"
}

resource "aws_iam_role" "review" {
  name = "${local.name}-review"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "review_logs" {
  role       = aws_iam_role.review.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "review" {
  role = aws_iam_role.review.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.data.arn}/runs/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.data.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.runs.arn, aws_dynamodb_table.topics.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["states:SendTaskSuccess", "states:SendTaskFailure"]
        Resource = aws_sfn_state_machine.daily.arn
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.notify.arn
      }
    ]
  })
}

resource "aws_lambda_function" "review" {
  function_name    = "${local.name}-review"
  role             = aws_iam_role.review.arn
  runtime          = "python3.12"
  handler          = "handler.lambda_handler"
  filename         = data.archive_file.review.output_path
  source_code_hash = data.archive_file.review.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      BUCKET        = aws_s3_bucket.data.bucket
      RUNS_TABLE    = aws_dynamodb_table.runs.name
      TOPICS_TABLE  = aws_dynamodb_table.topics.name
      SNS_TOPIC_ARN = aws_sns_topic.notify.arn
      API_URL       = aws_apigatewayv2_api.review.api_endpoint
      PUBLISH_MODE  = var.publish_mode
    }
  }
}

resource "aws_cloudwatch_log_group" "review" {
  name              = "/aws/lambda/${aws_lambda_function.review.function_name}"
  retention_in_days = 14
}

resource "aws_apigatewayv2_integration" "review" {
  api_id                 = aws_apigatewayv2_api.review.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.review.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "review" {
  for_each  = toset(["GET /review/{run_id}", "POST /review/{run_id}", "GET /ready/{run_id}"])
  api_id    = aws_apigatewayv2_api.review.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.review.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.review.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowHttpApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.review.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.review.execution_arn}/*/*"
}
