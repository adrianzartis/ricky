"""
GitHub Signal Scanner MCP
Finds companies/orgs using Claude by scanning GitHub for code signals.
"""

import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    "Claude Adopter Scanner - GitHub",
    instructions="Scan GitHub for companies using Claude/Anthropic",
)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API = "https://api.github.com"


def get_headers():
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


@mcp.tool()
async def search_claude_code(
    search_type: str = "all",
    limit: int = 50,
) -> dict:
    """
    Search GitHub for code containing Claude/Anthropic signals.

    Args:
        search_type: One of "all", "api_keys", "mcp_configs", "sdk_usage", "github_actions"
        limit: Max results per query (GitHub limits to 100)

    Returns:
        Repositories and organizations with Claude signals
    """
    if not GITHUB_TOKEN:
        return {
            "error": "GITHUB_TOKEN not set. Get one at https://github.com/settings/tokens",
            "note": "Without a token, you're limited to 10 requests/minute",
            "repos": [],
        }

    # Define search queries based on type
    queries = {
        "api_keys": [
            "ANTHROPIC_API_KEY in:file",
            "ANTHROPIC_BASE_URL in:file",
        ],
        "mcp_configs": [
            "filename:.mcp.json",
            "filename:mcp.json mcpServers",
        ],
        "sdk_usage": [
            '"@anthropic-ai/sdk" in:file extension:json',
            '"from anthropic import" in:file extension:py',
            '"import Anthropic" in:file extension:ts',
        ],
        "github_actions": [
            "anthropics/claude-code-action in:file",
            "claude-code-base-action in:file",
        ],
    }

    if search_type == "all":
        search_queries = []
        for q_list in queries.values():
            search_queries.extend(q_list)
    elif search_type in queries:
        search_queries = queries[search_type]
    else:
        return {"error": f"Invalid search_type. Use one of: all, {', '.join(queries.keys())}"}

    all_repos = []
    orgs_seen = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in search_queries:
            try:
                response = await client.get(
                    f"{GITHUB_API}/search/code",
                    params={"q": query, "per_page": min(limit, 100)},
                    headers=get_headers(),
                )

                if response.status_code == 403:
                    return {
                        "error": "GitHub API rate limit exceeded. Try again later or use a token.",
                        "repos": all_repos,
                    }

                if response.status_code != 200:
                    continue

                data = response.json()

                for item in data.get("items", []):
                    repo = item.get("repository", {})
                    owner = repo.get("owner", {})

                    repo_info = {
                        "repo_name": repo.get("full_name"),
                        "repo_url": repo.get("html_url"),
                        "owner_name": owner.get("login"),
                        "owner_type": owner.get("type"),  # User or Organization
                        "file_matched": item.get("path"),
                        "query_matched": query,
                        "signal_type": search_type if search_type != "all" else categorize_query(query),
                    }

                    # Track organizations
                    if owner.get("type") == "Organization":
                        org_login = owner.get("login")
                        if org_login not in orgs_seen:
                            orgs_seen[org_login] = {
                                "name": org_login,
                                "url": f"https://github.com/{org_login}",
                                "repos_with_signals": [],
                            }
                        orgs_seen[org_login]["repos_with_signals"].append(repo.get("full_name"))

                    all_repos.append(repo_info)

            except httpx.TimeoutException:
                continue

    # Dedupe repos
    seen_repos = set()
    unique_repos = []
    for repo in all_repos:
        if repo["repo_name"] not in seen_repos:
            seen_repos.add(repo["repo_name"])
            unique_repos.append(repo)

    return {
        "total_repos": len(unique_repos),
        "total_organizations": len(orgs_seen),
        "organizations": list(orgs_seen.values()),
        "repos": unique_repos[:limit],
    }


def categorize_query(query: str) -> str:
    if "ANTHROPIC_API_KEY" in query or "ANTHROPIC_BASE_URL" in query:
        return "api_keys"
    if ".mcp.json" in query or "mcpServers" in query:
        return "mcp_configs"
    if "anthropic-ai/sdk" in query or "from anthropic" in query or "import Anthropic" in query:
        return "sdk_usage"
    if "claude-code-action" in query:
        return "github_actions"
    return "other"


