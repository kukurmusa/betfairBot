# DeepSeek + Claude Code launcher

Two batch files for running DeepSeek (generation) and Claude (review) as separate
backends within Claude Code — no restarts, no env var editing.

## Setup

1. Put `deepseek.bat` and `review.bat` somewhere on your PATH
   (e.g. `C:\Users\you\scripts\` and add that folder to PATH in System env vars)

2. Open `deepseek.bat` and replace `YOUR_DEEPSEEK_API_KEY_HERE` with your key
   from https://platform.deepseek.com/api_keys

3. Open `review.bat` and replace `YOUR_ANTHROPIC_API_KEY_HERE` with your key
   from https://console.anthropic.com/settings/keys

4. Copy `CLAUDE.md` into your project root (or `.claude/CLAUDE.md`)
   and fill in your architecture rules — both models read this automatically

## Daily workflow

```
# 1. Start a DeepSeek session for coding
deepseek

# 2. Give it your task inside Claude Code
# DeepSeek generates the code, you iterate

# 3. When done, commit inside Claude Code
#    git commit -m "feat: add auth middleware"

# 4. Exit Claude Code (Ctrl+C or /exit)

# 5. Switch to Claude for review — diff is passed automatically
review

# Optional: add extra review instructions
review "focus on error handling and test coverage"
```

## Before switching sessions

Update the `## Session notes` section in `CLAUDE.md` with what DeepSeek did.
This gives Claude the reasoning behind the changes, not just the diff.

```markdown
## Session notes
Date: 2026-06-14
Task: Auth middleware for /api/v2
Files changed: src/middleware/auth.ts, tests/auth.test.ts
DeepSeek notes: Used RS256 for JWT. Skipped refresh token (out of scope).
Review focus: JWT error handling, middleware ordering, test coverage
```

## Tips

- `deepseek.bat "your task here"` — pass a prompt directly at launch
- `review.bat "focus on X"` — add extra instructions to the review prompt
- The review bat auto-reads `git diff HEAD~1` — make sure DeepSeek has committed
- If no commit exists yet, it falls back to `git diff --cached` (staged changes)
- Keep `CLAUDE.md` updated with your arch rules — both models read it every session
