$ErrorActionPreference = 'Stop'

# Use the same per-user Python installs as BeeRef-hidden.cmd, since the
# python.exe on PATH may be a different install without PyQt6.
$python = $null
foreach ($version in '312', '311', '310') {
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"
    if (-not $python -and (Test-Path $candidate)) {
        $python = $candidate
    }
}
if (-not $python) {
    $python = 'python'
}

$username = Read-Host 'Phone upload username'
$securePassword = Read-Host 'Phone upload password' -AsSecureString
$secureRepeat = Read-Host 'Repeat password' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$repeatPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureRepeat)
# Run from the repository so Python imports this checkout's beeref package.
Push-Location $PSScriptRoot
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $plainRepeat = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($repeatPointer)
    if ($plainPassword -cne $plainRepeat) {
        throw 'Passwords do not match; the phone login was not changed.'
    }
    $env:REFERENCES_PHONE_USERNAME = $username
    $env:REFERENCES_PHONE_PASSWORD = $plainPassword
    @'
import os
from beeref.phone_receiver import save_login
save_login(os.environ['REFERENCES_PHONE_USERNAME'],
           os.environ['REFERENCES_PHONE_PASSWORD'])
print('References phone login updated.')
'@ | & $python -
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not save the phone login (exit code $LASTEXITCODE)."
    }
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($repeatPointer)
    Remove-Item Env:REFERENCES_PHONE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:REFERENCES_PHONE_USERNAME -ErrorAction SilentlyContinue
    Pop-Location
}
