import json
from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agents.research_agent import ResearchAgent
from app.agents.research_tools import RESEARCH_TOOLS
from app.main import app
from app.models.leads import Business, Contact, Lead, Verification
from app.models.workspace import AdvisorMessage, CampaignPlan, now
from app.services.campaign_service import CampaignService
from app.services.hunter_service import HunterSearch
from app.services.research_service import ResearchService, public_url
from app.services.workspace_store import WorkspaceStore


def plan(**changes):
    return CampaignPlan(name="Austin clinics", source="google_maps", niche="clinics", city="Austin", state="Texas", research_websites=False, **changes)


@pytest.fixture
def workspace(settings, tmp_path):
    store = WorkspaceStore(str(tmp_path / "workspace.sqlite3"))
    service = CampaignService(settings, store)
    user = store.identity("owner")
    yield store, service, user
    service.close()
    store.close()


def test_workspace_isolation_and_restart(tmp_path):
    path = str(tmp_path / "records.db")
    store = WorkspaceStore(path)
    owner = store.identity("owner")
    store.save(owner, "lead", {"id":"a", "company":"Example"})
    assert store.list(store.identity("other"), "lead") == []
    with pytest.raises(HTTPException) as error:
        store.get(store.identity("other"), "lead", "a")
    assert error.value.status_code == 404
    store.close()
    restored = WorkspaceStore(path)
    assert restored.get(restored.identity("owner"), "lead", "a")["company"] == "Example"
    restored.close()


def test_campaign_exact_version_reservation_and_duplicate_start(workspace):
    store, service, user = workspace
    service.executor.submit = MagicMock()
    campaign = service.create(user, plan())
    with pytest.raises(HTTPException) as error:
        service.start(user,campaign["id"],2)
    assert error.value.status_code == 409
    first = service.start(user,campaign["id"],1)
    second = service.start(user,campaign["id"],1)
    assert first["id"] == second["id"]
    service.executor.submit.assert_called_once()
    assert store.get(user,"campaign",campaign["id"])["approved_version"] == 1


def test_campaign_missing_keys_has_no_reservation(workspace):
    store, service, user = workspace
    service.settings = replace(service.settings,neverbounce_key="")
    campaign = service.create(user,plan())
    with pytest.raises(HTTPException) as error:
        service.start(user,campaign["id"],1)
    assert error.value.status_code == 503
    assert store.get(user,"campaign",campaign["id"])["status"] == "draft"


def test_interrupted_campaign_does_not_restart(workspace):
    store, service, user = workspace
    campaign = service.create(user,plan())
    campaign.update(status="enriching",process_id="old")
    store.save(user,"campaign",campaign)
    service.executor.submit = MagicMock()
    assert service.start(user,campaign["id"],1)["status"] == "interrupted"
    service.executor.submit.assert_not_called()


@pytest.mark.parametrize("result,accepted",[("valid",True),("catchall",True),("unknown",True),("invalid",False),("disposable",False),("verification_error",False)])
def test_all_discovery_sources_use_hunter_and_neverbounce(workspace, monkeypatch,result,accepted):
    store, service, user = workspace
    service._discover = lambda *args: [{"title":"Clinic","website":"https://example.com","categoryName":"Clinic"}]
    hunter = MagicMock(); hunter.search.return_value = HunterSearch(contacts=[Contact(email="owner@example.com",job_title="Owner",first_name="Pat")])
    nb = MagicMock(); nb.verify.return_value = Verification(result=result)
    monkeypatch.setattr("app.services.campaign_service.HunterService",lambda *args: hunter)
    monkeypatch.setattr("app.services.campaign_service.NeverBounceService",lambda *args: nb)
    for source in ["google_maps","web_research","company_websites"]:
        identity = store.identity("user_" + source)
        campaign = service.create(identity,CampaignPlan(name="Test",source=source,niche="Clinics",city="Austin",state="Texas",query="Austin clinics",websites=["https://example.com"],research_websites=False,max_leads=1))
        from threading import Event
        service._run(identity,campaign,Event())
        records = store.list(identity,"lead")
        assert len(records) == int(accepted)
        if accepted:
            assert records[0]["category"] == "verified"
            assert records[0]["lead"]["verified"] is True
            assert records[0]["lead"]["verification"]["result"] == result
        outcome = store.get(identity,"campaign",campaign["id"])
        assert outcome["status"] == ("completed" if accepted else "shortfall")
        assert outcome["progress"]["verified"] == int(accepted)
    assert hunter.search.call_count == 3
    assert nb.verify.call_count == 3


def test_excluded_business_does_not_spend_enrichment(workspace,monkeypatch):
    store,service,user=workspace
    service.settings = replace(service.settings,openai_key="test")
    service._discover=lambda *args:[{"title":"Clinic","website":"https://example.com"}]
    monkeypatch.setattr(ResearchService,"assess",lambda *args: {"summary":"National franchise", "fit":"poor","reasons":["Excluded franchise"],"unknowns":[],"evidence":[],"excluded":True})
    hunter=MagicMock(); nb=MagicMock()
    monkeypatch.setattr("app.services.campaign_service.HunterService",lambda *args:hunter)
    monkeypatch.setattr("app.services.campaign_service.NeverBounceService",lambda *args:nb)
    campaign=service.create(user,CampaignPlan(name="Test",source="company_websites",niche="Clinics",websites=["https://example.com"],exclusions=["National franchises"]))
    from threading import Event
    service._run(user,campaign,Event())
    assert store.list(user,"lead") == []
    assert store.get(user,"campaign",campaign["id"])["progress"]["excluded"] == 1
    hunter.search.assert_not_called(); nb.verify.assert_not_called()


