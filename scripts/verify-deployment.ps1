param(
    [string]$EnvironmentFile = ".env.deploy",
    [string]$ManifestChecksumFile = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$environmentPath = (Resolve-Path (Join-Path $projectRoot $EnvironmentFile)).Path

if ($ManifestChecksumFile) {
    $checksumPath = (Resolve-Path $ManifestChecksumFile).Path
    $expected = (Get-Content -LiteralPath $checksumPath -Raw).Split(" ")[0].Trim().ToUpperInvariant()
    $actual = (Get-FileHash -LiteralPath $environmentPath -Algorithm SHA256).Hash
    if ($actual -ne $expected) {
        throw "Deployment manifest SHA-256 mismatch. Expected $expected, got $actual."
    }
}

$requiredImages = @(
    "KAXI_BACKEND_IMAGE",
    "KAXI_WEB_IMAGE",
    "KAXI_POSTGRES_IMAGE",
    "KAXI_REDIS_IMAGE",
    "KAXI_MINIO_IMAGE",
    "KAXI_MINIO_CLIENT_IMAGE"
)
$values = @{}
foreach ($line in Get-Content -LiteralPath $environmentPath) {
    if ($line -match "^([A-Z0-9_]+)=(.*)$") {
        $values[$Matches[1]] = $Matches[2].Trim()
    }
}
foreach ($name in $requiredImages) {
    $value = $values[$name]
    if (-not $value -or $value -notmatch "^[^\s@]+@sha256:[a-fA-F0-9]{64}$") {
        throw "$name must use an immutable repository@sha256:digest reference."
    }
}

$docker = (Get-Command docker -ErrorAction Stop).Source
$env:KAXI_ENV_FILE = $EnvironmentFile
& $docker compose --env-file $environmentPath -f (Join-Path $projectRoot "compose.deploy.yaml") config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose configuration validation failed."
}

foreach ($name in $requiredImages) {
    & $docker buildx imagetools inspect $values[$name] | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Image digest is unavailable: $($values[$name])"
    }
}

Write-Output "Deployment manifest and all immutable image digests are valid."
