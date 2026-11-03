# Call the deployed AI+ service. No application is installed or run here.
$ErrorActionPreference = 'Stop'
$serviceUrl = '__SERVICE_URL__'
$operation = '__OPERATION__'
# Keep this UUID if retrying a submission after a network timeout.
$requestId = [guid]::NewGuid().ToString()
$payload = __PAYLOAD__
$payload.request_id = $requestId
Write-Host ('Request ID: ' + $requestId)
$secureKey = Read-Host 'Paste your AI_PLUS_API_KEY from Render' -AsSecureString
$plainKey = [System.Net.NetworkCredential]::new('', $secureKey).Password
$headers = @{ Authorization = 'Bearer ' + $plainKey }
$plainKey = $null
try {
    # This request can use Fireworks tokens and, when required, Modal GPU time.
    $job = Invoke-RestMethod -Method Post -Uri ($serviceUrl + '/api/v1/' + $operation) -Headers $headers -ContentType 'application/json' -Body ($payload | ConvertTo-Json -Depth 30) -TimeoutSec 30
    $jobUrl = $serviceUrl + '/api/v1/jobs/' + $job.id
    Write-Host ('Job: ' + $jobUrl)
    $deadline = (Get-Date).AddMinutes(8)
    while ($job.status -in @('running', 'queued')) {
        if ((Get-Date) -gt $deadline) { throw ('Polling stopped. Retrieve the same job later: ' + $jobUrl) }
        Start-Sleep -Seconds 2
        try {
            $job = Invoke-RestMethod -Method Get -Uri $jobUrl -Headers $headers -TimeoutSec 30
        } catch {
            $response = $_.Exception.Response
            if ($null -ne $response -and [int]$response.StatusCode -eq 429) {
                Start-Sleep -Seconds 10
                continue
            }
            throw
        }
    }
    $job | ConvertTo-Json -Depth 100
    if ($job.status -ne 'completed') { throw ('Job ended with status: ' + $job.status) }
    if ($operation -eq 'compare') {
        Write-Host 'Check both engines: a completed comparison can contain a failed model response.'
    }
} finally {
    $headers.Clear()
    $secureKey = $null
}
