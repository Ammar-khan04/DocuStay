# Revert starry/cosmic theme - restore frontend files to pre-theme state (commit 9c6254d).
# Run from repo root: .\scripts\revert-starry-theme.ps1
# Prereq: git fetch origin; git checkout -b revert-starry-theme origin/main

$ErrorActionPreference = "Stop"
$preTheme = "9c6254d"
# Repo root = parent of folder containing this script (e.g. DocuStay when script is in DocuStay/scripts)
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$themeOnlyFiles = @(
    "frontend/components/AgreementSignModal.tsx",
    "frontend/components/AuthCardLayout.tsx",
    "frontend/components/HeroBackground.tsx",
    "frontend/components/InvitationsTabContent.tsx",
    "frontend/components/InviteRoleChoiceModal.tsx",
    "frontend/components/ModeSwitcher.tsx",
    "frontend/components/UI.tsx",
    "frontend/index.css",
    "frontend/pages/Auth/Login.tsx",
    "frontend/pages/Auth/RegisterOwner.tsx",
    "frontend/pages/Guest/SignAgreement.tsx",
    "frontend/pages/Landing.tsx",
    "frontend/pages/Support/HelpCenter.tsx"
)

$overlappingFiles = @(
    "frontend/App.tsx",
    "frontend/components/DashboardAlertsPanel.tsx",
    "frontend/pages/Guest/GuestDashboard.tsx",
    "frontend/pages/Owner/OwnerDashboard.tsx",
    "frontend/pages/Settings/Settings.tsx",
    "frontend/pages/Tenant/TenantDashboard.tsx"
)

# Pages that got cosmic theme in a later commit (not in original theme revert list)
$extraThemePages = @(
    "frontend/pages/LivePropertyPage.tsx",
    "frontend/pages/Verify/VerifyPage.tsx",
    "frontend/pages/PortfolioPage.tsx",
    "frontend/pages/Owner/PropertyDetail.tsx",
    "frontend/pages/Manager/ManagerPropertyDetail.tsx",
    "frontend/pages/Manager/ManagerDashboard.tsx",
    "frontend/pages/Admin/AdminDashboard.tsx"
)

$allFiles = $themeOnlyFiles + $overlappingFiles + $extraThemePages

Write-Host "Reverting theme: restoring $($allFiles.Count) files to $preTheme ..." -ForegroundColor Cyan
foreach ($f in $allFiles) {
    $path = Join-Path $root $f
    if (Test-Path $path) {
        git checkout $preTheme -- $f
        Write-Host "  OK $f" -ForegroundColor Green
    } else {
        Write-Host "  SKIP (not in working tree) $f" -ForegroundColor Yellow
    }
}

# Remove StarField (added by theme)
$starField = Join-Path $root "frontend/components/StarField.tsx"
if (Test-Path $starField) {
    Remove-Item $starField -Force
    Write-Host "  Removed frontend/components/StarField.tsx" -ForegroundColor Green
}

# Optional: revert lockfiles to avoid theme-only deps (uncomment if desired)
# git checkout $preTheme -- frontend/package-lock.json package-lock.json

Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Cyan
Write-Host "  1. Fix App.tsx: remove any leftover 'StarField' or 'view !== ''check''' if still present." -ForegroundColor White
Write-Host "  2. npm install (if you reverted lockfiles)." -ForegroundColor White
Write-Host "  3. Test the app (landing, login, dashboards, agreement modal)." -ForegroundColor White
Write-Host "  4. git add -A && git status && git commit -m ""Revert starry/cosmic theme - restore original frontend styling""" -ForegroundColor White