def test_local_api_ownership_profile_and_version():
    with TestClient(app) as client:
        assert client.get('/api/workspace').status_code == 200
        assert client.put('/api/workspace/profile',json={"offer":"Local SEO"}).status_code == 200
        assert client.get('/api/workspace').json()["profile"]["offer"] == "Local SEO"
        created=client.post('/api/workspace/campaigns',json=plan().model_dump()).json()
        response=client.put('/api/workspace/campaigns/'+created["id"]+'?version=1',json=plan(max_leads=5).model_dump())
        assert response.status_code == 200 and response.json()["version"] == 2
        assert client.post('/api/workspace/campaigns/'+created["id"]+'/start',json={"version":1}).status_code == 409
        client.cookies.clear()
        assert client.get('/api/workspace').json()["campaigns"] == []
        assert client.post('/api/workspace/campaigns/'+created["id"]+'/start',json={"version":2}).status_code == 404


def test_verified_export_checks_actual_provider_result_and_formula_escaping():
    with TestClient(app) as client:
        client.get('/api/workspace')
        owner = 'local_' + __import__('hashlib').sha256(client.cookies.get('gm_session').encode()).hexdigest()
        store=app.state.workspace_store; user=store.identity(owner)
        for key,result in [('good','catchall'),('bad','invalid')]:
            item={"id":key,"company":"=Example","industry":"Clinic","location":"Austin","domain":"example.com","category":"verified", "stage":"new", "campaign_ids":[],"source":"google_maps","assessment":{"fit":"unknown"},"lead":{"verified":True,"contact":{"email":"owner@example.com","first_name":"Pat","job_title":"Owner"},"verification":{"result":result}}}
            store.save(user,'lead',item)
        content=client.get('/api/workspace/leads/export').content.decode('utf-8-sig')
        assert content.count('owner@example.com') == 1
        assert "'=Example" in content
        assert client.patch('/api/workspace/leads/good',json={"category":"verified"}).status_code == 422
        assert client.patch('/api/workspace/leads/bad',json={"stage":"qualified"}).status_code == 409
        assert client.patch('/api/workspace/leads/bulk',json={"ids":["good","bad"],"changes":{"stage":"qualified"}}).status_code == 409
        assert store.get(user,'lead','good')['stage'] == 'new'


@pytest.mark.parametrize('value',['http://localhost','http://127.0.0.1','https://10.0.0.1','file:///etc/passwd','javascript:alert(1)','https://user:pass@example.com','https://example.com:8080','https://host.internal'])
def test_research_rejects_nonpublic_urls(value):
    assert public_url(value) is None


def test_research_tools_strict_and_support_bounded_generation():
    for tool in RESEARCH_TOOLS:
        assert tool['strict'] is True
        assert tool['parameters']['additionalProperties'] is False
        assert set(tool['parameters']['required']) == set(tool['parameters']['properties'])
    assert {'generate_leads','start_lead_search','propose_campaign'} <= {tool['name'] for tool in RESEARCH_TOOLS}
    generate = next(tool for tool in RESEARCH_TOOLS if tool['name']=='generate_leads')
    assert generate['parameters']['properties']['max_leads']['maximum']==1000
    assert generate['parameters']['$defs']['CampaignLocation']['additionalProperties'] is False


def test_advisor_proposes_without_executing_and_retries_idempotently(workspace,settings,monkeypatch):
    store,service,user=workspace
    settings=replace(settings,openai_key='test')
    agent=ResearchAgent(settings,store,service)
    service.start=MagicMock()
    client=MagicMock(); client.__enter__.return_value=client
    call=NS(type='function_call',name='propose_campaign',arguments=plan().model_dump_json(),call_id='call1')
    client.responses.create.side_effect=[NS(status='completed',output=[call],output_text='',usage=NS(input_tokens=10,output_tokens=20)),NS(status='completed',output=[],output_text='Review your campaign.',usage=NS(input_tokens=10,output_tokens=20))]
    monkeypatch.setattr(ResearchService,'client',lambda self:client)
    thread=agent.create(user)
    body=AdvisorMessage(message='Find Austin clinics',message_id='message1')
    result=agent.message(user,thread['id'],body)
    assert len(result['campaign_ids']) == 1
    assert store.list(user,'campaign')[0]['status'] == 'draft'
    assert result['messages'][-1]['content'] == 'Review your campaign.'
    agent.message(user,thread['id'],body)
    assert client.responses.create.call_count == 2
    service.start.assert_not_called()


def test_remote_store_uses_owner_filter_and_jwt(monkeypatch):
    store=WorkspaceStore(':memory:','https://project.supabase.co','public-key')
    user=store.identity('user-id','user-token')
    request=MagicMock(return_value=httpx.Response(200,json=[]))
    monkeypatch.setattr(httpx,'request',request)
    assert store.list(user,'lead') == []
    assert request.call_args.kwargs['params']['owner_id'] == 'eq.user-id'
    assert request.call_args.kwargs['headers']['Authorization'] == 'Bearer user-token'
    store.close()


def test_unauthenticated_cloud_mode_and_invalid_token(monkeypatch):
    monkeypatch.setenv('ALLOW_LOCAL_WORKSPACE','false')
    with TestClient(app) as client:
        assert client.get('/api/workspace').status_code == 401
        assert client.get('/api/workspace',headers={'Authorization':'Bearer forged'}).status_code == 401
        assert client.post('/api/runs',json={}).status_code == 401
        assert client.post('/api/scrapes',json={}).status_code == 401
        assert client.get('/health').status_code == 200
        assert client.get('/api/workspace/config').status_code == 200


