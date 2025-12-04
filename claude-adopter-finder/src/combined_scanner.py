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

# Constants
THEIRSTACK_BASE_URL = "https://api.theirstack.com/v1"
GITHUB_API = "https://api.github.com"

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


@mcp.tool()
async def check_api_status() -> dict:
    """
    Check which APIs are configured and working.
    Run this first to verify your setup.
    GitHub is required, TheirStack is optional.
    """
    status = {
        "github": {"configured": bool(GITHUB_TOKEN), "status": "unknown", "required": True},
        "theirstack": {"configured": bool(THEIRSTACK_API_KEY), "status": "unknown", "required": False},
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

    # Ready if GitHub works (TheirStack is optional)
    github_ok = status["github"]["configured"] and "working" in status["github"]["status"]
    theirstack_ok = status["theirstack"]["configured"] and "working" in status["theirstack"]["status"]

    status["ready"] = github_ok
    status["full_features"] = github_ok and theirstack_ok
    status["summary"] = {
        "can_search_github": github_ok,
        "can_search_jobs": theirstack_ok,
        "message": "Ready! GitHub search available." if github_ok else "GitHub token required.",
    }

    if github_ok and not theirstack_ok:
        status["summary"]["message"] += " Job posting search disabled (TheirStack not configured - optional)."

    return status


if __name__ == "__main__":
    mcp.run()
