param(
    [switch]$Dev,
    [switch]$Open
)

$ErrorActionPreference = "Stop"
$python = "python"
$argsList = @("scripts/run.py")
if ($Dev) { $argsList += "--dev" }
if ($Open) { $argsList += "--open" }

& $python @argsList