def test_advisor_receives_actionable_validation_and_corrects_draft(workspace,settings,monkeypatch):
    store,service,user=workspace
    agent=ResearchAgent(replace(settings,openai_key='test'),store,service)
    invalid=plan().model_dump()
    invalid['qualification_criteria']=['Owner operated']
    client=MagicMock(); client.__enter__.return_value=client
    observed=[]
    def respond(**kwargs):
        observed.append(list(kwargs['input']))
        if len(observed)==1:
            call=NS(type='function_call',name='propose_campaign',arguments=json.dumps(invalid),call_id='bad')
        elif len(observed)==2:
            error=json.loads(kwargs['input'][-1]['output'])
            assert 'Website research is required' in error['details'][0]['msg']
            assert 'input' not in error['details'][0]
            call=NS(type='function_call',name='propose_campaign',arguments=plan().model_dump_json(),call_id='fixed')
        else:
            return NS(status='completed',output=[],output_text='Your draft is ready.',usage=None)
        return NS(status='completed',output=[call],output_text='',usage=None)
    client.responses.create.side_effect=respond
    monkeypatch.setattr(ResearchService,'client',lambda self:client)
    thread=agent.create(user)
    result=agent.message(user,thread['id'],AdvisorMessage(message='Find clinics without website research.',message_id='repair'))
    assert len(result['campaign_ids'])==1
    assert [item['status'] for item in result['messages'][-1]['traces']]==['error','completed']
    assert service.jobs=={}


def test_cloud_recovery_flush_is_owner_scoped_and_preserves_later_edits(monkeypatch):
    store=WorkspaceStore(':memory:','https://project.supabase.co','public')
    owner=store.identity('owner','jwt')
    other=store.identity('other','other-jwt')
    records={}
    def remote(identity,method,params=None,payload=None):
        if method=='POST':
            records[(identity.owner,payload['record_id'])]=dict(payload['data'])
            return []
        item=records.get((identity.owner,params['record_id'][3:]))
        return [{'data':item}] if item else []
    monkeypatch.setattr(store,'_remote',remote)
    store.recovery_save(owner,'lead',{'id':'a','company':'Provider result'})
    store.recovery_save(owner,'lead',{'id':'b','notes':'Older copy'})
    store.recovery_save(other,'lead',{'id':'c','company':'Private result'})
    records[('owner','b')]={'id':'b','notes':'Later CRM edit','updated_at':'9999-01-01T00:00:00+00:00'}
    store.flush_recovery(owner)
    assert records[('owner','a')]['company']=='Provider result'
    assert records[('owner','b')]['notes']=='Later CRM edit'
    assert ('other','c') not in records
    assert store.db.execute('SELECT owner,id FROM workspace_outbox').fetchall()==[('other','c')]
    store.close()


def mock_people(monkeypatch, search, verify):
    hunter=MagicMock(); hunter.search.side_effect=search
    nb=MagicMock(); nb.verify.side_effect=verify
    monkeypatch.setattr("app.services.campaign_service.HunterService",lambda *args:hunter)
    monkeypatch.setattr("app.services.campaign_service.NeverBounceService",lambda *args:nb)
    return hunter,nb


def person(email):
    return Contact(email=email,first_name="Pat",last_name="Owner",job_title="Owner")


@pytest.mark.parametrize('limit,expected', [(1, 1), (2, 2), (None, 3)])
def test_company_limit_checks_next_candidate_after_rejection(workspace, monkeypatch, limit, expected):
    from threading import Event
    store, service, user = workspace
    service._discover = lambda *args: [{'title': 'Clinic', 'website': 'https://clinic.com'}]
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(contacts=[person(f'{name}@clinic.com') for name in ['bad', 'pat', 'sam', 'alex']]),
        lambda email: Verification(result='invalid' if email.startswith('bad@') else 'valid'))
    campaign = service.create(user, plan(max_leads=5, max_leads_per_company=limit))
    service._run(user, campaign, Event())
    result = store.get(user, 'campaign', campaign['id'])
    assert result['progress']['verified'] == expected
    assert result['shortfall'] == 5 - expected
    assert nb.verify.call_count == expected + 1
    assert len(store.list(user, 'lead')) == expected


def test_200_leads_require_200_unique_companies(workspace, monkeypatch):
    from threading import Event
    store, service, user = workspace
    def discover(local_plan, *args):
        prefix = local_plan.city.lower().replace(' ', '')
        return [{'title': f'{prefix} Clinic {i}', 'website': f'https://{prefix}{i}.com'} for i in range(70)]
    service._discover = discover
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(contacts=[person(name + '@' + domain) for name in ['pat', 'sam', 'alex']]),
        lambda email: Verification(result='valid'))
    campaign = service.create(user, multi_plan(200))
    service._run(user, campaign, Event())
    records = store.list(user, 'lead')
    assert len(records) == len({row['domain'] for row in records}) == 200
    assert hunter.search.call_count == nb.verify.call_count == 200
    assert store.get(user, 'campaign', campaign['id'])['status'] == 'completed'


