$env:MSYSTEM = $null
$env:MSYS = $null
$env:MINGW = $null

. "C:\Espressif\tools\Microsoft.v6.0.PowerShell_profile.ps1"

$exampleDir = "D:\espidf\v6.0\esp-idf\examples\peripherals\camera\mipi_isp_dsi"
Set-Location $exampleDir
if (Test-Path build) { Remove-Item -Recurse -Force build }

# set-target
Write-Host "=== Setting target to esp32p4 ==="
& idf.py set-target esp32p4 2>&1 | ForEach-Object { Write-Host $_ }

# build
Write-Host "=== Building ==="
& idf.py build 2>&1 | ForEach-Object { Write-Host $_ }

