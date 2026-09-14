param(
    [int]$Port = 7862
)

$ownerIds = @(
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.OwningProcess }
)
if ($ownerIds.Count -eq 0) {
    $pattern = ":$Port\s+.*LISTENING\s+(\d+)\s*$"
    $ownerIds = @(
        netstat.exe -ano -p tcp |
            ForEach-Object {
                if ($_ -match $pattern) { [int]$Matches[1] }
            }
    )
}
$ownerIds = @($ownerIds | Sort-Object -Unique)
if ($ownerIds.Count -eq 0) {
    Write-Output "Speaker Training GUI is not listening on port $Port."
    exit 0
}

$stopped = 0
foreach ($processId in $ownerIds) {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($null -eq $processInfo) {
        Write-Error "Could not inspect PID $processId; refusing to stop an unverified process."
        continue
    }
    $commandLine = [string]$processInfo.CommandLine
    if ($commandLine -notmatch '(?i)speaker_training_gui\.py') {
        Write-Error "PID $processId owns port $Port but is not Speaker Training GUI; refusing to stop it."
        continue
    }
    Stop-Process -Id $processId -Force -ErrorAction Stop
    Write-Output "Stopped Speaker Training GUI PID $processId."
    $stopped++
}

if ($stopped -eq 0) {
    exit 1
}
exit 0