@pytest.mark.parametrize('limit,expected_checks', [(1, 0), (2, 1)])
def test_saved_company_cap_applies_to_subdomains_and_existing_leads(workspace, monkeypatch, limit, expected_checks):
    from threading import Event
    store, service, user = workspace
    existing = {'id': 'legacy', 'domain': 'WWW.CLINIC.CO.UK', 'notes': 'Keep my CRM notes',
        'stage': 'archived', 'category': 'excluded',
        'lead': {'contact': {'email': ' Pat@Clinic.co.uk '}, 'verification': {'result': 'invalid'}}}
    store.save(user, 'lead', existing)
    service._discover = lambda *args: [{'title': 'Other branch', 'website': 'https://austin.clinic.co.uk/team'}]
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(contacts=[person('pat@clinic.co.uk'), person('sam@clinic.co.uk'), person('alex@clinic.co.uk')]),
        lambda email: Verification(result='valid'))
    campaign = service.create(user, plan(max_leads=10, max_leads_per_company=limit))
    service._run(user, campaign, Event())
    assert hunter.search.call_count == expected_checks
    assert nb.verify.call_count == expected_checks
    assert len(store.list(user, 'lead')) == 1 + expected_checks
    assert store.get(user, 'lead', 'legacy') == existing


def test_saved_email_dedup_is_independent_of_company_and_current_policy(workspace, monkeypatch):
    from threading import Event
    store, service, user = workspace
    store.save(user, 'lead', {'id': 'old', 'domain': 'old.com', 'category': 'excluded',
        'lead': {'contact': {'email': ' Pat@shared.com '}, 'verification': {'result': 'invalid'}}})
    service._discover = lambda *args: [{'title': 'New company', 'website': 'https://new.com'}]
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(contacts=[person('PAT@SHARED.COM'), person('sam@new.com')]),
        lambda email: Verification(result='valid'))
    index_read = MagicMock(wraps=store.lead_index)
    monkeypatch.setattr(store, 'lead_index', index_read)
    campaign = service.create(user, plan(max_leads=1))
    service._run(user, campaign, Event())
    index_read.assert_called_once_with(user)
    nb.verify.assert_called_once_with('sam@new.com')
    assert store.get(user, 'campaign', campaign['id'])['progress']['verified'] == 1
    assert len(store.list(user, 'lead')) == 2


@pytest.mark.parametrize('bad', [0, -1, 1001, 1.5, True, '2'])
def test_company_limit_validation(bad):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        plan(max_leads_per_company=bad)


def test_company_limit_reaches_both_advisor_tools(workspace):
    store, service, user = workspace
    agent = ResearchAgent(service.settings, store, service)
    service.start = MagicMock(side_effect=lambda identity, record_id, version: store.get(identity, 'campaign', record_id))
    for name in ('generate_leads', 'propose_campaign'):
        schema = next(tool['parameters'] for tool in RESEARCH_TOOLS if tool['name'] == name)
        assert 'max_leads_per_company' in schema['required']
        for limit in (1, 3, None):
            result = agent.execute(name, plan(max_leads=200, max_leads_per_company=limit).model_dump(), user, None, [])
            assert result['plan']['max_leads_per_company'] == limit


def test_compact_lead_index_is_owner_scoped_and_counts_unique_emails(workspace):
    store, service, user = workspace
    for record_id in ('a', 'b'):
        store.save(user, 'lead', {'id': record_id, 'website': 'https://branch.clinic.com',
            'lead': {'contact': {'email': ' PAT@clinic.com '}}})
    store.save(store.identity('other'), 'lead', {'id': 'private', 'domain': 'clinic.com',
        'lead': {'contact': {'email': 'private@clinic.com'}}})
    index = store.lead_index(user)
    assert index.emails == {'pat@clinic.com'}
    assert index.company_counts == {'clinic.com': 1}
    query_plan = store.db.execute("EXPLAIN QUERY PLAN SELECT id FROM workspace_records WHERE owner=? AND kind='lead'", (user.owner,)).fetchall()
    assert any('USING' in row[3] and 'INDEX' in row[3] for row in query_plan)


def test_cloud_lead_index_paginates_keys_and_includes_pending_recovery(workspace, monkeypatch):
    store, service, local = workspace
    user = store.identity('cloud', 'jwt')
    store.recovery_save(user, 'lead', {'id': 'pending', 'domain': 'pending.com', 'lead': {'contact': {'email': 'pat@pending.com'}}})
    store.recovery_save(store.identity('other', 'jwt2'), 'lead', {'id': 'private', 'domain': 'private.com', 'lead': {'contact': {'email': 'private@private.com'}}})
    page = [{'record_id': f'{i:04}', 'email': f'pat@clinic{i}.com', 'domain': f'clinic{i}.com'} for i in range(500)]
    remote = MagicMock(side_effect=[page, [{'record_id': '0500', 'email': 'last@clinic.com', 'domain': 'clinic.com'}]])
    monkeypatch.setattr(store, '_remote', remote)
    index = store.lead_index(user)
    assert len(index.emails) == 502
    assert 'pat@pending.com' in index.emails and 'private@private.com' not in index.emails
    first, second = remote.call_args_list
    assert first.args[2]['owner_id'] == 'eq.cloud'
    assert first.args[2]['kind'] == 'eq.lead'
    assert first.args[2]['select'] != 'data'
    assert 'offset' not in second.args[2]
    assert second.args[2]['record_id'] == 'gt.0499'


def test_insert_lead_preserves_existing_record_and_is_owner_scoped(workspace):
    store, service, user = workspace
    original = {'id': 'same-email-hash', 'notes': 'Contacted yesterday', 'stage': 'contacted'}
    assert store.insert_lead(user, original)
    assert not store.insert_lead(user, {'id': original['id'], 'notes': '', 'stage': 'new'})
    assert store.get(user, 'lead', original['id']) == original
    assert store.insert_lead(store.identity('other'), {'id': original['id']})


