# infra (Terraform)

## Quick start

1. Copy example vars and edit:
   - `cp terraform.tfvars.example terraform.tfvars`
2. Initialize:
   - `terraform init`
3. Apply:
   - `terraform apply`

## Destroy and rebuild (clean slate)

- Destroy everything created by this Terraform state:
  - `terraform destroy`
- Recreate:
  - `terraform apply`

## Notes

- `ssh_key_name` is the **Key Pair name** in the AWS console (region-scoped), not a `.pem` path.
- If `docker-compose.cloud.yml` is under a subdirectory in your repo, set `repo_subdir`.
- If you front the Hub API with CloudFront (`hub_api_https_url`), make sure the EC2 SG allows inbound `:8000` from CloudFront origin-facing IPs (this repo uses the managed prefix list).

