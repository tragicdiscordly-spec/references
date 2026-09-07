$ErrorActionPreference = 'Stop'
$username = Read-Host 'Phone upload username'
$securePassword = Read-Host 'Phone upload password' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $env:REFERENCES_PHONE_USERNAME = $username
    $env:REFERENCES_PHONE_PASSWORD = $plainPassword
    @'
import os
from beeref.phone_receiver import save_login
save_login(os.environ['REFERENCES_PHONE_USERNAME'],
           os.environ['REFERENCES_PHONE_PASSWORD'])
print('References phone login updated.')
'@ | python -
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    Remove-Item Env:REFERENCES_PHONE_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:REFERENCES_PHONE_USERNAME -ErrorAction SilentlyContinue
}