def test_cloud_insert_lead_ignores_conflicts_without_overwriting_recovery(workspace, monkeypatch):
    store, service, local = workspace
    user = store.identity('cloud', 'jwt')
    request = MagicMock(return_value=httpx.Response(201, json=[]))
    monkeypatch.setattr(httpx, 'request', request)
    assert not store.insert_lead(user, {'id': 'existing', 'notes': 'Do not replace'})
    assert request.call_args.kwargs['headers']['Prefer'] == 'resolution=ignore-duplicates,return=representation'
    assert request.call_args.kwargs['json']['owner_id'] == 'cloud'
    assert store.db.execute("SELECT count(*) FROM workspace_records WHERE owner='cloud'").fetchone()[0] == 0


def multi_plan(target=100):
    return CampaignPlan(name="Texas dentists",source="google_maps",niche="dentists",max_leads=target,research_websites=False,
        locations=[{"city":city,"state":"Texas"} for city in ["Austin","Round Rock","Cedar Park"]])


def test_requested_100_three_cities_yield_30_and_recommend_more(workspace,monkeypatch):
    from threading import Event
    store,service,user=workspace
    service.settings=replace(service.settings,openai_key="mock")
    searched=[]
    def discover(plan,*args):
        searched.append(plan.city)
        key=plan.city.replace(' ','').lower()
        return [{"title":f"Clinic {key} {i}","website":f"https://{key}{i}.com"} for i in range(70)]
    service._discover=discover
    def search(domain):
        import re
        number=int(re.search(r'(\d+)\.com',domain)[1])
        return HunterSearch(contacts=[person('pat@'+domain)] if number<10 else [])
    hunter,nb=mock_people(monkeypatch,search,lambda email:Verification(result=["valid","catchall","unknown"][nb.verify.call_count%3]))
    recommend=MagicMock(return_value=[{"city":"Georgetown","state":"Texas","reason":"Nearby market for dental SEO","evidence":[{"url":"https://example.com/cities","title":"City research","observation":"Nearby"}]}])
    monkeypatch.setattr(ResearchService,'recommend_locations',recommend)
    campaign=service.create(user,multi_plan())
    service._run(user,campaign,Event())
    result=store.get(user,'campaign',campaign['id'])
    assert searched==['Austin','Round Rock','Cedar Park'] * 2
    assert result['status']=='shortfall' and result['shortfall']==70
    assert result['progress']['verified']==30 and result['progress']['discovered']==210
    assert [item['leads'] for item in result['locations']]==[10,10,10,0,0,0]
    assert hunter.search.call_count == 210  # repeated Maps rows never repeat enrichment
    assert len(store.list(user,'lead'))==30 and nb.verify.call_count==30
    assert '30 of 100' in result['message']
    assert result['recommendations'][0]['city']=='Georgetown'
    recommend.assert_called_once()


def test_target_counts_people_not_business_attempts_and_stops_before_next_city(workspace,monkeypatch):
    from threading import Event
    store,service,user=workspace
    cities=[]
    def discover(plan,*args):
        cities.append(plan.city)
        return [{"title":f"Clinic {i}","website":f"https://clinic{i}.com"} for i in range(70)]
    service._discover=discover
    def search(domain):
        return HunterSearch(contacts=[person('pat@'+domain),person('sam@'+domain),Contact(email='info@'+domain,provider_type='generic')])
    hunter,nb=mock_people(monkeypatch,search,lambda email:Verification(result='invalid' if email.startswith('pat@') else 'unknown'))
    campaign=service.create(user,multi_plan(50))
    service._run(user,campaign,Event())
    result=store.get(user,'campaign',campaign['id'])
    assert cities==['Austin']
    assert result['status']=='completed' and result['progress']['verified']==50
    assert hunter.search.call_count==50 and nb.verify.call_count==100
    assert len(store.list(user,'lead'))==50
    assert all(row['lead']['verification']['result']=='unknown' for row in store.list(user,'lead'))


def test_multiple_people_per_business_and_email_deduplication(workspace,monkeypatch):
    from threading import Event
    store,service,user=workspace
    service._discover=lambda *args:[{'title':'One','website':'https://one.com'},{'title':'Two','website':'https://two.com'}]
    hunter,nb=mock_people(monkeypatch,lambda domain:HunterSearch(contacts=[person('Pat@shared.com'),person('pat@shared.com'),person('sam@'+domain)]),lambda email:Verification(result='catchall'))
    campaign=service.create(user,plan(max_leads=3, max_leads_per_company=2))
    service._run(user,campaign,Event())
    assert len(store.list(user,'lead'))==3 and nb.verify.call_count==3
    assert store.get(user,'campaign',campaign['id'])['progress']['verified']==3
    # A second request cannot recount saved contacts as new leads.
    repeated=service.create(user,plan(max_leads=3, max_leads_per_company=2))
    service._run(user,repeated,Event())
    assert store.get(user,'campaign',repeated['id'])['progress']['verified']==0
    assert nb.verify.call_count==3


