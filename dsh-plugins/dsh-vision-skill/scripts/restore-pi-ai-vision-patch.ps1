# Restore pi-ai vision placeholder patch (part B); preserves zen-ua patch (part A).
# Delegates to the Python implementation so exact byte/indent matching stays reliable.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here 'restore_pi_ai_vision_patch.py'
if (-not (Test-Path -LiteralPath $py)) { throw "FAIL: $py not found" }
python $py
