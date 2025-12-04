"""
Job Posting Scanner MCP
Finds companies mentioning Claude/Anthropic in job postings via TheirStack API.
"""

import os
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP(
    "Claude Adopter Scanner - Jobs",
    instructions="Scan job postings for companies using Claude Desktop/Code",
)

THEIRSTACK_API_KEY = os.getenv("THEIRSTACK_API_KEY")
THEIRSTACK_BASE_URL = "https://api.theirstack.com/v1"

# Keywords that signal Claude/Anthropic usage
CLAUDE_KEYWORDS = [
    "Claude",
    "Anthropic",
    "Claude Code",
    "Claude Desktop",
    "MCP",
    "Model Context Protocol",
]

# High-confidence keywords (explicit mentions)
HIGH_CONFIDENCE_KEYWORDS = [
    "Claude Code",
    "Claude Desktop",
    "Anthropic API",
    "ANTHROPIC_API_KEY",
    "Model Context Protocol",
]


def calculate_confidence(job_description: str, job_title: str) -> tuple[str, list[str]]:
    """Calculate confidence level based on keyword matches."""
    text = f"{job_title} {job_description}".lower()
    matched_keywords = []

    for kw in HIGH_CONFIDENCE_KEYWORDS:
        if kw.lower() in text:
            matched_keywords.append(kw)

    if matched_keywords:
        return "high", matched_keywords

    for kw in CLAUDE_KEYWORDS:
        if kw.lower() in text:
            matched_keywords.append(kw)

    if matched_keywords:
        return "medium", matched_keywords

    return "low", []