def test_businesses_and_generic_inboxes_never_count_as_people(workspace,monkeypatch):
    from threading import Event
    store,service,user=workspace
    service._discover=lambda *args:[{'title':'Clinic','website':'https://clinic.com'},{'title':'No website'}]
    hunter,nb=mock_people(monkeypatch,lambda domain:HunterSearch(contacts=[Contact(email='info@clinic.com',provider_type='generic'),Contact(email='owner@clinic.com',job_title='Owner')]),lambda email:Verification(result='valid'))
    campaign=service.create(user,plan(max_leads=1))
    service._run(user,campaign,Event())
    assert store.list(user,'lead')==[]
    assert store.get(user,'campaign',campaign['id'])['progress']['verified']==0
    nb.verify.assert_not_called()


def test_cancellation_stops_before_more_people_or_cities(workspace,monkeypatch):
    from threading import Event
    store,service,user=workspace
    cancel=Event()
    discover=MagicMock(return_value=[{'title':'Clinic','website':'https://clinic.com'}])
    service._discover=discover
    def verify(email):
        cancel.set()
        return Verification(result='valid')
    hunter,nb=mock_people(monkeypatch,lambda domain:HunterSearch(contacts=[person('a@clinic.com'),person('b@clinic.com')]),verify)
    campaign=service.create(user,multi_plan())
    service._run(user,campaign,cancel)
    assert store.get(user,'campaign',campaign['id'])['status']=='cancelled'
    assert nb.verify.call_count==1 and discover.call_count==1
    assert len(store.list(user,'lead'))==1


def test_generate_tool_starts_once_and_message_replay_does_not_spend(workspace,settings,monkeypatch):
    store,service,user=workspace
    service.executor.submit=MagicMock()
    agent=ResearchAgent(replace(settings,openai_key='mock'),store,service)
    client=MagicMock(); client.__enter__.return_value=client
    call=NS(type='function_call',name='generate_leads',arguments=multi_plan(50).model_dump_json(),call_id='generate')
    client.responses.create.side_effect=[NS(status='completed',output=[call],output_text='',usage=None),NS(status='completed',output=[],output_text='Your search has started.',usage=None)]
    monkeypatch.setattr(ResearchService,'client',lambda self:client)
    thread=agent.create(user)
    body=AdvisorMessage(message='Fetch 50 dentists across these three Texas cities.',message_id='fetch')
    result=agent.message(user,thread['id'],body)
    agent.message(user,thread['id'],body)
    assert len(result['campaign_ids'])==1
    campaign=store.get(user,'campaign',result['campaign_ids'][0])
    assert campaign['status']=='queued' and len(campaign['plan']['locations'])==3
    assert campaign['thread_id']==thread['id']
    service.executor.submit.assert_called_once()


def test_location_validation_and_duplicate_city_normalization():
    value=multi_plan(100)
    assert value.city=='Austin' and len(value.locations)==3
    duplicate=value.model_dump(); duplicate['locations'] += [{'city':'austin','state':'texas'}]
    assert len(CampaignPlan.model_validate(duplicate).locations)==3
    with pytest.raises(ValueError):
        CampaignPlan(name='Test',source='google_maps',niche='dentists',locations=[{'city':' ','state':'Texas'}])


def test_city_recommendations_require_citations_and_skip_searched_cities(settings,monkeypatch):
    from app.models.workspace import LocationRecommendations
    service=ResearchService(settings)
    service.search=MagicMock(return_value={'summary':'Cities','sources':[{'url':'https://example.com/geography','title':'Geography'}]})
    evidence=[{'title':'Geography','url':'https://example.com/geography','observation':'Nearby'}]
    service.parse=MagicMock(return_value=LocationRecommendations(locations=[
        {'city':'Austin','state':'Texas','reason':'Already searched','evidence':evidence},
        {'city':'Georgetown','state':'Texas','reason':'Nearby','evidence':evidence},
        {'city':'Uncited','state':'Texas','reason':'Unsupported','evidence':[{'title':'Fake','url':'https://fake.com','observation':'Unknown'}]}]))
    assert [item['city'] for item in service.recommend_locations(multi_plan(),{})]==['Georgetown']


def test_workspace_and_export_use_person_policy_including_older_records():
    with TestClient(app) as client:
        client.get('/api/workspace')
        owner='local_'+__import__('hashlib').sha256(client.cookies.get('gm_session').encode()).hexdigest()
        store=app.state.workspace_store; user=store.identity(owner)
        for key,result,named in [('valid','valid',True),('catch','catchall',True),('unknown','unknown',True),
                                 ('invalid','invalid',True),('error','verification_error',True),('generic','valid',False)]:
            item={'id':key,'company':'Clinic','industry':'Dentist','location':'Austin','domain':'clinic.com',
                'category':'needs_review','stage':'new','campaign_ids':['run'],'source':'google_maps','assessment':{'fit':'unknown'},
                'lead':{'verified':False,'contact':{'email':key+'@clinic.com','first_name':'Pat' if named else None},'verification':{'result':result}}}
            store.save(user,'lead',item)
        rows=client.get('/api/workspace').json()['leads']
        assert len(rows)==3 and all(item['lead']['verified'] for item in rows)
        export=client.get('/api/workspace/leads/export').content.decode('utf-8-sig')
        assert all(email in export for email in ['valid@clinic.com','catch@clinic.com','unknown@clinic.com'])
        assert all(email not in export for email in ['invalid@clinic.com','error@clinic.com','generic@clinic.com'])
        subset=client.get('/api/workspace/leads/export?category=unknown').content.decode('utf-8-sig')
        assert 'unknown@clinic.com' in subset and 'valid@clinic.com' not in subset
        assert client.patch('/api/workspace/leads/unknown',json={'stage':'qualified'}).status_code==200


