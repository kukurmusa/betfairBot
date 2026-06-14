@echo off
:: ============================================================
::  deepseek.bat — Launch Claude Code with DeepSeek backend
::  Usage: deepseek.bat [optional prompt]
::  Example: deepseek.bat "Add auth middleware to /api/v2"
:: ============================================================

:: ── API credentials ─────────────────────────────────────────
:: Replace with your actual DeepSeek API key
:: Get one at: https://platform.deepseek.com/api_keys
set ANTHROPIC_AUTH_TOKEN=sk-d1bae125a57543cfafa3c2b94f3765f6

:: ── DeepSeek endpoint (Anthropic-compatible) ─────────────────
set ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic

:: ── Model routing ────────────────────────────────────────────
:: Main model: DeepSeek V4 Pro with 1M context
set ANTHROPIC_MODEL=deepseek-v4-pro[1m]
set ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro[1m]
set ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro[1m]

:: Sub-agent model: DeepSeek V4 Flash (fast + cheap for sub-tasks)
set ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash
set CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash

:: ── Effort level ─────────────────────────────────────────────
set CLAUDE_CODE_EFFORT_LEVEL=max

:: ── Launch ───────────────────────────────────────────────────
echo.
echo  [DeepSeek] Backend: api.deepseek.com
echo  [DeepSeek] Model:   deepseek-v4-pro[1m]
echo  [DeepSeek] Sub:     deepseek-v4-flash
echo.

:: If a prompt was passed as argument, use it directly
if "%~1"=="" (
    claude
) else (
    claude "%~1"
)
