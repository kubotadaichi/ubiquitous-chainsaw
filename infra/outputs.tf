output "s3_bucket" {
  value = aws_s3_bucket.assets.bucket
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "redis_url" {
  value = local.redis_url
}

output "ec2_public_ip" {
  value = aws_instance.app.public_ip
}

output "hub_api_url" {
  value = "http://${aws_instance.app.public_ip}:8000"
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/terraform.pem ec2-user@${aws_instance.app.public_ip}"
}
