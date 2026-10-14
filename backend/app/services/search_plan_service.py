import re

from app.models.agent_schemas import AgentInterpretation, LeadSearchPlan, PlanDraft

US_STATES = dict(pair.split(":") for pair in (
    "AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|CT:Connecticut|DE:Delaware|"
    "FL:Florida|GA:Georgia|HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|"
    "LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|MS:Mississippi|MO:Missouri|"
    "MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|"
    "ND:North Dakota|OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|SD:South Dakota|"
    "TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|DC:District of Columbia"
).split("|"))


def update_plan(current: LeadSearchPlan, interpretation: AgentInterpretation) -> LeadSearchPlan:
    values = current.model_dump()
    for field in interpretation.changed_fields:
        value = getattr(interpretation.plan, field)
        values[field] = value.strip() or None if isinstance(value, str) else value
    if values["state"]:
        state = values["state"]
        values["state"] = US_STATES.get(state.upper(), next((name for name in US_STATES.values() if name.casefold() == state.casefold()), state))
    before = {key: getattr(current, key) for key in PlanDraft.model_fields}
    after = {key: values[key] for key in PlanDraft.model_fields}
    if after != before:
        values["version"] += 1
    plan = LeadSearchPlan.model_validate(values)
    limitations = list(plan.unsupported_preferences)
    if plan.business_size_preference:
        limitations.append("Company size cannot be established from this pipeline. Remove this qualification to continue.")
    if plan.additional_preferences:
        limitations.append("Additional qualifications are recorded but unsupported. Remove them before starting the search.")
    if plan.country and plan.country.casefold() not in {"us", "usa", "united states", "united states of america"}:
        limitations.append("The conversational search currently supports one US city and state.")
    if plan.state and plan.state not in US_STATES.values():
        limitations.append("Choose a supported US state.")
    if plan.city and re.search(r"[,;\n]|\s+(?:and|or)\s+", plan.city, re.IGNORECASE):
        limitations.append("Choose one concrete city for this search.")
    if plan.min_google_maps_rank and plan.max_google_maps_rank and plan.min_google_maps_rank > plan.max_google_maps_rank:
        limitations.append("Minimum result position must not exceed maximum result position.")
    plan.limitations = limitations
    plan.status = "ready_for_confirmation" if plan.niche and plan.city and plan.state and not limitations else "collecting_requirements"
    return plan
