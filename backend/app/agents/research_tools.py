from copy import deepcopy

from app.models.workspace import CampaignPlan


def strict_schema(schema):
    value = deepcopy(schema)
    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return value


def tool(name, description, properties):
    return {"type": "function", "name": name, "description": description, "strict": True,
        "parameters": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}}


TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}
RESEARCH_TOOLS = [
    tool("source_capabilities", "Inspect available discovery sources, limits and verification requirements before recommending a source.", {}),
    tool("research_market", "Search the web for evidence to compare customer segments or markets. Does not start a scraping campaign.", {"query": TEXT}),
    tool("research_company", "Research a public company website, including the user's business, and return cited facts. Does not discover or verify contact emails.", {"website": TEXT, "question": TEXT}),
    tool("search_crm", "Search this user's existing leads to avoid duplicates and learn from recorded qualification feedback.", {"query": TEXT}),
    tool("review_campaigns", "Inspect this user's recent campaign outcomes, verified counts, exclusions and research limitations. Use to recommend improvements from actual results.", {}),
    {"type": "function", "name": "propose_campaign", "strict": True,
     "description": "Create a draft campaign with a source, targeting rationale, criteria and limits. Requires a user click before scraping or enrichment. Do not invent a city the user has not selected. Never promise a lead count.",
     "parameters": strict_schema(CampaignPlan.model_json_schema())},
]


def source_catalog(settings):
    return [
        {"id": "google_maps", "name": "Google Maps", "provider": "Apify", "available": bool(settings.apify_token),
         "description": "Discover local businesses by category and city. Best for practices, shops and local services.",
         "fields": ["name", "website", "address", "business phone", "reviews", "observed Maps position"],
         "limits": "Up to 30 source places. Ranking is query-specific and may be unavailable. Does not establish revenue or employee count."},
        {"id": "web_research", "name": "Web discovery", "provider": "OpenAI web search", "available": bool(settings.openai_key),
         "description": "Find companies through cited web research. Useful for specialist B2B, software, agencies and manufacturers.",
         "fields": ["name", "official website", "category", "location", "source evidence"],
         "limits": "Up to 30 cited companies; result count is not guaranteed. Uncited websites are omitted."},
        {"id": "company_websites", "name": "Company websites", "provider": "Website research", "available": bool(settings.openai_key),
         "description": "Research and enrich a supplied list of company websites.",
         "fields": ["domain", "business evidence", "fit assessment"],
         "limits": "Up to 30 websites. Indexed public content only; unavailable evidence remains unknown."},
    ]