@mcp.tool()
async def search_mcp_repos(
    min_stars: int = 0,
    limit: int = 50,
) -> dict:
    """
    Search specifically for repos with MCP configurations.
    Very high signal for Claude usage as MCP is Anthropic-specific.

    Args:
        min_stars: Minimum stars (0 = include private-looking repos)
        limit: Max results

    Returns:
        Repos with MCP configurations
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required for code search"}

    queries = [
        "filename:.mcp.json",
        "filename:mcp.json mcpServers",
        '"mcpServers" in:file extension:json',
    ]

    repos = []
    seen = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            if min_stars > 0:
                query += f" stars:>={min_stars}"

            response = await client.get(
                f"{GITHUB_API}/search/code",
                params={"q": query, "per_page": limit},
                headers=get_headers(),
            )

            if response.status_code != 200:
                continue

            data = response.json()

            for item in data.get("items", []):
                repo = item.get("repository", {})
                repo_name = repo.get("full_name")

                if repo_name and repo_name not in seen:
                    seen.add(repo_name)
                    owner = repo.get("owner", {})

                    repos.append({
                        "repo": repo_name,
                        "url": repo.get("html_url"),
                        "owner": owner.get("login"),
                        "owner_type": owner.get("type"),
                        "config_file": item.get("path"),
                        "description": repo.get("description"),
                        "confidence": "very_high",
                        "signal": "MCP configuration file found",
                    })

    return {
        "total_repos": len(repos),
        "note": ".mcp.json files indicate active Claude Code/Desktop usage",
        "repos": repos,
    }


@mcp.tool()
async def get_org_claude_usage(
    org_name: str,
) -> dict:
    """
    Analyze a specific GitHub organization for Claude/Anthropic usage signals.

    Args:
        org_name: GitHub organization name (e.g., 'stripe', 'vercel')

    Returns:
        Analysis of Claude signals in the org's public repos
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required"}

    signals = {
        "mcp_configs": [],
        "anthropic_sdk": [],
        "api_keys": [],
        "github_actions": [],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search within the org
        search_queries = [
            (f"org:{org_name} filename:.mcp.json", "mcp_configs"),
            (f"org:{org_name} ANTHROPIC_API_KEY in:file", "api_keys"),
            (f'org:{org_name} "@anthropic-ai/sdk" in:file', "anthropic_sdk"),
            (f"org:{org_name} claude-code-action in:file", "github_actions"),
        ]

        for query, signal_type in search_queries:
            response = await client.get(
                f"{GITHUB_API}/search/code",
                params={"q": query, "per_page": 30},
                headers=get_headers(),
            )

            if response.status_code == 200:
                data = response.json()
                for item in data.get("items", []):
                    signals[signal_type].append({
                        "repo": item.get("repository", {}).get("full_name"),
                        "file": item.get("path"),
                        "url": item.get("html_url"),
                    })

        # Get org info
        org_response = await client.get(
            f"{GITHUB_API}/orgs/{org_name}",
            headers=get_headers(),
        )

        org_info = {}
        if org_response.status_code == 200:
            org_data = org_response.json()
            org_info = {
                "name": org_data.get("name"),
                "company": org_data.get("company"),
                "blog": org_data.get("blog"),
                "location": org_data.get("location"),
                "public_repos": org_data.get("public_repos"),
                "followers": org_data.get("followers"),
            }

    total_signals = sum(len(v) for v in signals.values())

    return {
        "organization": org_name,
        "org_info": org_info,
        "total_claude_signals": total_signals,
        "has_claude_usage": total_signals > 0,
        "confidence": "high" if total_signals > 2 else "medium" if total_signals > 0 else "none",
        "signals": signals,
    }


@mcp.tool()
async def find_claude_action_users(
    limit: int = 50,
) -> dict:
    """
    Find organizations/repos using Claude Code GitHub Actions.
    This is a strong signal of enterprise Claude Code adoption.

    Returns:
        Repos using Claude Code in CI/CD pipelines
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required"}

    queries = [
        "anthropics/claude-code-action in:file path:.github/workflows",
        "anthropic_api_key in:file path:.github/workflows",
    ]

    repos = []
    seen = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in queries:
            response = await client.get(
                f"{GITHUB_API}/search/code",
                params={"q": query, "per_page": limit},
                headers=get_headers(),
            )

            if response.status_code != 200:
                continue

            data = response.json()

            for item in data.get("items", []):
                repo = item.get("repository", {})
                repo_name = repo.get("full_name")

                if repo_name and repo_name not in seen:
                    seen.add(repo_name)
                    owner = repo.get("owner", {})

                    repos.append({
                        "repo": repo_name,
                        "url": repo.get("html_url"),
                        "owner": owner.get("login"),
                        "owner_type": owner.get("type"),
                        "workflow_file": item.get("path"),
                        "confidence": "very_high",
                        "signal": "Claude Code GitHub Action in CI/CD",
                    })

    # Separate orgs from users
    orgs = [r for r in repos if r["owner_type"] == "Organization"]
    users = [r for r in repos if r["owner_type"] == "User"]

    return {
        "total_repos": len(repos),
        "organizations": len(orgs),
        "note": "GitHub Actions usage indicates production Claude Code deployment",
        "org_repos": orgs,
        "user_repos": users[:10],  # Limit individual users
    }


if __name__ == "__main__":
    mcp.run()
