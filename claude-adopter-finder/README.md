# Claude Adopter Finder

MCP server that finds companies using Claude Desktop/Code by scanning multiple sources: GitHub, Hacker News, npm, PyPI, LinkedIn, news, and job postings.

## Quick Start (5 minutes)

### 1. Get API Keys

**GitHub (REQUIRED - FREE):**
- Go to https://github.com/settings/tokens
- Create a new token (classic) with `public_repo` and `read:org` scopes
- This is all you need to get started!

**Brave Search (OPTIONAL - FREE tier: 2000 queries/month):**
- Go to https://brave.com/search/api/
- Sign up for free tier
- Adds: LinkedIn posts, news articles, engineering blog search

**TheirStack (OPTIONAL - for job posting search):**
- Go to https://theirstack.com
- Sign up and get an API key
- Pricing: ~$299/month
- Skip this for now - other sources work great!

**FREE APIs (no key needed):**
- Hacker News (Algolia API)
- npm Registry
- PyPI

**LinkedIn MCP (OPTIONAL - requires session cookie):**
- Direct LinkedIn scraping for profiles, companies, and jobs
- See [LinkedIn MCP Setup](#linkedin-mcp-setup) below

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

### Quick Company Check
> "Does Stripe use Claude?"

Runs `does_company_use_claude` - fast check for a single company.

### Full Multi-Source Scan (NEW)
> "Run a full multi-source scan for Vercel"

Runs `full_multi_source_scan` - scans ALL sources (GitHub, HN, npm, PyPI, LinkedIn, news) and returns a confidence score.

### Find Companies via GitHub
> "Search GitHub for organizations using Claude Code"

Runs `find_claude_companies_github` - finds repos with MCP configs, Anthropic SDK usage, etc.

### Find Companies via Job Postings
> "Find mid-market companies hiring for Claude skills in the last 30 days"

Runs `find_claude_companies_jobs` - searches job postings for Claude/Anthropic mentions. (Requires TheirStack API)

### Search Hacker News (NEW - FREE)
> "Search Hacker News for discussions about Notion using Claude"

Runs `search_hackernews_signals` - finds HN posts and comments mentioning company + Claude.

### Check npm Packages (NEW - FREE)
> "Check if Vercel has npm packages using Anthropic SDK"

Runs `check_npm_anthropic_usage` - very high confidence signal when company publishes packages with Anthropic dependencies.

### Check PyPI Packages (NEW - FREE)
> "Check if OpenAI has PyPI packages using anthropic"

Runs `check_pypi_anthropic_usage` - same as npm but for Python packages.

### Search Web (LinkedIn, News, Blogs) (NEW)
> "Search for LinkedIn posts and news about Stripe using Claude"

Runs `search_web_signals` - searches LinkedIn posts, news articles, and engineering blogs. (Requires free Brave API key)

### Batch Check Companies
> "Check which of these companies use Claude: Stripe, Vercel, Shopify, Netflix"

Runs `batch_check_companies` - check multiple companies at once for CRM enrichment.

### CRM Integration
> "Get my HubSpot companies and check which use Claude"

Runs `check_companies_from_crm` - enriches CRM data with Claude usage signals.

### Analyze Specific Org
> "Analyze Stripe's GitHub for Claude usage"

Runs `analyze_org_claude_usage` - deep dive into a specific org's Claude signals.

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

## Signal Confidence Levels & Scoring

The `full_multi_source_scan` tool uses weighted scoring:

| Signal | Weight | Confidence |
|--------|--------|------------|
| MCP config in GitHub | 40 pts | Very High |
| npm package with @anthropic-ai/sdk | 35 pts | Very High |
| PyPI package with anthropic | 35 pts | Very High |
| Anthropic SDK usage in code | 30 pts | High |
| Engineering blog post | 30 pts | High |
| LinkedIn employee post | 25 pts | High |
| API key reference | 25 pts | High |
| Job posting mention | 20 pts | High |
| News article | 20 pts | Medium |
| Hacker News mention | 15 pts | Medium |

**Verdict Thresholds:**
- **Very High (60+ pts)**: Multiple strong signals - definitely using Claude
- **High (40-59 pts)**: At least one strong signal - likely using Claude
- **Medium (20-39 pts)**: Some signals - possibly using Claude
- **Low (<20 pts)**: Weak or no signals

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Claude Desktop                        │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │           claude-adopter-finder MCP                │  │
│  │                                                    │  │
│  │  Core Tools:                                       │  │
│  │  • full_multi_source_scan    (aggregated scan)    │  │
│  │  • does_company_use_claude   (quick check)        │  │
│  │  • batch_check_companies     (CRM enrichment)     │  │
│  │                                                    │  │
│  │  Signal Sources:                                   │  │
│  │  • search_hackernews_signals (FREE)               │  │
│  │  • check_npm_anthropic_usage (FREE)               │  │
│  │  • check_pypi_anthropic_usage (FREE)              │  │
│  │  • search_web_signals        (Brave API)          │  │
│  │  • find_claude_companies_github (GitHub API)      │  │
│  │  • find_claude_companies_jobs (TheirStack)        │  │
│  └────────────────────────────────────────────────────┘  │
│           │         │         │         │                │
│           ▼         ▼         ▼         ▼                │
│    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │
│    │ GitHub │ │  HN    │ │  npm   │ │ Brave  │          │
│    │  API   │ │Algolia │ │ PyPI   │ │ Search │          │
│    │ (FREE) │ │ (FREE) │ │ (FREE) │ │ (FREE) │          │
│    └────────┘ └────────┘ └────────┘ └────────┘          │
└──────────────────────────────────────────────────────────┘
```

## LinkedIn MCP Setup

The LinkedIn MCP server ([stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server)) provides direct LinkedIn scraping for:
- **Profile scraping** - Get detailed info from LinkedIn profiles
- **Company analysis** - Extract company information
- **Job search** - Search jobs with filters
- **Job details** - Get specific job posting info

### Step 1: Get Your LinkedIn Cookie

1. Open Chrome and log into LinkedIn
2. Press F12 to open DevTools
3. Go to **Application** → **Storage** → **Cookies** → `https://www.linkedin.com`
4. Find the cookie named `li_at` and copy its value
5. The cookie looks like: `AQEDAT...` (long string)

> ⚠️ Cookie expires in ~30 days. Refresh when needed.

### Step 2: Add to Claude Desktop Config

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claude-adopter-finder": {
      "command": "/Users/adriandelasierra/.local/bin/uv",
      "args": [
        "run", "--directory",
        "/Users/adriandelasierra/Desktop/desktop/innovation/ricky/claude-adopter-finder",
        "python", "-m", "src.combined_scanner"
      ]
    },
    "linkedin": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/stickerdaniel/linkedin-mcp-server",
        "linkedin-mcp-server"
      ],
      "env": {
        "LINKEDIN_COOKIE": "li_at=YOUR_COOKIE_HERE"
      }
    }
  }
}
```

### Step 3: Restart Claude Desktop

Quit and reopen Claude Desktop. You now have both MCPs available.

### LinkedIn MCP Tools

Once configured, you can ask Claude:

| Prompt | Tool Used |
|--------|-----------|
| "Get the profile of this person: linkedin.com/in/username" | `get_person_profile` |
| "Get company info for Stripe from LinkedIn" | `get_company_profile` |
| "Search LinkedIn jobs for 'AI Engineer' in San Francisco" | `search_jobs` |
| "Get details for this job posting: linkedin.com/jobs/view/123" | `get_job_details` |

### Combined Workflow Example

```
You: Find companies using Claude, then get their LinkedIn company profiles

Claude: [Uses claude-adopter-finder to find companies]
        Found 15 companies with Claude signals...

        [Uses linkedin MCP to get company profiles]
        Here's detailed info for each company from LinkedIn...
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
