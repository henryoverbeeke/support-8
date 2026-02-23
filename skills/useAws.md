# AWS CLI Access Guide

## Configuration

AWS CLI is configured on this machine with the following settings:

- **Region:** us-east-2
- **Account ID:** 584973764297
- **Credentials:** Located at `~/.aws/credentials` (default profile)
- **Output format:** JSON

## Important

Always include `--region us-east-2` in AWS CLI commands.

## Available Lambda Functions

| Function | Runtime | Purpose |
|----------|---------|---------|
| `todolist` | Python 3.13 | Todo list backend |
| `manage-users` | Python 3.13 | User management |
| `PhotoGalleryAPI` | Python 3.12 | Photo gallery backend |

## Common Commands

```bash
# List all Lambda functions
aws lambda list-functions --region us-east-2

# Get function details
aws lambda get-function --function-name <function-name> --region us-east-2

# Invoke a function
aws lambda invoke --function-name <function-name> --payload '{}' output.json --region us-east-2

# Update function code from zip
aws lambda update-function-code --function-name <function-name> --zip-file fileb://function.zip --region us-east-2

# View logs (follow mode)
aws logs tail /aws/lambda/<function-name> --follow

# View recent logs
aws logs tail /aws/lambda/<function-name> --since 1h
```

## Debugging

CloudWatch logs are available at `/aws/lambda/<function-name>` for each Lambda function.

---

This gives Cursor everything it needs to work with your AWS setup.