def test_editing_target_and_starting_older_draft_updates_progress(workspace):
    store,service,user=workspace
    service.executor.submit=MagicMock()
    campaign=service.create(user,plan(max_leads=10))
    for key in ['locations','recommendations','lead_ids','policy_version']:
        campaign.pop(key)
    for key in ['target','rejected','no_contact','verification_errors']:
        campaign['progress'].pop(key)
    store.save(user,'campaign',campaign)
    edited=service.update_plan(user,campaign['id'],multi_plan(100),1)
    assert edited['progress']['target']==100
    started=service.start(user,campaign['id'],2)
    assert started['locations']==[] and started['progress']['verification_errors']==0
    assert started['policy_version']=='person-v3'


def test_sixty_people_requires_deeper_same_city_and_stops_exactly(workspace, monkeypatch):
    from threading import Event
    import re
    store, service, user = workspace
    passes = []
    def discover(plan, campaign, *args):
        limit = campaign['locations'][-1]['business_limit']
        passes.append((plan.city, limit))
        return [{'title': f'Clinic {i}', 'website': f'https://clinic{i}.com'} for i in range(limit)]
    service._discover = discover
    def search(domain):
        i = int(re.search(r'(\d+)\.com', domain)[1])
        return HunterSearch(contacts=[person('pat@' + domain)] if i % 2 == 0 else [])
    hunter, nb = mock_people(monkeypatch, search, lambda email: Verification(result='unknown'))
    campaign = service.create(user, plan(max_leads=60))
    service._run(user, campaign, Event())
    result = store.get(user, 'campaign', campaign['id'])
    assert passes == [('Austin', 70), ('Austin', 140)]
    assert result['status'] == 'completed' and result['progress']['verified'] == 60
    assert result['shortfall'] == 0 and result['stop_reason'] == 'target_reached'
    assert len(store.list(user, 'lead')) == 60 and nb.verify.call_count == 60
    assert hunter.search.call_count == 119
    assert result['progress']['discovered'] == 140


@pytest.mark.parametrize('rounds', [1, 3, 5])
def test_city_depth_budget_and_no_unapproved_city(workspace, monkeypatch, rounds):
    from threading import Event
    store, service, user = workspace
    limits = []
    def discover(plan, campaign, *args):
        assert plan.city == 'Austin' and plan.state == 'Texas'
        limit = campaign['locations'][-1]['business_limit']
        limits.append(limit)
        return [{'title': f'Clinic {i}', 'website': f'https://clinic{i}.com'} for i in range(limit)]
    service._discover = discover
    hunter, nb = mock_people(monkeypatch, lambda domain: HunterSearch(), lambda email: Verification(result='valid'))
    campaign = service.create(user, plan(max_leads=60, max_city_rounds=rounds))
    service._run(user, campaign, Event())
    result = store.get(user, 'campaign', campaign['id'])
    assert limits == [70 * i for i in range(1, rounds + 1)]
    assert result['status'] == 'shortfall' and result['shortfall'] == 60
    assert result['stop_reason'] == 'city_depth_budget_reached'
    assert hunter.search.call_count == rounds * 70
    nb.verify.assert_not_called()


def test_unsaturated_city_is_not_repeated(workspace, monkeypatch):
    from threading import Event
    store, service, user = workspace
    service._discover = MagicMock(return_value=[{'title': 'Clinic', 'website': 'https://clinic.com'}])
    mock_people(monkeypatch, lambda domain: HunterSearch(), lambda email: Verification(result='valid'))
    campaign = service.create(user, plan())
    service._run(user, campaign, Event())
    service._discover.assert_called_once()
    assert store.get(user, 'campaign', campaign['id'])['stop_reason'] == 'approved_locations_exhausted'


def test_valid_only_never_counts_catchall_or_unknown(workspace, monkeypatch):
    from threading import Event
    store, service, user = workspace
    service._discover = lambda *args: [{'title': 'Clinic', 'website': 'https://clinic.com'}]
    statuses = iter(['catchall', 'unknown', 'valid'])
    mock_people(monkeypatch, lambda domain: HunterSearch(contacts=[person(f'p{i}@clinic.com') for i in range(3)]),
        lambda email: Verification(result=next(statuses)))
    campaign = service.create(user, plan(max_leads=1, email_policy='valid_only'))
    service._run(user, campaign, Event())
    assert [row['lead']['verification']['result'] for row in store.list(user, 'lead')] == ['valid']
    assert campaign['progress']['rejected'] == 2


@pytest.mark.parametrize('provider', ['hunter', 'neverbounce'])
def test_provider_quota_stops_before_spending_on_more_cities(workspace, monkeypatch, provider):
    from threading import Event
    store, service, user = workspace
    service._discover = MagicMock(return_value=[{'title': 'Clinic', 'website': 'https://clinic.com'}])
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(reason='hunter_quota_exhausted') if provider == 'hunter' else HunterSearch(contacts=[person('pat@clinic.com')]),
        lambda email: Verification(result='verification_error', failure_reason='neverbounce_quota_exhausted'))
    campaign = service.create(user, multi_plan(60))
    service._run(user, campaign, Event())
    assert campaign['status'] == 'failed' and campaign['shortfall'] == 60
    service._discover.assert_called_once()
    assert campaign['progress']['verified'] == 0


