"""
Combined Claude Adopter Scanner MCP
Single MCP with all tools for finding companies using Claude Desktop/Code.
"""

import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    "Claude Adopter Finder",
    instructions="Find companies using Claude Desktop/Code via job postings, GitHub, and web signals",
)

# API Keys
THEIRSTACK_API_KEY = os.getenv("THEIRSTACK_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
LINKEDIN_COOKIE = os.getenv("LINKEDIN_COOKIE")  # li_at cookie value

# Constants
THEIRSTACK_BASE_URL = "https://api.theirstack.com/v1"
GITHUB_API = "https://api.github.com"
HN_ALGOLIA_API = "https://hn.algolia.com/api/v1"
NPM_REGISTRY_API = "https://registry.npmjs.org"
PYPI_API = "https://pypi.org/pypi"
BRAVE_SEARCH_API = "https://api.search.brave.com/res/v1"
LINKEDIN_API = "https://www.linkedin.com/voyager/api"

# Signal weights for multi-source scoring
SIGNAL_WEIGHTS = {
    "github_mcp_config": 40,
    "github_anthropic_sdk": 30,
    "github_api_key": 25,
    "npm_anthropic_dep": 35,
    "pypi_anthropic_dep": 35,
    "linkedin_post": 25,
    "linkedin_job": 25,
    "engineering_blog": 30,
    "news_article": 20,
    "hackernews_mention": 15,
    "job_posting": 20,
}


# ============ LINKEDIN HELPERS ============

def get_linkedin_headers() -> dict:
    """Get headers for LinkedIn Voyager API calls."""
    if not LINKEDIN_COOKIE:
        return {}

    # Extract JSESSIONID from cookie if present, or generate csrf token
    cookie = LINKEDIN_COOKIE
    if not cookie.startswith("li_at="):
        cookie = f"li_at={cookie}"

    return {
        "cookie": f"{cookie}; JSESSIONID=ajax:0000000000000000000",
        "csrf-token": "ajax:0000000000000000000",
        "x-li-lang": "en_US",
        "x-li-track": '{"clientVersion":"1.0.0"}',
        "x-restli-protocol-version": "2.0.0",
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

CLAUDE_KEYWORDS = [
    "Claude",
    "Anthropic",
    "Claude Code",
    "Claude Desktop",
    "MCP",
    "Model Context Protocol",
]

HIGH_CONFIDENCE_KEYWORDS = [
    "Claude Code",
    "Claude Desktop",
    "Anthropic API",
    "Model Context Protocol",
]


# ============ JOB POSTING TOOLS ============

@mcp.tool()
async def find_claude_companies_jobs(
    days_back: int = 30,
    min_employees: int = 50,
    max_employees: int = 10000,
    countries: list[str] | None = None,
) -> dict:
    """
    Find companies mentioning Claude/Anthropic in job postings.
    Best for discovering mid-market and enterprise adopters.
    REQUIRES: TheirStack API key (optional - skip if not configured)

    Args:
        days_back: How many days back to search (default 30)
        min_employees: Minimum company size (default 50)
        max_employees: Maximum company size (default 10000)
        countries: Filter by country codes (e.g., ["US", "GB", "DE"])

    Returns:
        Companies with Claude signals in their job postings
    """
    if not THEIRSTACK_API_KEY:
        return {
            "status": "skipped",
            "reason": "TheirStack API not configured (optional)",
            "setup": "To enable job posting search, get API key at https://theirstack.com",
            "alternative": "Use find_claude_companies_github instead (free)",
            "companies": [],
        }

    posted_after = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    payload = {
        "job_description_pattern_or": CLAUDE_KEYWORDS,
        "posted_at_gte": posted_after,
        "company_num_employees_min": min_employees,
        "company_num_employees_max": max_employees,
        "limit": 100,
        "order_by": [{"field": "date_posted", "desc": True}],
    }

    if countries:
        payload["job_country_code_or"] = countries

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{THEIRSTACK_BASE_URL}/jobs/search",
            headers={
                "Authorization": f"Bearer {THEIRSTACK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        if response.status_code != 200:
            return {"error": f"API error: {response.status_code}", "details": response.text}

        data = response.json()

    # Process results
    companies = {}
    for job in data.get("data", []):
        domain = job.get("company_domain", "unknown")

        # Check confidence
        text = f"{job.get('job_title', '')} {job.get('job_description', '')}".lower()
        confidence = "medium"
        matched = []

        for kw in HIGH_CONFIDENCE_KEYWORDS:
            if kw.lower() in text:
                confidence = "high"
                matched.append(kw)

        if not matched:
            for kw in CLAUDE_KEYWORDS:
                if kw.lower() in text:
                    matched.append(kw)

        if domain not in companies:
            companies[domain] = {
                "name": job.get("company_name"),
                "domain": domain,
                "employees": job.get("company_num_employees"),
                "industry": job.get("company_industry"),
                "country": job.get("company_country"),
                "linkedin": job.get("company_linkedin_url"),
                "jobs": [],
                "keywords": set(),
                "confidence": confidence,
            }

        companies[domain]["jobs"].append({
            "title": job.get("job_title"),
            "url": job.get("job_url"),
            "posted": job.get("date_posted"),
        })
        companies[domain]["keywords"].update(matched)

        if confidence == "high":
            companies[domain]["confidence"] = "high"

    # Format output
    results = []
    for c in companies.values():
        c["keywords"] = list(c["keywords"])
        c["job_count"] = len(c["jobs"])
        results.append(c)

    # Sort by confidence then job count
    results.sort(key=lambda x: (x["confidence"] == "high", x["job_count"]), reverse=True)

    return {
        "found": len(results),
        "high_confidence": len([r for r in results if r["confidence"] == "high"]),
        "companies": results,
    }


# ============ GITHUB TOOLS ============

@mcp.tool()
async def find_claude_companies_github(
    search_scope: str = "all",
) -> dict:
    """
    Find companies/orgs using Claude by searching GitHub code.
    Looks for API keys, MCP configs, SDK usage, and GitHub Actions.

    Args:
        search_scope: "all", "mcp_configs", "sdk_usage", or "github_actions"

    Returns:
        Organizations and repos with Claude code signals
    """
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    else:
        return {
            "warning": "No GITHUB_TOKEN - rate limited to 10 requests/min",
            "setup": "Create token at https://github.com/settings/tokens",
        }

    queries = {
        "mcp_configs": ["filename:.mcp.json", "filename:mcp.json mcpServers"],
        "sdk_usage": [
            '"@anthropic-ai/sdk" in:file extension:json',
            '"from anthropic import" in:file extension:py',
        ],
        "github_actions": [
            "anthropics/claude-code-action path:.github/workflows",
        ],
        "api_keys": ["ANTHROPIC_API_KEY in:file"],
    }

    if search_scope == "all":
        all_queries = []
        for qs in queries.values():
            all_queries.extend(qs)
    elif search_scope in queries:
        all_queries = queries[search_scope]
    else:
        return {"error": f"Invalid scope. Use: all, {', '.join(queries.keys())}"}

    repos = []
    orgs = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in all_queries:
            response = await client.get(
                f"{GITHUB_API}/search/code",
                params={"q": query, "per_page": 50},
                headers=headers,
            )

            if response.status_code == 403:
                return {"error": "Rate limited. Wait or add GITHUB_TOKEN."}
            if response.status_code != 200:
                continue

            for item in response.json().get("items", []):
                repo = item.get("repository", {})
                owner = repo.get("owner", {})

                repos.append({
                    "repo": repo.get("full_name"),
                    "url": repo.get("html_url"),
                    "owner": owner.get("login"),
                    "owner_type": owner.get("type"),
                    "file": item.get("path"),
                    "signal": query.split()[0],
                })

                if owner.get("type") == "Organization":
                    org = owner.get("login")
                    if org not in orgs:
                        orgs[org] = {"name": org, "repos": []}
                    if repo.get("full_name") not in orgs[org]["repos"]:
                        orgs[org]["repos"].append(repo.get("full_name"))

    # Dedupe
    seen = set()
    unique_repos = []
    for r in repos:
        if r["repo"] not in seen:
            seen.add(r["repo"])
            unique_repos.append(r)

    return {
        "repos_found": len(unique_repos),
        "orgs_found": len(orgs),
        "organizations": [{"name": k, "repo_count": len(v["repos"]), "repos": v["repos"]}
                         for k, v in orgs.items()],
        "sample_repos": unique_repos[:30],
    }


@mcp.tool()
async def analyze_org_claude_usage(org_name: str) -> dict:
    """
    Deep-dive into a specific GitHub org's Claude/Anthropic usage.

    Args:
        org_name: GitHub organization name (e.g., 'stripe', 'vercel')

    Returns:
        Detailed analysis of Claude signals in the org
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required for org analysis"}

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    signals = {"mcp": [], "sdk": [], "actions": [], "api_keys": []}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search within org
        searches = [
            (f"org:{org_name} filename:.mcp.json", "mcp"),
            (f'org:{org_name} "@anthropic-ai/sdk"', "sdk"),
            (f"org:{org_name} claude-code-action path:.github", "actions"),
            (f"org:{org_name} ANTHROPIC_API_KEY", "api_keys"),
        ]

        for query, signal_type in searches:
            resp = await client.get(
                f"{GITHUB_API}/search/code",
                params={"q": query, "per_page": 20},
                headers=headers,
            )
            if resp.status_code == 200:
                for item in resp.json().get("items", []):
                    signals[signal_type].append({
                        "repo": item.get("repository", {}).get("full_name"),
                        "file": item.get("path"),
                    })

        # Get org info
        org_resp = await client.get(f"{GITHUB_API}/orgs/{org_name}", headers=headers)
        org_info = {}
        if org_resp.status_code == 200:
            d = org_resp.json()
            org_info = {
                "name": d.get("name"),
                "blog": d.get("blog"),
                "public_repos": d.get("public_repos"),
            }

    total = sum(len(v) for v in signals.values())

    return {
        "org": org_name,
        "info": org_info,
        "total_signals": total,
        "using_claude": total > 0,
        "confidence": "high" if total > 2 else "medium" if total > 0 else "none",
        "breakdown": {k: len(v) for k, v in signals.items()},
        "details": signals,
    }


# ============ COMBINED SEARCH ============

@mcp.tool()
async def full_claude_company_scan(
    days_back: int = 30,
    min_employees: int = 100,
    include_github: bool = True,
) -> dict:
    """
    Run a comprehensive scan for Claude-adopting companies across all sources.
    Combines job posting and GitHub signals.

    Args:
        days_back: Days back for job search
        min_employees: Minimum company size
        include_github: Whether to include GitHub search

    Returns:
        Combined results from all sources with deduplication
    """
    results = {
        "job_signals": {},
        "github_signals": {},
        "combined_companies": [],
    }

    # Job posting search
    if THEIRSTACK_API_KEY:
        job_results = await find_claude_companies_jobs(
            days_back=days_back,
            min_employees=min_employees,
        )
        if "companies" in job_results:
            for c in job_results["companies"]:
                domain = c.get("domain", "").lower()
                if domain:
                    results["job_signals"][domain] = c

    # GitHub search
    if include_github and GITHUB_TOKEN:
        gh_results = await find_claude_companies_github(search_scope="all")
        if "organizations" in gh_results:
            for org in gh_results["organizations"]:
                # Try to match org name to domain (imperfect but helpful)
                org_name = org["name"].lower()
                results["github_signals"][org_name] = org

    # Combine and dedupe
    all_domains = set(results["job_signals"].keys()) | set(results["github_signals"].keys())

    for domain in all_domains:
        job_data = results["job_signals"].get(domain, {})
        gh_data = results["github_signals"].get(domain, {})

        combined = {
            "identifier": domain,
            "name": job_data.get("name") or gh_data.get("name", domain),
            "domain": job_data.get("domain"),
            "employees": job_data.get("employees"),
            "industry": job_data.get("industry"),
            "sources": [],
            "confidence": "low",
        }

        if job_data:
            combined["sources"].append("job_postings")
            combined["job_count"] = job_data.get("job_count", 0)
            combined["job_keywords"] = job_data.get("keywords", [])

        if gh_data:
            combined["sources"].append("github")
            combined["github_repos"] = gh_data.get("repo_count", 0)

        # Calculate confidence
        if len(combined["sources"]) > 1:
            combined["confidence"] = "very_high"
        elif job_data.get("confidence") == "high":
            combined["confidence"] = "high"
        elif job_data or gh_data:
            combined["confidence"] = "medium"

        results["combined_companies"].append(combined)

    # Sort by confidence
    conf_order = {"very_high": 4, "high": 3, "medium": 2, "low": 1}
    results["combined_companies"].sort(
        key=lambda x: conf_order.get(x["confidence"], 0),
        reverse=True,
    )

    return {
        "total_companies": len(results["combined_companies"]),
        "from_jobs": len(results["job_signals"]),
        "from_github": len(results["github_signals"]),
        "multi_source": len([c for c in results["combined_companies"] if len(c["sources"]) > 1]),
        "companies": results["combined_companies"],
    }


@mcp.tool()
async def batch_check_companies(
    companies: list[str],
    include_evidence: bool = False,
) -> dict:
    """
    Check multiple companies for Claude usage in one batch call.
    Perfect for enriching CRM data from HubSpot, Salesforce, etc.

    Args:
        companies: List of company names or GitHub orgs (e.g., ["stripe", "vercel", "shopify"])
        include_evidence: Include detailed evidence (slower, more data)

    Returns:
        Results for each company with Claude usage verdict

    Example workflow with HubSpot:
        1. Ask Claude: "Get all my companies from HubSpot"
        2. Then: "Check which of these use Claude"
        3. Or combined: "Get my HubSpot companies and check which use Claude"
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required"}

    if not companies:
        return {"error": "No companies provided", "hint": "Pass a list of company names"}

    if len(companies) > 50:
        return {
            "error": f"Too many companies ({len(companies)}). Max 50 per batch.",
            "hint": "Split into smaller batches",
        }

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    results = []
    checked = 0
    found_using_claude = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for company in companies:
            checked += 1

            # Normalize company name
            org_name = company.lower().strip().replace(" ", "").replace("-", "").replace(".", "")

            # Quick org lookup
            org_resp = await client.get(f"{GITHUB_API}/orgs/{org_name}", headers=headers)

            if org_resp.status_code != 200:
                # Try variations
                found = False
                for var in [company.lower(), company.replace(" ", "-").lower(), f"{company.lower()}hq"]:
                    resp = await client.get(f"{GITHUB_API}/orgs/{var}", headers=headers)
                    if resp.status_code == 200:
                        org_name = var
                        found = True
                        break

                if not found:
                    results.append({
                        "company": company,
                        "github_org": None,
                        "uses_claude": "unknown",
                        "confidence": "none",
                        "reason": "GitHub org not found",
                    })
                    continue

            # Quick signal check (prioritize high-value signals)
            signals = []
            searches = [
                (f"org:{org_name} filename:.mcp.json", "MCP config", "very_high"),
                (f"org:{org_name} ANTHROPIC_API_KEY", "API key ref", "high"),
                (f'org:{org_name} "@anthropic-ai/sdk"', "SDK usage", "high"),
            ]

            for query, signal_name, confidence in searches:
                try:
                    resp = await client.get(
                        f"{GITHUB_API}/search/code",
                        params={"q": query, "per_page": 1},
                        headers=headers,
                    )
                    if resp.status_code == 200 and resp.json().get("total_count", 0) > 0:
                        signals.append({"signal": signal_name, "confidence": confidence})

                        # If we found a very high signal, we can stop early
                        if confidence == "very_high":
                            break
                except Exception:
                    continue

            # Determine verdict
            if any(s["confidence"] == "very_high" for s in signals):
                verdict = "yes"
                conf = "very_high"
                found_using_claude += 1
            elif any(s["confidence"] == "high" for s in signals):
                verdict = "likely"
                conf = "high"
                found_using_claude += 1
            elif signals:
                verdict = "possibly"
                conf = "medium"
            else:
                verdict = "no evidence"
                conf = "none"

            result = {
                "company": company,
                "github_org": org_name,
                "uses_claude": verdict,
                "confidence": conf,
                "signals": [s["signal"] for s in signals],
            }

            if include_evidence and signals:
                result["signal_details"] = signals

            results.append(result)

            # Rate limit: GitHub allows 30 search requests/minute
            # We do up to 3 searches per company, so ~10 companies/minute safe
            if checked % 10 == 0:
                import asyncio
                await asyncio.sleep(2)  # Brief pause every 10 companies

    # Sort by confidence
    conf_order = {"very_high": 4, "high": 3, "medium": 2, "none": 1}
    results.sort(key=lambda x: conf_order.get(x["confidence"], 0), reverse=True)

    # Separate into categories for easy reading
    using_claude = [r for r in results if r["uses_claude"] in ("yes", "likely")]
    possibly = [r for r in results if r["uses_claude"] == "possibly"]
    no_evidence = [r for r in results if r["uses_claude"] in ("no evidence", "unknown")]

    return {
        "summary": {
            "total_checked": len(companies),
            "using_claude": len(using_claude),
            "possibly_using": len(possibly),
            "no_evidence": len(no_evidence),
        },
        "using_claude": using_claude,
        "possibly_using": possibly,
        "no_evidence": no_evidence,
        "all_results": results,
    }


@mcp.tool()
async def check_companies_from_crm(
    companies: list[dict],
) -> dict:
    """
    Check companies from CRM export (HubSpot, Salesforce, etc.) for Claude usage.
    Accepts company objects with name and/or domain fields.

    Args:
        companies: List of company objects, e.g.:
                   [{"name": "Stripe", "domain": "stripe.com"}, ...]
                   Fields can include: name, domain, company_name, website

    Returns:
        Enriched company data with Claude usage signals

    Example: "Get my HubSpot companies and check which ones use Claude"
    """
    if not companies:
        return {"error": "No companies provided"}

    # Extract company names from various possible field names
    company_names = []
    company_map = {}  # Map normalized name back to original data

    for c in companies:
        # Try different field names that CRMs might use
        name = (
            c.get("name") or
            c.get("company_name") or
            c.get("company") or
            c.get("domain", "").replace(".com", "").replace(".io", "").replace("www.", "") or
            c.get("website", "").replace("https://", "").replace("http://", "").replace("www.", "").split(".")[0]
        )

        if name:
            name = name.strip()
            company_names.append(name)
            company_map[name.lower()] = c

    if not company_names:
        return {
            "error": "Could not extract company names from data",
            "hint": "Expected fields: name, company_name, domain, or website",
            "sample_input": companies[:2] if companies else [],
        }

    # Use the batch checker
    batch_results = await batch_check_companies(company_names[:50], include_evidence=False)

    if "error" in batch_results:
        return batch_results

    # Enrich results with original CRM data
    enriched = []
    for result in batch_results.get("all_results", []):
        original = company_map.get(result["company"].lower(), {})
        enriched.append({
            **result,
            "original_data": original,
            "hubspot_enrichment": {
                "claude_user": result["uses_claude"] in ("yes", "likely"),
                "confidence": result["confidence"],
                "signals": result.get("signals", []),
            }
        })

    return {
        "summary": batch_results["summary"],
        "for_crm_update": [
            {
                "company": r["company"],
                "domain": r.get("original_data", {}).get("domain"),
                "uses_claude": r["uses_claude"],
                "confidence": r["confidence"],
                "update_field_suggestion": {
                    "uses_claude_code": r["uses_claude"] in ("yes", "likely"),
                    "claude_confidence": r["confidence"],
                }
            }
            for r in enriched
        ],
        "using_claude": [r for r in enriched if r["uses_claude"] in ("yes", "likely")],
        "full_results": enriched,
    }


@mcp.tool()
async def does_company_use_claude(
    company: str,
) -> dict:
    """
    Quick check if a specific company uses Claude/Anthropic.
    Searches their GitHub org for Claude signals.

    Args:
        company: Company name or GitHub org (e.g., 'stripe', 'vercel', 'netflix')

    Returns:
        Whether the company appears to use Claude and what signals were found
    """
    if not GITHUB_TOKEN:
        return {"error": "GITHUB_TOKEN required"}

    # Normalize company name to likely GitHub org
    org_name = company.lower().replace(" ", "").replace("-", "").replace(".", "")

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }

    signals = []
    evidence = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if org exists
        org_resp = await client.get(f"{GITHUB_API}/orgs/{org_name}", headers=headers)

        org_info = None
        if org_resp.status_code == 200:
            org_data = org_resp.json()
            org_info = {
                "name": org_data.get("name") or org_name,
                "github_org": org_name,
                "description": org_data.get("description"),
                "blog": org_data.get("blog"),
                "public_repos": org_data.get("public_repos"),
            }
        else:
            # Try common variations
            variations = [company.lower(), company.replace(" ", "-").lower(), f"{company.lower()}hq", f"{company.lower()}-inc"]
            for var in variations:
                resp = await client.get(f"{GITHUB_API}/orgs/{var}", headers=headers)
                if resp.status_code == 200:
                    org_name = var
                    org_data = resp.json()
                    org_info = {
                        "name": org_data.get("name") or var,
                        "github_org": var,
                        "description": org_data.get("description"),
                        "blog": org_data.get("blog"),
                        "public_repos": org_data.get("public_repos"),
                    }
                    break

        if not org_info:
            return {
                "company": company,
                "found_on_github": False,
                "uses_claude": "unknown",
                "note": f"Could not find GitHub org for '{company}'. Try the exact GitHub org name.",
            }

        # Search for Claude signals
        searches = [
            (f"org:{org_name} filename:.mcp.json", "MCP config file", "very_high"),
            (f"org:{org_name} claude-code-action path:.github", "Claude Code GitHub Action", "very_high"),
            (f"org:{org_name} ANTHROPIC_API_KEY", "Anthropic API key reference", "high"),
            (f'org:{org_name} "@anthropic-ai/sdk"', "Anthropic SDK usage", "high"),
            (f'org:{org_name} "from anthropic import"', "Anthropic Python import", "high"),
            (f'org:{org_name} "claude" "api"', "Claude API mention", "medium"),
        ]

        for query, description, confidence in searches:
            try:
                resp = await client.get(
                    f"{GITHUB_API}/search/code",
                    params={"q": query, "per_page": 5},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("total_count", 0) > 0:
                        signals.append({
                            "signal": description,
                            "confidence": confidence,
                            "matches": data["total_count"],
                        })
                        for item in data.get("items", [])[:2]:
                            evidence.append({
                                "repo": item.get("repository", {}).get("full_name"),
                                "file": item.get("path"),
                                "signal": description,
                            })
            except Exception:
                continue

    # Determine verdict
    if any(s["confidence"] == "very_high" for s in signals):
        verdict = "yes"
        confidence = "very_high"
    elif any(s["confidence"] == "high" for s in signals):
        verdict = "likely"
        confidence = "high"
    elif signals:
        verdict = "possibly"
        confidence = "medium"
    else:
        verdict = "no evidence found"
        confidence = "none"

    return {
        "company": org_info.get("name", company),
        "github_org": org_name,
        "uses_claude": verdict,
        "confidence": confidence,
        "signals_found": len(signals),
        "signals": signals,
        "evidence": evidence[:5],
        "org_info": org_info,
    }


# ============ NEW SIGNAL SOURCES (FREE APIs) ============

@mcp.tool()
async def search_hackernews_signals(
    company: str,
    days_back: int = 365,
) -> dict:
    """
    Search Hacker News for discussions about a company using Claude.
    Uses the free Algolia HN Search API (no key needed).

    Args:
        company: Company name to search for
        days_back: How far back to search (default 365 days)

    Returns:
        HN discussions mentioning the company and Claude/Anthropic
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search for company + Claude mentions
        queries = [
            f'"{company}" Claude',
            f'"{company}" Anthropic',
            f'"{company}" "Claude Code"',
        ]

        all_results = []
        seen_ids = set()

        for query in queries:
            try:
                # Search stories
                stories_resp = await client.get(
                    f"{HN_ALGOLIA_API}/search",
                    params={
                        "query": query,
                        "tags": "story",
                        "hitsPerPage": 20,
                    },
                )
                if stories_resp.status_code == 200:
                    for hit in stories_resp.json().get("hits", []):
                        if hit["objectID"] not in seen_ids:
                            seen_ids.add(hit["objectID"])
                            all_results.append({
                                "type": "story",
                                "title": hit.get("title"),
                                "url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                                "author": hit.get("author"),
                                "points": hit.get("points"),
                                "comments": hit.get("num_comments"),
                                "date": hit.get("created_at"),
                            })

                # Search comments
                comments_resp = await client.get(
                    f"{HN_ALGOLIA_API}/search",
                    params={
                        "query": query,
                        "tags": "comment",
                        "hitsPerPage": 30,
                    },
                )
                if comments_resp.status_code == 200:
                    for hit in comments_resp.json().get("hits", []):
                        if hit["objectID"] not in seen_ids:
                            seen_ids.add(hit["objectID"])
                            comment_text = hit.get("comment_text", "")[:200]
                            all_results.append({
                                "type": "comment",
                                "text_preview": comment_text,
                                "url": f"https://news.ycombinator.com/item?id={hit['objectID']}",
                                "author": hit.get("author"),
                                "date": hit.get("created_at"),
                            })

            except Exception:
                continue

    # Analyze results for relevance
    relevant_results = []
    claude_terms = ["claude", "anthropic", "claude code", "mcp", "model context protocol"]

    for r in all_results:
        text = f"{r.get('title', '')} {r.get('text_preview', '')}".lower()
        if any(term in text for term in claude_terms):
            relevant_results.append(r)

    return {
        "company": company,
        "source": "hackernews",
        "total_mentions": len(relevant_results),
        "signal_strength": "high" if len(relevant_results) > 5 else "medium" if len(relevant_results) > 0 else "none",
        "results": relevant_results[:15],  # Top 15 results
    }


@mcp.tool()
async def check_npm_anthropic_usage(
    company: str,
) -> dict:
    """
    Check if a company has npm packages that depend on @anthropic-ai/sdk.
    Uses the free npm registry API (no key needed).
    Very high confidence signal - they're publishing code that uses Anthropic.

    Args:
        company: Company name or npm org scope (e.g., 'vercel', 'stripe')

    Returns:
        npm packages from the company that depend on Anthropic SDK
    """
    org_variations = [
        company.lower(),
        company.lower().replace(" ", ""),
        company.lower().replace(" ", "-"),
    ]

    anthropic_packages = []
    all_packages = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for org in org_variations:
            try:
                # Search for packages by org/maintainer
                search_resp = await client.get(
                    f"{NPM_REGISTRY_API}/-/v1/search",
                    params={
                        "text": f"maintainer:{org}",
                        "size": 50,
                    },
                )

                if search_resp.status_code != 200:
                    # Try scope search
                    search_resp = await client.get(
                        f"{NPM_REGISTRY_API}/-/v1/search",
                        params={
                            "text": f"scope:{org}",
                            "size": 50,
                        },
                    )

                if search_resp.status_code == 200:
                    packages = search_resp.json().get("objects", [])

                    for pkg in packages:
                        pkg_name = pkg.get("package", {}).get("name")
                        if not pkg_name:
                            continue

                        all_packages.append(pkg_name)

                        # Get package details to check dependencies
                        try:
                            pkg_resp = await client.get(f"{NPM_REGISTRY_API}/{pkg_name}/latest")
                            if pkg_resp.status_code == 200:
                                pkg_data = pkg_resp.json()
                                deps = pkg_data.get("dependencies", {})
                                dev_deps = pkg_data.get("devDependencies", {})
                                all_deps = {**deps, **dev_deps}

                                # Check for Anthropic SDK
                                anthropic_deps = [d for d in all_deps if "anthropic" in d.lower()]
                                if anthropic_deps:
                                    anthropic_packages.append({
                                        "package": pkg_name,
                                        "version": pkg_data.get("version"),
                                        "anthropic_dependencies": anthropic_deps,
                                        "npm_url": f"https://www.npmjs.com/package/{pkg_name}",
                                    })
                        except Exception:
                            continue

            except Exception:
                continue

    return {
        "company": company,
        "source": "npm",
        "packages_checked": len(all_packages),
        "packages_using_anthropic": len(anthropic_packages),
        "signal_strength": "very_high" if anthropic_packages else "none",
        "evidence": anthropic_packages,
    }


@mcp.tool()
async def check_pypi_anthropic_usage(
    company: str,
) -> dict:
    """
    Check if a company has PyPI packages that depend on the anthropic SDK.
    Uses the free PyPI JSON API (no key needed).
    Very high confidence signal - they're publishing code that uses Anthropic.

    Args:
        company: Company name to search for in package authors/maintainers

    Returns:
        PyPI packages from the company that depend on anthropic
    """
    # PyPI doesn't have a great search API, so we'll use the simple API
    # and search via the JSON endpoint
    anthropic_packages = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Search PyPI using simple search
        # Note: PyPI's search is limited, so we check known patterns
        search_terms = [
            company.lower(),
            company.lower().replace(" ", "-"),
            company.lower().replace(" ", "_"),
        ]

        # Try to find packages by searching
        for term in search_terms:
            try:
                # Use PyPI's simple search via Google (hacky but works)
                # Or try the JSON API for known package patterns
                possible_packages = [
                    term,
                    f"{term}-sdk",
                    f"{term}-python",
                    f"{term}-client",
                    f"py{term}",
                ]

                for pkg_name in possible_packages:
                    try:
                        pkg_resp = await client.get(f"{PYPI_API}/{pkg_name}/json")
                        if pkg_resp.status_code == 200:
                            pkg_data = pkg_resp.json()
                            info = pkg_data.get("info", {})

                            # Check if package author matches company
                            author = info.get("author", "").lower()
                            maintainer = info.get("maintainer", "").lower()
                            author_email = info.get("author_email", "").lower()

                            if not (term in author or term in maintainer or term in author_email):
                                continue

                            # Check dependencies
                            requires = info.get("requires_dist", []) or []
                            requires_str = " ".join(requires).lower()

                            if "anthropic" in requires_str:
                                anthropic_packages.append({
                                    "package": info.get("name"),
                                    "version": info.get("version"),
                                    "author": info.get("author"),
                                    "pypi_url": info.get("project_url") or f"https://pypi.org/project/{pkg_name}/",
                                    "requires_anthropic": True,
                                })
                    except Exception:
                        continue

            except Exception:
                continue

    return {
        "company": company,
        "source": "pypi",
        "packages_using_anthropic": len(anthropic_packages),
        "signal_strength": "very_high" if anthropic_packages else "none",
        "evidence": anthropic_packages,
    }


# ============ LINKEDIN TOOLS (Voyager API) ============

@mcp.tool()
async def search_linkedin_posts(
    company: str,
    keywords: list[str] | None = None,
) -> dict:
    """
    Search LinkedIn for posts mentioning a company and Claude/Anthropic.
    Uses LinkedIn's Voyager API directly (no Selenium needed).
    Requires LINKEDIN_COOKIE (li_at value from browser).

    Args:
        company: Company name to search for
        keywords: Additional keywords (default: Claude, Anthropic)

    Returns:
        LinkedIn posts mentioning the company and Claude/Anthropic
    """
    if not LINKEDIN_COOKIE:
        return {
            "status": "skipped",
            "reason": "LINKEDIN_COOKIE not configured",
            "setup": "Get li_at cookie from Chrome DevTools > Application > Cookies > linkedin.com",
            "results": [],
        }

    headers = get_linkedin_headers()
    if not headers:
        return {"error": "Failed to build LinkedIn headers"}

    search_keywords = keywords or ["Claude", "Anthropic", "Claude Code"]
    all_posts = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for keyword in search_keywords:
            query = f"{company} {keyword}"

            try:
                # Use LinkedIn's search endpoint for content
                resp = await client.get(
                    f"{LINKEDIN_API}/search/blended",
                    params={
                        "keywords": query,
                        "origin": "GLOBAL_SEARCH_HEADER",
                        "q": "all",
                        "filters": "List(resultType->CONTENT)",
                        "count": 20,
                    },
                    headers=headers,
                )

                if resp.status_code == 200:
                    data = resp.json()

                    # Parse the response for posts
                    elements = data.get("data", {}).get("elements", [])
                    if not elements:
                        elements = data.get("elements", [])

                    for element in elements:
                        # Extract post data from various response formats
                        post_data = element.get("content", element)

                        post = {
                            "type": "post",
                            "query": query,
                            "text": post_data.get("text", {}).get("text", "")[:500] if isinstance(post_data.get("text"), dict) else str(post_data.get("text", ""))[:500],
                            "author": post_data.get("actor", {}).get("name", {}).get("text", "Unknown"),
                            "url": f"https://www.linkedin.com/feed/update/{element.get('trackingUrn', element.get('entityUrn', ''))}",
                        }

                        if post["text"] and post not in all_posts:
                            all_posts.append(post)

                elif resp.status_code == 401:
                    return {
                        "error": "LinkedIn cookie expired or invalid",
                        "setup": "Refresh your li_at cookie from Chrome DevTools",
                    }

            except Exception as e:
                # Try alternative search endpoint
                try:
                    resp = await client.get(
                        f"{LINKEDIN_API}/search/dash/clusters",
                        params={
                            "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-175",
                            "origin": "GLOBAL_SEARCH_HEADER",
                            "q": "all",
                            "query": f"(keywords:{query},resultType:List(CONTENT))",
                            "start": 0,
                            "count": 20,
                        },
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        for element in data.get("included", []):
                            if element.get("$type") == "com.linkedin.voyager.feed.render.UpdateV2":
                                text = element.get("commentary", {}).get("text", {}).get("text", "")
                                if text:
                                    all_posts.append({
                                        "type": "post",
                                        "query": query,
                                        "text": text[:500],
                                        "author": element.get("actor", {}).get("name", {}).get("text", "Unknown"),
                                        "url": f"https://www.linkedin.com/feed/update/{element.get('urn', '')}",
                                    })
                except Exception:
                    continue

    # Deduplicate
    seen = set()
    unique_posts = []
    for post in all_posts:
        key = post.get("text", "")[:100]
        if key and key not in seen:
            seen.add(key)
            unique_posts.append(post)

    return {
        "company": company,
        "source": "linkedin_posts",
        "total_posts": len(unique_posts),
        "signal_strength": "high" if len(unique_posts) > 3 else "medium" if len(unique_posts) > 0 else "none",
        "posts": unique_posts[:20],
    }


@mcp.tool()
async def search_linkedin_jobs(
    company: str | None = None,
    keywords: list[str] | None = None,
    location: str | None = None,
) -> dict:
    """
    Search LinkedIn for job postings mentioning Claude/Anthropic.
    Can filter by company and/or search across all companies.
    Uses LinkedIn's Voyager API directly (no Selenium needed).

    Args:
        company: Company name to filter by (optional)
        keywords: Search keywords (default: Claude, Anthropic, Claude Code)
        location: Location filter (optional, e.g., "San Francisco")

    Returns:
        Job postings mentioning Claude/Anthropic
    """
    if not LINKEDIN_COOKIE:
        return {
            "status": "skipped",
            "reason": "LINKEDIN_COOKIE not configured",
            "setup": "Get li_at cookie from Chrome DevTools > Application > Cookies > linkedin.com",
            "results": [],
        }

    headers = get_linkedin_headers()
    search_keywords = keywords or ["Claude", "Anthropic", "Claude Code", "MCP"]
    all_jobs = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for keyword in search_keywords:
            query = f"{company} {keyword}" if company else keyword

            try:
                params = {
                    "decorationId": "com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-194",
                    "count": 25,
                    "q": "jobSearch",
                    "query": f"(origin:JOB_SEARCH_PAGE_QUERY_EXPANSION,keywords:{query},locationUnion:(geoId:103644278),spellCorrectionEnabled:true)",
                    "start": 0,
                }

                if location:
                    params["query"] = f"(origin:JOB_SEARCH_PAGE_QUERY_EXPANSION,keywords:{query},locationUnion:(geoId:103644278),location:{location},spellCorrectionEnabled:true)"

                resp = await client.get(
                    f"{LINKEDIN_API}/jobs/jobPostings",
                    params={"q": "search", "keywords": query, "count": 25},
                    headers=headers,
                )

                if resp.status_code == 200:
                    data = resp.json()

                    for element in data.get("elements", data.get("included", [])):
                        if "title" in element or element.get("$type", "").endswith("JobPosting"):
                            job = {
                                "title": element.get("title", ""),
                                "company": element.get("companyName", element.get("companyDetails", {}).get("company", "")),
                                "location": element.get("formattedLocation", element.get("location", "")),
                                "url": f"https://www.linkedin.com/jobs/view/{element.get('entityUrn', '').split(':')[-1]}" if element.get("entityUrn") else "",
                                "posted": element.get("listedAt", ""),
                                "keyword_matched": keyword,
                            }
                            if job["title"]:
                                all_jobs.append(job)

                # Try alternative job search endpoint
                if not all_jobs:
                    resp = await client.get(
                        f"{LINKEDIN_API}/search/dash/clusters",
                        params={
                            "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-175",
                            "origin": "JOB_SEARCH_PAGE_QUERY_EXPANSION",
                            "q": "all",
                            "query": f"(keywords:{query},resultType:List(JOBS))",
                            "start": 0,
                            "count": 25,
                        },
                        headers=headers,
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        for element in data.get("included", []):
                            if element.get("$type", "").endswith("JobPosting") or "title" in element:
                                job = {
                                    "title": element.get("title", ""),
                                    "company": element.get("primarySubtitle", {}).get("text", "") if isinstance(element.get("primarySubtitle"), dict) else element.get("companyName", ""),
                                    "location": element.get("secondarySubtitle", {}).get("text", "") if isinstance(element.get("secondarySubtitle"), dict) else "",
                                    "url": f"https://www.linkedin.com/jobs/view/{element.get('trackingUrn', element.get('entityUrn', '')).split(':')[-1]}",
                                    "keyword_matched": keyword,
                                }
                                if job["title"]:
                                    all_jobs.append(job)

            except Exception:
                continue

    # Deduplicate by title + company
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = f"{job.get('title', '')}-{job.get('company', '')}"
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Filter to only jobs that actually mention Claude/Anthropic in title
    claude_jobs = []
    other_jobs = []
    for job in unique_jobs:
        title_lower = job.get("title", "").lower()
        if any(kw.lower() in title_lower for kw in ["claude", "anthropic", "llm", "ai", "ml"]):
            claude_jobs.append(job)
        else:
            other_jobs.append(job)

    return {
        "company": company,
        "source": "linkedin_jobs",
        "total_jobs": len(unique_jobs),
        "claude_related_jobs": len(claude_jobs),
        "signal_strength": "high" if len(claude_jobs) > 2 else "medium" if len(claude_jobs) > 0 else "none",
        "jobs": claude_jobs + other_jobs[:10],
    }


@mcp.tool()
async def get_linkedin_company(
    company: str,
) -> dict:
    """
    Get LinkedIn company profile information.
    Useful for enriching company data found from other sources.
    Uses LinkedIn's Voyager API directly (no Selenium needed).

    Args:
        company: Company name or LinkedIn company URL

    Returns:
        Company profile information from LinkedIn
    """
    if not LINKEDIN_COOKIE:
        return {
            "status": "skipped",
            "reason": "LINKEDIN_COOKIE not configured",
            "setup": "Get li_at cookie from Chrome DevTools > Application > Cookies > linkedin.com",
        }

    headers = get_linkedin_headers()

    # Extract company slug from URL if provided
    company_slug = company
    if "linkedin.com/company/" in company:
        company_slug = company.split("/company/")[-1].strip("/").split("/")[0]
    else:
        # Normalize company name to likely LinkedIn slug
        company_slug = company.lower().replace(" ", "-").replace(".", "").replace(",", "")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            # Try to get company by universal name (slug)
            resp = await client.get(
                f"{LINKEDIN_API}/organization/companies",
                params={
                    "decorationId": "com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-40",
                    "q": "universalName",
                    "universalName": company_slug,
                },
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])

                if elements:
                    company_data = elements[0]

                    return {
                        "company": company,
                        "source": "linkedin",
                        "found": True,
                        "profile": {
                            "name": company_data.get("name", ""),
                            "universal_name": company_data.get("universalName", ""),
                            "tagline": company_data.get("tagline", ""),
                            "description": company_data.get("description", "")[:500],
                            "website": company_data.get("companyPageUrl", company_data.get("websiteUrl", "")),
                            "industry": company_data.get("companyIndustries", [{}])[0].get("localizedName", "") if company_data.get("companyIndustries") else "",
                            "company_size": company_data.get("staffCountRange", {}).get("start", 0),
                            "headquarters": company_data.get("headquarter", {}).get("city", ""),
                            "founded": company_data.get("foundedOn", {}).get("year", ""),
                            "specialties": company_data.get("specialities", []),
                            "linkedin_url": f"https://www.linkedin.com/company/{company_slug}",
                            "follower_count": company_data.get("followingInfo", {}).get("followerCount", 0),
                        },
                    }

            # Try search if direct lookup failed
            resp = await client.get(
                f"{LINKEDIN_API}/search/dash/clusters",
                params={
                    "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-175",
                    "origin": "GLOBAL_SEARCH_HEADER",
                    "q": "all",
                    "query": f"(keywords:{company},resultType:List(COMPANIES))",
                    "start": 0,
                    "count": 5,
                },
                headers=headers,
            )

            if resp.status_code == 200:
                data = resp.json()
                for element in data.get("included", []):
                    if element.get("$type", "").endswith("Company") or element.get("$type", "").endswith("MiniCompany"):
                        return {
                            "company": company,
                            "source": "linkedin",
                            "found": True,
                            "profile": {
                                "name": element.get("name", ""),
                                "universal_name": element.get("universalName", ""),
                                "description": element.get("description", "")[:500] if element.get("description") else "",
                                "industry": element.get("industry", {}).get("name", "") if isinstance(element.get("industry"), dict) else "",
                                "linkedin_url": f"https://www.linkedin.com/company/{element.get('universalName', '')}",
                            },
                        }

        except Exception as e:
            return {
                "company": company,
                "source": "linkedin",
                "found": False,
                "error": str(e),
            }

    return {
        "company": company,
        "source": "linkedin",
        "found": False,
        "note": f"Could not find company '{company}' on LinkedIn",
    }


@mcp.tool()
async def search_web_signals(
    company: str,
    signal_type: str = "all",
) -> dict:
    """
    Search the web for Claude/Anthropic signals using Brave Search API.
    Searches LinkedIn posts, news articles, and engineering blogs.
    Requires free Brave API key (get at https://brave.com/search/api/).

    Args:
        company: Company name to search for
        signal_type: "all", "linkedin", "news", or "blogs"

    Returns:
        Web mentions of the company using Claude/Anthropic
    """
    if not BRAVE_API_KEY:
        return {
            "status": "skipped",
            "reason": "BRAVE_API_KEY not configured (optional but recommended)",
            "setup": "Get free API key at https://brave.com/search/api/ (2000 queries/month free)",
            "results": [],
        }

    headers = {
        "X-Subscription-Token": BRAVE_API_KEY,
        "Accept": "application/json",
    }

    results = {
        "linkedin": [],
        "news": [],
        "blogs": [],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        queries = []

        if signal_type in ("all", "linkedin"):
            queries.append({
                "type": "linkedin",
                "query": f'site:linkedin.com "{company}" ("Claude Code" OR "using Claude" OR "Anthropic")',
            })

        if signal_type in ("all", "news"):
            queries.append({
                "type": "news",
                "query": f'"{company}" ("Claude AI" OR "Anthropic") (adoption OR using OR partnership OR announcement)',
            })

        if signal_type in ("all", "blogs"):
            queries.append({
                "type": "blogs",
                "query": f'"{company}" engineering blog ("Claude" OR "Anthropic") (implementation OR integration)',
            })

        for q in queries:
            try:
                resp = await client.get(
                    f"{BRAVE_SEARCH_API}/web/search",
                    params={"q": q["query"], "count": 10},
                    headers=headers,
                )

                if resp.status_code == 200:
                    data = resp.json()
                    for result in data.get("web", {}).get("results", []):
                        results[q["type"]].append({
                            "title": result.get("title"),
                            "url": result.get("url"),
                            "description": result.get("description", "")[:200],
                            "age": result.get("age"),
                        })

            except Exception as e:
                results[q["type"]].append({"error": str(e)})

    # Calculate signal strength
    total_results = sum(len(v) for v in results.values() if isinstance(v, list))
    linkedin_count = len([r for r in results["linkedin"] if "error" not in r])
    news_count = len([r for r in results["news"] if "error" not in r])
    blog_count = len([r for r in results["blogs"] if "error" not in r])

    signal_strength = "none"
    if linkedin_count > 0 or blog_count > 0:
        signal_strength = "high"
    elif news_count > 0:
        signal_strength = "medium"

    return {
        "company": company,
        "source": "web_search",
        "signal_strength": signal_strength,
        "counts": {
            "linkedin_posts": linkedin_count,
            "news_articles": news_count,
            "blog_posts": blog_count,
        },
        "results": results,
    }


@mcp.tool()
async def full_multi_source_scan(
    company: str,
    include_web: bool = True,
    include_linkedin: bool = True,
) -> dict:
    """
    Run a comprehensive multi-source scan for Claude/Anthropic usage.
    Combines GitHub, HN, npm, PyPI, LinkedIn, and web signals into a confidence score.

    Args:
        company: Company name to scan
        include_web: Include Brave Search (requires API key)
        include_linkedin: Include direct LinkedIn search (requires cookie)

    Returns:
        Aggregated signals with confidence score
    """
    signals = []
    evidence = {}
    score = 0

    # 1. GitHub scan
    if GITHUB_TOKEN:
        github_result = await does_company_use_claude(company)
        evidence["github"] = github_result

        if github_result.get("uses_claude") == "yes":
            score += SIGNAL_WEIGHTS["github_mcp_config"]
            signals.append({"source": "github", "signal": "MCP config found", "weight": 40})
        elif github_result.get("uses_claude") == "likely":
            score += SIGNAL_WEIGHTS["github_anthropic_sdk"]
            signals.append({"source": "github", "signal": "Anthropic SDK usage", "weight": 30})

    # 2. Hacker News scan
    hn_result = await search_hackernews_signals(company)
    evidence["hackernews"] = hn_result

    if hn_result.get("total_mentions", 0) > 0:
        weight = SIGNAL_WEIGHTS["hackernews_mention"]
        score += weight
        signals.append({
            "source": "hackernews",
            "signal": f"{hn_result['total_mentions']} HN mentions",
            "weight": weight,
        })

    # 3. npm scan
    npm_result = await check_npm_anthropic_usage(company)
    evidence["npm"] = npm_result

    if npm_result.get("packages_using_anthropic", 0) > 0:
        weight = SIGNAL_WEIGHTS["npm_anthropic_dep"]
        score += weight
        signals.append({
            "source": "npm",
            "signal": f"{npm_result['packages_using_anthropic']} packages use Anthropic SDK",
            "weight": weight,
        })

    # 4. PyPI scan
    pypi_result = await check_pypi_anthropic_usage(company)
    evidence["pypi"] = pypi_result

    if pypi_result.get("packages_using_anthropic", 0) > 0:
        weight = SIGNAL_WEIGHTS["pypi_anthropic_dep"]
        score += weight
        signals.append({
            "source": "pypi",
            "signal": f"{pypi_result['packages_using_anthropic']} packages use anthropic",
            "weight": weight,
        })

    # 5. LinkedIn direct search (posts and jobs)
    if include_linkedin and LINKEDIN_COOKIE:
        # LinkedIn posts
        linkedin_posts_result = await search_linkedin_posts(company)
        evidence["linkedin_posts"] = linkedin_posts_result

        if linkedin_posts_result.get("total_posts", 0) > 0:
            weight = SIGNAL_WEIGHTS["linkedin_post"]
            score += weight
            signals.append({
                "source": "linkedin_posts",
                "signal": f"{linkedin_posts_result['total_posts']} LinkedIn posts about Claude",
                "weight": weight,
            })

        # LinkedIn jobs
        linkedin_jobs_result = await search_linkedin_jobs(company=company)
        evidence["linkedin_jobs"] = linkedin_jobs_result

        if linkedin_jobs_result.get("claude_related_jobs", 0) > 0:
            weight = SIGNAL_WEIGHTS["linkedin_job"]
            score += weight
            signals.append({
                "source": "linkedin_jobs",
                "signal": f"{linkedin_jobs_result['claude_related_jobs']} LinkedIn job postings mention Claude/AI",
                "weight": weight,
            })

    # 6. Web search (additional LinkedIn via Brave, News, Blogs)
    if include_web and BRAVE_API_KEY:
        web_result = await search_web_signals(company)
        evidence["web"] = web_result

        # Only add Brave LinkedIn if we didn't already get direct LinkedIn results
        if not (include_linkedin and LINKEDIN_COOKIE):
            if web_result.get("counts", {}).get("linkedin_posts", 0) > 0:
                weight = SIGNAL_WEIGHTS["linkedin_post"]
                score += weight
                signals.append({
                    "source": "linkedin_web",
                    "signal": f"{web_result['counts']['linkedin_posts']} LinkedIn posts (via web search)",
                    "weight": weight,
                })

        if web_result.get("counts", {}).get("blog_posts", 0) > 0:
            weight = SIGNAL_WEIGHTS["engineering_blog"]
            score += weight
            signals.append({
                "source": "engineering_blog",
                "signal": f"{web_result['counts']['blog_posts']} blog posts",
                "weight": weight,
            })

        if web_result.get("counts", {}).get("news_articles", 0) > 0:
            weight = SIGNAL_WEIGHTS["news_article"]
            score += weight
            signals.append({
                "source": "news",
                "signal": f"{web_result['counts']['news_articles']} news articles",
                "weight": weight,
            })

    # Determine confidence level
    if score >= 60:
        confidence = "very_high"
        verdict = "yes"
    elif score >= 40:
        confidence = "high"
        verdict = "likely"
    elif score >= 20:
        confidence = "medium"
        verdict = "possibly"
    else:
        confidence = "low"
        verdict = "no strong evidence"

    return {
        "company": company,
        "verdict": verdict,
        "confidence": confidence,
        "score": score,
        "max_possible_score": sum(SIGNAL_WEIGHTS.values()),
        "signals_found": len(signals),
        "signals": sorted(signals, key=lambda x: x["weight"], reverse=True),
        "sources_checked": list(evidence.keys()),
        "evidence": evidence,
    }


@mcp.tool()
async def check_api_status() -> dict:
    """
    Check which APIs are configured and working.
    Run this first to verify your setup.
    GitHub is required, others are optional but add more signals.
    """
    status = {
        "github": {"configured": bool(GITHUB_TOKEN), "status": "unknown", "required": True},
        "linkedin": {"configured": bool(LINKEDIN_COOKIE), "status": "unknown", "required": False},
        "brave_search": {"configured": bool(BRAVE_API_KEY), "status": "unknown", "required": False},
        "theirstack": {"configured": bool(THEIRSTACK_API_KEY), "status": "unknown", "required": False},
        "hackernews": {"configured": True, "status": "working (no key needed)", "required": False},
        "npm": {"configured": True, "status": "working (no key needed)", "required": False},
        "pypi": {"configured": True, "status": "working (no key needed)", "required": False},
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Check TheirStack
        if THEIRSTACK_API_KEY:
            try:
                resp = await client.get(
                    f"{THEIRSTACK_BASE_URL}/technologies",
                    headers={"Authorization": f"Bearer {THEIRSTACK_API_KEY}"},
                    params={"limit": 1},
                )
                status["theirstack"]["status"] = "working" if resp.status_code == 200 else f"error: {resp.status_code}"
            except Exception as e:
                status["theirstack"]["status"] = f"error: {str(e)}"

        # Check GitHub
        if GITHUB_TOKEN:
            try:
                resp = await client.get(
                    f"{GITHUB_API}/rate_limit",
                    headers={"Authorization": f"token {GITHUB_TOKEN}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    remaining = data.get("resources", {}).get("search", {}).get("remaining", 0)
                    status["github"]["status"] = f"working ({remaining} searches remaining)"
                else:
                    status["github"]["status"] = f"error: {resp.status_code}"
            except Exception as e:
                status["github"]["status"] = f"error: {str(e)}"

        # Check LinkedIn
        if LINKEDIN_COOKIE:
            try:
                headers = get_linkedin_headers()
                resp = await client.get(
                    f"{LINKEDIN_API}/me",
                    headers=headers,
                )
                if resp.status_code == 200:
                    status["linkedin"]["status"] = "working"
                elif resp.status_code == 401:
                    status["linkedin"]["status"] = "error: cookie expired - refresh from Chrome DevTools"
                else:
                    status["linkedin"]["status"] = f"error: {resp.status_code}"
            except Exception as e:
                status["linkedin"]["status"] = f"error: {str(e)}"

    # Ready if GitHub works (others are optional)
    github_ok = status["github"]["configured"] and "working" in status["github"]["status"]
    linkedin_ok = status["linkedin"]["configured"] and "working" in status["linkedin"]["status"]
    theirstack_ok = status["theirstack"]["configured"] and "working" in status["theirstack"]["status"]

    status["ready"] = github_ok
    status["full_features"] = github_ok and linkedin_ok
    status["summary"] = {
        "can_search_github": github_ok,
        "can_search_linkedin": linkedin_ok,
        "can_search_jobs_theirstack": theirstack_ok,
        "message": "Ready! GitHub search available." if github_ok else "GitHub token required.",
    }

    if github_ok and linkedin_ok:
        status["summary"]["message"] = "Full features enabled! GitHub + LinkedIn working."
    elif github_ok and not linkedin_ok:
        status["summary"]["message"] += " LinkedIn disabled (add LINKEDIN_COOKIE for posts/jobs search)."

    return status


if __name__ == "__main__":
    mcp.run()
