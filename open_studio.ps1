param([string]$Scene = '')
Set-Location -LiteralPath $PSScriptRoot
if ($Scene) {
    uv run python -m studio.app $Scene
} else {
    uv run python -m studio.app
}
