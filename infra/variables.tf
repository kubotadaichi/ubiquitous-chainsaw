variable "aws_region" {
  type = string
}

variable "project_name" {
  type    = string
  default = "pipeline"
}

variable "repo_url" {
  type = string
}

variable "repo_ref" {
  type    = string
  default = "main"
}

variable "repo_subdir" {
  type    = string
  default = ""
}

variable "instance_type" {
  type    = string
  default = "t3.large"
}

variable "ssh_key_name" {
  type    = string
  default = null
}

variable "ssh_ingress_cidr" {
  type    = string
  default = "0.0.0.0/0"
}

variable "hub_ingress_cidr" {
  type    = string
  default = "0.0.0.0/0"
}

variable "redis_node_type" {
  type    = string
  default = "cache.t3.micro"
}

variable "s3_bucket_prefix" {
  type    = string
  default = "hackathon-pipeline-"
}

variable "s3_force_destroy" {
  type    = bool
  default = true
}
