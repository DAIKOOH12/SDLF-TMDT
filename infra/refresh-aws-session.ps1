# Refresh the AWS "login" session and sync it into this PowerShell session's
# environment variables, so both `cdk`/`aws` (which read ~/.aws/config) and
# any Python/boto3 script (which prefers env vars) use the SAME, fresh token.
#
# Why this exists: the org's `aws login` tool issues short-lived session
# tokens. Env vars take priority over ~/.aws/config in every AWS SDK, so if
# you `aws login` again without re-exporting, cdk/boto3 keep using the old
# (now expired) token from the environment and fail with ExpiredToken even
# though the login itself succeeded.
#
# Usage (must be dot-sourced so the env vars persist in your shell):
#   . .\refresh-aws-session.ps1
#
# Run this again any time a command fails with ExpiredToken.

aws login
if ($LASTEXITCODE -ne 0) {
    Write-Error "aws login failed — fix that first, then re-run this script."
    return
}

$creds = aws configure export-credentials --format process | ConvertFrom-Json
$env:AWS_ACCESS_KEY_ID = $creds.AccessKeyId
$env:AWS_SECRET_ACCESS_KEY = $creds.SecretAccessKey
$env:AWS_SESSION_TOKEN = $creds.SessionToken

Write-Host "AWS session refreshed. Credentials expire at: $($creds.Expiration)" -ForegroundColor Green
