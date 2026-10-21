"""Opt-in real-model smoke test. No scraping, enrichment, cloud writes or outreach.

Run from backend: .venv/Scripts/python.exe scripts/smoke_advisor.py --live
Uses the existing OPENAI_MODEL and credentials; at most eight model requests.
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.research_agent import ResearchAgent
from app.config import get_settings
from app.models.workspace import AdvisorMessage
from app.services.campaign_service import CampaignService
from app.services.research_service import ResearchService
from app.services.workspace_store import WorkspaceStore


def main():
    if sys.argv[1:] != ['--live']:
        raise SystemExit('Pass --live to authorize paid model requests (no paid lead providers).')
    settings = get_settings()
    store = WorkspaceStore(':memory:')
    campaigns = CampaignService(settings, store)
    campaigns.executor.submit = MagicMock()
    user = store.identity('isolated-smoke-test')
    agent = ResearchAgent(settings, store, campaigns)
    original_client = ResearchService.client
    requests = 0

    def limited_client(service):
        nonlocal requests
        requests += 1
        if requests > 8:
            raise RuntimeError('Live smoke request budget exceeded')
        return original_client(service)

    try:
        with patch.object(ResearchService, 'client', limited_client), patch.object(
            ResearchService, 'search', return_value={'summary': 'Web research disabled in this dispatch smoke test.', 'sources': []}
        ):
            thread = agent.create(user)
            result = agent.message(user, thread['id'], AdvisorMessage(message='Pull me leads for my SEO agency.', message_id='brief'))
            assert not store.list(user, 'campaign'), 'Incomplete brief must not create a campaign'
            print(json.dumps({'scenario': 'missing brief', 'answer': result['messages'][-1]['content']}, ensure_ascii=True), flush=True)
            result = agent.message(user, thread['id'], AdvisorMessage(message=(
                'Fetch 60 dentist leads in Austin, Texas only. Include valid, catchall and unknown emails. '
                'Use up to three search passes in Austin, no other cities. No additional company-fit criteria or website research.'
            ), message_id='generate'))
            saved = store.list(user, 'campaign')
            assert len(saved) == 1, 'Expected exactly one campaign'
            campaign = saved[0]
            assert campaign['status'] == 'queued'
            assert campaign['plan']['max_leads'] == 60
            assert campaign['plan']['email_policy'] == 'accepted'
            assert campaign['plan']['max_city_rounds'] == 3
            assert len(campaign['plan']['locations']) == 1
            assert campaign['plan']['locations'][0]['city'].casefold() == 'austin'
            campaigns.executor.submit.assert_called_once()
            print(json.dumps({'scenario': 'complete brief', 'model': settings.openai_model, 'requests': requests,
                'plan': campaign['plan'], 'answer': result['messages'][-1]['content']}, ensure_ascii=True), flush=True)
    finally:
        campaigns.close()
        store.close()


if __name__ == '__main__':
    main()
