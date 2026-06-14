@echo off
:: ============================================================
::  review.bat — Launch Claude Code with Anthropic backend
::  Automatically passes the latest git diff for review
::  Usage: review.bat [optional extra instructions]
::  Example: review.bat "focus on error handling"
:: ============================================================

:: ── API credentials ─────────────────────────────────────────
:: Replace with your actual Anthropic API key
:: Get one at: https://console.anthropic.com/settings/keys
set ANTHROPIC_AUTH_TOKEN=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

:: ── Clear DeepSeek overrides ─────────────────────────────────
set ANTHROPIC_BASE_URL=
set ANTHROPIC_MODEL=
set ANTHROPIC_DEFAULT_OPUS_MODEL=
set ANTHROPIC_DEFAULT_SONNET_MODEL=
set ANTHROPIC_DEFAULT_HAIKU_MODEL=
set CLAUDE_CODE_SUBAGENT_MODEL=
set CLAUDE_CODE_EFFORT_LEVEL=

:: ── Build the git diff context ───────────────────────────────
:: Captures what DeepSeek just committed
for /f "delims=" %%i in ('git diff HEAD~1 2^>nul') do set GIT_DIFF=%%i

:: Fallback: if no prior commit, use staged changes instead
if "%GIT_DIFF%"=="" (
    for /f "delims=" %%i in ('git diff --cached 2^>nul') do set GIT_DIFF=%%i
)

:: ── Launch ───────────────────────────────────────────────────
echo.
echo  [Claude] Backend: api.anthropic.com
echo  [Claude] Mode:    Architectural review
echo  [Claude] Context: latest git diff
echo.

:: If no diff found, launch normally and let user paste manually
if "%GIT_DIFF%"=="" (
    echo  [Claude] Warning: No git diff found. Launching without diff context.
    echo  Tip: Make sure DeepSeek has committed before running review.bat
    echo.
    if "%~1"=="" (
        claude
    ) else (
        claude "%~1"
    )
) else (
    :: Build review prompt with optional extra instructions
    if "%~1"=="" (
        claude "Review this code for architectural alignment, patterns, security, consistency and edge cases. Flag anything that should be changed and explain why.

Git diff from DeepSeek session:
%GIT_DIFF%"
    ) else (
        claude "Review this code for architectural alignment, patterns, security, consistency and edge cases. %~1

Git diff from DeepSeek session:
%GIT_DIFF%"
    )
)
