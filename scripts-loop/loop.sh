# Usage: .\scripts-loop\loop.ps1 -Max 3
param([int]$Max = 3, [int]$SleepSeconds = 20)

if (git status --porcelain --untracked-files=no) {
  Write-Host "Working tree is dirty. Commit or stash first."; exit 1
}

for ($i = 1; $i -le $Max; $i++) {
  $open = Select-String -Path BUGS.md -Pattern '^- \[ \]' -Quiet
  if (-not $open) { Write-Host "No open items. Done."; break }

  Write-Host "=== Iteration $i of $Max ==="
  opencode run "Follow .opencode/commands/fix-next.md exactly for the first open item in BUGS.md. Do not commit."

  python -m pytest -q
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failing. Stopping. Review with: git diff"; break
  }

  git add -u
  git commit -m "loop: iteration $i (auto)"
  Start-Sleep -Seconds $SleepSeconds
}