@mcp.tool()
async def search_claude_jobs(
    days_back: int = 30,
    min_employees: int = 50,
    max_employees: int = 10000,
    countries: list[str] | None = None,
    limit: int = 100,
) -> dict:
    """
    Search job postings for companies using Claude/Anthropic.

    Args:
        days_back: How many days back to search (default 30)
        min_employees: Minimum company size (default 50 for mid-market)
        max_employees: Maximum company size (default 10000)
        countries: List of country codes to filter (e.g., ["US", "GB"])
        limit: Maximum results to return (default 100)

    Returns:
        Dictionary with companies found and their Claude signals
    """
    if not THEIRSTACK_API_KEY:
        return {
            "error": "THEIRSTACK_API_KEY not set. Get one at https://theirstack.com",
            "companies": [],
        }

    # Build the search query
    posted_after = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    payload = {
        "job_description_pattern_or": CLAUDE_KEYWORDS,
        "posted_at_gte": posted_after,
        "company_num_employees_min": min_employees,
        "company_num_employees_max": max_employees,
        "limit": limit,
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
            return {
                "error": f"TheirStack API error: {response.status_code} - {response.text}",
                "companies": [],
            }

        data = response.json()

    # Process and dedupe by company
    companies_map = {}

    for job in data.get("data", []):
        company_domain = job.get("company_domain") or job.get("company_name", "unknown")
        confidence, keywords = calculate_confidence(
            job.get("job_description", ""),
            job.get("job_title", ""),
        )

        if company_domain not in companies_map:
            companies_map[company_domain] = {
                "company_name": job.get("company_name"),
                "domain": job.get("company_domain"),
                "employee_count": job.get("company_num_employees"),
                "industry": job.get("company_industry"),
                "country": job.get("company_country"),
                "linkedin_url": job.get("company_linkedin_url"),
                "jobs": [],
                "all_keywords": set(),
                "highest_confidence": "low",
            }

        companies_map[company_domain]["jobs"].append({
            "title": job.get("job_title"),
            "url": job.get("job_url"),
            "posted_date": job.get("date_posted"),
            "location": job.get("job_location"),
            "confidence": confidence,
            "matched_keywords": keywords,
        })

        companies_map[company_domain]["all_keywords"].update(keywords)

        # Update highest confidence
        conf_order = {"high": 3, "medium": 2, "low": 1}
        current = companies_map[company_domain]["highest_confidence"]
        if conf_order[confidence] > conf_order[current]:
            companies_map[company_domain]["highest_confidence"] = confidence

    # Convert to list and sort by confidence + job count
    companies = []
    for domain, company in companies_map.items():
        company["all_keywords"] = list(company["all_keywords"])
        company["job_count"] = len(company["jobs"])
        companies.append(company)

    # Sort: high confidence first, then by job count
    conf_order = {"high": 3, "medium": 2, "low": 1}
    companies.sort(
        key=lambda c: (conf_order[c["highest_confidence"]], c["job_count"]),
        reverse=True,
    )

    return {
        "total_companies": len(companies),
        "search_params": {
            "days_back": days_back,
            "min_employees": min_employees,
            "max_employees": max_employees,
            "countries": countries,
        },
        "companies": companies,
    }


@mcp.tool()
async def search_mcp_jobs(
    days_back: int = 60,
    limit: int = 50,
) -> dict:
    """
    Search specifically for jobs mentioning MCP (Model Context Protocol).
    This is a very high signal for Claude adoption as MCP is Anthropic-specific.

    Args:
        days_back: How many days back to search
        limit: Maximum results

    Returns:
        Companies mentioning MCP in job postings
    """
    if not THEIRSTACK_API_KEY:
        return {
            "error": "THEIRSTACK_API_KEY not set",
            "companies": [],
        }

    posted_after = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    payload = {
        "job_description_pattern_or": [
            "Model Context Protocol",
            "MCP server",
            "MCP client",
            ".mcp.json",
        ],
        "posted_at_gte": posted_after,
        "limit": limit,
        "order_by": [{"field": "date_posted", "desc": True}],
    }

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
            return {"error": f"API error: {response.text}", "companies": []}

        data = response.json()

    # These are all high-confidence since MCP is Anthropic-specific
    companies = []
    seen = set()

    for job in data.get("data", []):
        domain = job.get("company_domain")
        if domain and domain not in seen:
            seen.add(domain)
            companies.append({
                "company_name": job.get("company_name"),
                "domain": domain,
                "employee_count": job.get("company_num_employees"),
                "industry": job.get("company_industry"),
                "linkedin_url": job.get("company_linkedin_url"),
                "sample_job": {
                    "title": job.get("job_title"),
                    "url": job.get("job_url"),
                    "posted": job.get("date_posted"),
                },
                "confidence": "very_high",
                "signal": "MCP mentioned in job posting",
            })

    return {
        "total_companies": len(companies),
        "note": "MCP mentions are very high confidence - it's Anthropic-specific technology",
        "companies": companies,
    }


@mcp.tool()
async def get_company_jobs(
    domain: str,
    days_back: int = 90,
) -> dict:
    """
    Get all recent jobs from a specific company to analyze their AI/Claude usage.

    Args:
        domain: Company domain (e.g., 'stripe.com')
        days_back: How far back to search

    Returns:
        All jobs from this company with Claude/AI signal analysis
    """
    if not THEIRSTACK_API_KEY:
        return {"error": "THEIRSTACK_API_KEY not set"}

    posted_after = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    payload = {
        "company_domain_or": [domain],
        "posted_at_gte": posted_after,
        "limit": 100,
    }

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
            return {"error": f"API error: {response.text}"}

        data = response.json()

    jobs = []
    claude_signals = []

    for job in data.get("data", []):
        confidence, keywords = calculate_confidence(
            job.get("job_description", ""),
            job.get("job_title", ""),
        )

        job_info = {
            "title": job.get("job_title"),
            "url": job.get("job_url"),
            "posted": job.get("date_posted"),
            "location": job.get("job_location"),
        }

        if keywords:
            job_info["claude_signals"] = keywords
            job_info["confidence"] = confidence
            claude_signals.append(job_info)

        jobs.append(job_info)

    return {
        "domain": domain,
        "total_jobs": len(jobs),
        "jobs_with_claude_signals": len(claude_signals),
        "claude_signal_jobs": claude_signals,
        "all_jobs": jobs[:20],  # Limit to 20 for readability
    }


if __name__ == "__main__":
    mcp.run()
