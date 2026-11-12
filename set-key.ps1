# Saves your Gnani API key into .env (in this folder) without showing it on screen.
# Run from the ASHA-VoiceMate folder:   & .\set-key.ps1
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile }

$secure = Read-Host "Paste your Gnani API key (it will be hidden) and press Enter" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim().Trim('"', "'") }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if ([string]::IsNullOrWhiteSpace($key)) { Write-Host "No key entered. Nothing was changed." -ForegroundColor Yellow; exit 1 }

$found = $false
$lines = foreach ($line in [IO.File]::ReadAllLines($envFile)) {
    if ($line -like "GNANI_API_KEY=*") { $found = $true; "GNANI_API_KEY=" + $key } else { $line }
}
if (-not $found) { $lines = @($lines) + ("GNANI_API_KEY=" + $key) }
[IO.File]::WriteAllLines($envFile, [string[]]$lines)   # UTF-8 without BOM
Remove-Variable key
Write-Host "Saved the Gnani API key to .env. You can close this tab and tell Claude 'done'." -ForegroundColor Green
