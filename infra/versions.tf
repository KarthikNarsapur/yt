terraform {
  required_version = ">= 1.6"
  required_providers {
    aws     = { source = "hashicorp/aws", version = ">= 5.80" }
    archive = { source = "hashicorp/archive", version = ">= 2.4" }
    random  = { source = "hashicorp/random", version = ">= 3.6" }
  }
  # Recommended: keep this project's own state remote too.
  # backend "s3" {
  #   bucket       = "your-tf-state-bucket"
  #   key          = "yt-autopilot/terraform.tfstate"
  #   region       = "ap-south-1"
  #   use_lockfile = true
  # }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.project }
  }
}

data "aws_caller_identity" "me" {}
data "aws_region" "current" {}