def test_unknown_requested_fit_does_not_count_or_spend_on_enrichment(workspace, monkeypatch):
    from threading import Event
    store, service, user = workspace
    service._discover = lambda *args: [{'title': 'Clinic', 'website': 'https://clinic.com'}]
    monkeypatch.setattr(ResearchService, 'assess', lambda *args: {'fit': 'unknown', 'excluded': False})
    hunter, nb = mock_people(monkeypatch, lambda domain: HunterSearch(), lambda email: Verification(result='valid'))
    value = CampaignPlan(name='Fit', source='company_websites', niche='dentists', websites=['https://clinic.com'],
        qualification_criteria=['Owner operated'], research_websites=True)
    campaign = service.create(user, value)
    service._run(user, campaign, Event())
    assert campaign['progress']['review'] == 1 and campaign['progress']['verified'] == 0
    hunter.search.assert_not_called()


def test_business_memory_partial_update_and_owner_isolation(workspace, settings):
    store, service, user = workspace
    agent = ResearchAgent(settings, store, service)
    agent.execute('remember_business_context', {'offer': 'SEO for dental clinics', 'geography': 'Texas'}, user, None, [])
    agent.execute('remember_business_context', {'offer': None, 'geography': 'Ontario'}, user, None, [])
    profile = store.get(user, 'profile', 'business')['profile']
    assert profile['offer'] == 'SEO for dental clinics' and profile['geography'] == 'Ontario'
    assert store.list(store.identity('other'), 'profile') == []
    with pytest.raises(ValueError):
        agent.execute('remember_business_context', {'invented': 'field'}, user, None, [])


def test_stop_tool_cannot_cancel_another_workspace(workspace, settings):
    store, service, user = workspace
    service.executor.submit = MagicMock()
    campaign = service.create(user, plan())
    service.start(user, campaign['id'], 1)
    agent = ResearchAgent(settings, store, service)
    with pytest.raises(HTTPException):
        agent.execute('stop_lead_search', {'campaign_id': campaign['id']}, store.identity('other'), None, [])
    assert not service.jobs[campaign['id']].is_set()
    assert agent.execute('stop_lead_search', {'campaign_id': campaign['id']}, user, None, [])['requested']
    assert service.jobs[campaign['id']].is_set()


def test_deeper_actor_input_keeps_original_geography(sdk, search_request):
    from app.services.apify_service import ApifyService
    service = ApifyService(sdk)
    service.start(search_request, business_limit=140)
    payload = sdk.actor.return_value.start.call_args.kwargs['run_input']
    assert payload['maxCrawledPlacesPerSearch'] == 140
    assert payload['locationQuery'] == 'Austin, Texas'
    with pytest.raises(ValueError):
        service.start(search_request, business_limit=1000)


@pytest.mark.parametrize('verdict,cited,expected_fit', [('met', True, 'strong'), ('met', False, 'unknown'), ('unknown', True, 'unknown')])
def test_positive_criteria_need_individual_cited_evidence(settings, verdict, cited, expected_fit):
    from app.models.workspace import Assessment
    research = ResearchService(settings)
    evidence = {'title': 'Clinic', 'url': 'https://clinic.com/about', 'observation': 'Owner operated'}
    research.search = MagicMock(return_value={'summary': 'Clinic', 'sources': [{'url': evidence['url']}]})
    research.parse = MagicMock(return_value=Assessment(summary='Company fit', fit='strong', reasons=[], unknowns=[],
        excluded=False, evidence=[evidence], criteria_checks=[{'criterion': 'Owner operated', 'verdict': verdict,
            'evidence': [evidence] if cited else []}]))
    value = CampaignPlan(name='Fit', source='company_websites', niche='dentists', websites=['https://clinic.com'],
        qualification_criteria=['Owner operated'], research_websites=True)
    result = research.assess(Business(business_website='https://clinic.com'), value, {})
    assert result['fit'] == expected_fit


def test_workspace_cannot_run_concurrent_new_person_targets(workspace):
    store, service, user = workspace
    service.settings = replace(service.settings, max_active_runs=3)
    service.executor.submit = MagicMock()
    first = service.create(user, plan())
    service.start(user, first['id'], 1)
    second = service.create(user, plan())
    with pytest.raises(HTTPException) as error:
        service.start(user, second['id'], 1)
    assert error.value.status_code == 409
    assert store.get(user, 'campaign', second['id'])['status'] == 'draft'


def test_older_draft_keeps_its_original_one_pass_budget(workspace):
    store, service, user = workspace
    service.executor.submit = MagicMock()
    campaign = service.create(user, plan())
    campaign['plan'].pop('max_city_rounds')
    campaign['plan'].pop('email_policy')
    store.save(user, 'campaign', campaign)
    started = service.start(user, campaign['id'], 1)
    assert started['plan']['max_city_rounds'] == 1
    assert started['plan']['email_policy'] == 'accepted'


@pytest.mark.parametrize('provider', ['hunter', 'neverbounce'])
def test_repeated_provider_errors_trip_circuit_breaker(workspace, monkeypatch, provider):
    from threading import Event
    store, service, user = workspace
    service._discover = MagicMock(return_value=[{'title': f'Clinic {i}', 'website': f'https://clinic{i}.com'} for i in range(70)])
    hunter, nb = mock_people(monkeypatch,
        lambda domain: HunterSearch(reason='hunter_network_error') if provider == 'hunter' else HunterSearch(contacts=[person('pat@' + domain)]),
        lambda email: Verification(result='verification_error', failure_reason='neverbounce_network_error'))
    campaign = service.create(user, multi_plan(60))
    service._run(user, campaign, Event())
    assert campaign['status'] == 'failed' and campaign['shortfall'] == 60
    assert hunter.search.call_count == 3
    assert nb.verify.call_count == (3 if provider == 'neverbounce' else 0)
    service._discover.assert_called_once()
