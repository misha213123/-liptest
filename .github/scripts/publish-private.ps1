# Publish the validated desktop version to PRIVATE GitHub Releases.
# Run after the latest Windows preview build has passed on the feature branch.
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $root
try {
  if ((git remote get-url origin) -notmatch 'misha213123/-liptest(\.git)?$') {
    throw 'Wrong origin. Expected misha213123/-liptest.'
  }
  git fetch origin feature/windows-desktop-installer
  if ($LASTEXITCODE -ne 0) { throw 'Failed to fetch desktop branch.' }
  $commit = (git rev-parse origin/feature/windows-desktop-installer).Trim()
  if ($LASTEXITCODE -ne 0) { throw 'Cannot read desktop commit.' }
  $pkg = (git show "${commit}:desktop/package.json" | Out-String | ConvertFrom-Json)
  $version = [string]$pkg.version
  if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid version.' }
  $tag = "v$version"
  if ($Force) { Write-Host 'Forcing publication of a potentially unverified commit is not supported.'; exit 1 }
  $url = "https://api.github.com/repos/misha213123/-liptest"
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    $visibility = (gh api $url --jq '.private').Trim()
    if ($visibility -ne 'true') { throw 'Release blocked: repository is not private.' }
    $checks = gh api "$url/commits/$commit/check-runs" --jq '[.check_runs[] | select(.name == "build-preview" and .conclusion == "success")] | length' 2>$null
    if (($checks | Select-Object -Last 1) -ne '1') {
      Write-Warning 'A successful Windows preview check for this commit was not verified. Review GitHub Actions before continuing.'
      throw 'Desktop release is not validated.'
    }
  } else {
    throw 'Install and log in to GitHub CLI (gh auth login) to verify private repository and successful build.'
  }
  $found = (git ls-remote --tags origin "refs/tags/$tag").Trim()
  if ($found) { throw "Tag $tag already exists; increment version instead of replacing it." }
  Write-Host "Publishing $tag at $commit (private GitHub repository)."
  git tag -a $tag $commit -m "GTA 6 Clip Studio $version"
  if ($LASTEXITCODE -ne 0) { throw 'Failed to create release tag.' }
  git push origin "refs/tags/$tag"
  if ($LASTEXITCODE -ne 0) { throw 'Failed to push release tag.' }
  Write-Host 'Release workflow should begin at: https://github.com/misha213123/-liptest/actions/workflows/windows-release.yml'
} finally { Pop-Location }
