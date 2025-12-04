# Claude Adopter Finder

MCP server that finds companies using Claude Desktop/Code by scanning job postings and GitHub.

## Quick Start (5 minutes)

### 1. Get API Keys

**GitHub (REQUIRED - FREE):**
- Go to https://github.com/settings/tokens
- Create a new token (classic) with `public_repo` and `read:org` scopes
- This is all you need to get started!

**TheirStack (OPTIONAL - for job posting search):**
- Go to https://theirstack.com
- Sign up and get an API key
- Pricing: ~$299/month
- Skip this for now - GitHub search works great alone!

### 2. Setup

```bash
cd /Users/adriandelasierra/Desktop/desktop/innovation/ricky/claude-adopter-finder

# Create .env file with your keys
cp .env.example .env
# Edit .env and add your API keys

# Install dependencies
uv sync
```

### 3. Add to Claude Desktop

Open Claude Desktop settings and add this MCP server:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "claude-adopter-finder": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Users/adriandelasierra/Desktop/desktop/innovation/ricky/claude-adopter-finder",
        "python",
        "-m",
        "src.combined_scanner"
      ],
      "env": {
        "THEIRSTACK_API_KEY": "your_key_here",
        "GITHUB_TOKEN": "your_token_here"
      }
    }
  }
}
```

### 4. Restart Claude Desktop

Quit and reopen Claude Desktop. You should see the MCP server connected.

## Available Tools

Once connected, you can ask Claude:

### Check Setup
> "Check if my Claude Adopter Finder APIs are working"

Runs `check_api_status` to verify your configuration.

### Find Companies via Job Postings
> "Find mid-market companies hiring for Claude skills in the last 30 days"

Runs `find_claude_companies_jobs` - searches job postings for Claude/Anthropic mentions.

### Find Companies via GitHub
> "Search GitHub for organizations using Claude Code"

Runs `find_claude_companies_github` - finds repos with MCP configs, Anthropic SDK usage, etc.

### Analyze Specific Org
> "Analyze Stripe's GitHub for Claude usage"

Runs `analyze_org_claude_usage` - deep dive into a specific org's Claude signals.

### Full Scan
> "Run a full scan for Claude-adopting companies"

Runs `full_claude_company_scan` - combines all sources for comprehensive results.

## Example Conversations

**Discovery:**
```
You: Find me all companies that mentioned Claude Code in job postings
     in the last 2 weeks, with 200-2000 employees

Claude: [Uses find_claude_companies_jobs with filters]
        Found 23 companies...
```

**Deep Dive:**
```
You: I see Acme Corp in the results. Can you check their GitHub
     for more Claude signals?

Claude: [Uses analyze_org_claude_usage]
        Acme Corp has 5 repos with MCP configs and uses
        Claude Code GitHub Actions in their CI...
```

**Export:**
```
You: Great, can you format the top 20 results as a CSV I can
     import into our CRM?

Claude: [Formats results as CSV]
```

## Signal Confidence Levels

- **Very High**: MCP configs, Claude Code GitHub Actions, explicit "Claude Code" in job posts
- **High**: Multiple signals from different sources, "Anthropic API" mentions
- **Medium**: Generic "Claude" mentions, SDK imports
- **Low**: Circumstantial signals

## Architecture

```
┌─────────────────────────────────────────┐
│           Claude Desktop                │
│                                         │
│  ┌───────────────────────────────────┐  │
│  │    claude-adopter-finder MCP      │  │
│  │                                   │  │
│  │  Tools:                           │  │
│  │  • find_claude_companies_jobs     │  │
│  │  • find_claude_companies_github   │  │
│  │  • analyze_org_claude_usage       │  │
│  │  • full_claude_company_scan       │  │
│  │  • check_api_status               │  │
│  └───────────────────────────────────┘  │
│           │               │             │
│           ▼               ▼             │
│    ┌──────────┐    ┌──────────┐        │
│    │TheirStack│    │ GitHub   │        │
│    │   API    │    │   API    │        │
│    └──────────┘    └──────────┘        │
└─────────────────────────────────────────┘
```

## Adding to Claude Code (CLI)

If using Claude Code instead of Claude Desktop:

```bash
claude mcp add claude-adopter-finder \
  --command "uv run --directory /Users/adriandelasierra/Desktop/desktop/innovation/ricky/claude-adopter-finder python -m src.combined_scanner"
```

## Future Enhancements

- [ ] News/press release scanner
- [ ] LinkedIn company page analyzer
- [ ] Automatic enrichment with Apollo.io
- [ ] Google Sheets export MCP
- [ ] Scheduled scans with alerts
