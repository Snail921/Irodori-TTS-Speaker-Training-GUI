param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$TimeoutSeconds = 180
)

for ($attempt = 0; $attempt -lt $TimeoutSeconds; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Start-Process $Url
            exit 0
        }
    }
    catch {
        # The local service is still starting.
    }

    Start-Sleep -Seconds 1
}

exit 1
