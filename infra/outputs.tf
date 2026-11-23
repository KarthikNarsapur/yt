output "bucket" {
  value = aws_s3_bucket.data.bucket
}

output "topics_table" {
  value = aws_dynamodb_table.topics.name
}

output "ecr_repository_url" {
  value = aws_ecr_repository.pipeline.repository_url
}

output "review_api_url" {
  value = aws_apigatewayv2_api.review.api_endpoint
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.daily.arn
}

output "github_role_arn" {
  value = local.gh_enabled ? aws_iam_role.github[0].arn : "(github_repo not set)"
}

output "next_steps" {
  value = <<-EOT
    1. Confirm the SNS email sent to ${var.notify_email}
    2. Push the image:   see README "Build the image"
    3. Claude token:     claude setup-token   (on your laptop), then
                         aws ssm put-parameter --overwrite --type SecureString --name ${aws_ssm_parameter.secret["claude_token"].name} --value "<token>"
    4. Load topics + the 100-day challenge:
                         python scripts/seed_topics.py --table ${aws_dynamodb_table.topics.name} --region ${var.region}
    5. Test run now:     aws stepfunctions start-execution --state-machine-arn ${aws_sfn_state_machine.daily.arn}
  EOT
}
