from copy import deepcopy

from app.models.workspace import BusinessProfile, CampaignPlan


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
    tool("remember_business_context", "Save only agency facts explicitly supplied by the user. Null leaves a field unchanged; empty string clears it.",
        {key: {"type": ["string", "null"], "maxLength": value.get("maxLength", 3000)}
         for key, value in BusinessProfile.model_json_schema()["properties"].items()}),
    tool("crm_insights", "Summarize this workspace's recorded pipeline stages, niches and exact email statuses. No outreach is sent.", {}),
    tool("stop_lead_search", "Request cancellation of the search the user asks to stop. A current paid provider call may finish.", {"campaign_id": TEXT}),
    tool("source_capabilities", "Inspect available discovery sources, limits and verification requirements before recommending a source.", {}),
    tool("research_market", "Search the web for evidence to compare customer segments or markets. Does not start a scraping campaign.", {"query": TEXT}),
    tool("research_company", "Research a public company website, including the user's business, and return cited facts. Does not discover or verify contact emails.", {"website": TEXT, "question": TEXT}),
    tool("search_crm", "Search this user's existing leads to avoid duplicates and learn from recorded qualification feedback.", {"query": TEXT}),
    tool("review_campaigns", "Inspect this user's recent campaign outcomes, verified counts, exclusions and research limitations. Use to recommend improvements from actual results.", {}),
    tool("start_lead_search", "Start an existing draft when the user asks to run it. Do not start a different search or add cities.", {"campaign_id": TEXT}),
    {"type": "function", "name": "generate_leads", "strict": True,
     "description": "Run a lead search when the user explicitly asks to fetch/find/generate leads. max_leads is the target number of new unique people with NeverBounce valid/catchall/unknown emails. The worker starts at 70 businesses per city and deepens saturated searches within those same cities up to max_city_rounds, until the target or exhaustion. Never invent additional cities. Returns a background job, not finished leads.",
     "parameters": strict_schema(CampaignPlan.model_json_schema())},
    {"type": "function", "name": "propose_campaign", "strict": True,
     "description": "Create a draft campaign with a source, targeting rationale, criteria and limits. Use only for a planning request. For an explicit request to fetch leads, use generate_leads. Do not invent a city the user has not selected. Never promise a lead count.",
     "parameters": strict_schema(CampaignPlan.model_json_schema())},
]


def source_catalog(settings):
    return [
        {"id": "google_maps", "name": "Google Maps", "provider": "Apify", "available": bool(settings.apify_token),
         "description": "Discover local businesses by category and city. Best for practices, shops and local services.",
         "fields": ["name", "website", "address", "business phone", "reviews", "observed Maps position"],
         "limits": "Starts at 70 businesses per location; deeper passes request 140 then 210 when the prior cap was filled. Only explicitly approved cities are searched, until the person target or depth budget. Ranking is query-specific and may be unavailable. Does not establish revenue or employee count."},
        {"id": "web_research", "name": "Web discovery", "provider": "OpenAI web search", "available": bool(settings.openai_key),
         "description": "Find companies through cited web research. Useful for specialist B2B, software, agencies and manufacturers.",
         "fields": ["name", "official website", "category", "location", "source evidence"],
         "limits": "Up to 70 cited companies per location; result count is not guaranteed. Uncited websites are omitted."},
        {"id": "company_websites", "name": "Company websites", "provider": "Website research", "available": bool(settings.openai_key),
         "description": "Research and enrich a supplied list of company websites.",
         "fields": ["domain", "business evidence", "fit assessment"],
         "limits": "Up to 70 websites. Indexed public content only; unavailable evidence remains unknown."},
    ]
