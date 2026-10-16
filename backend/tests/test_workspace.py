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


@pytest.mark.parametrize("result,expected",[("valid","verified"),("catchall","needs_review"),("invalid","needs_review"),("verification_error","needs_review")])
def test_all_discovery_sources_use_hunter_and_neverbounce(workspace, monkeypatch,result,expected):
    store, service, user = workspace
    service._discover = lambda *args: [{"title":"Clinic","website":"https://example.com","categoryName":"Clinic"}]
    hunter = MagicMock(); hunter.search.return_value = HunterSearch(contacts=[Contact(email="owner@example.com",job_title="Owner",first_name="Pat")])
    nb = MagicMock(); nb.verify.return_value = Verification(result=result)
    monkeypatch.setattr("app.services.campaign_service.HunterService",lambda *args: hunter)
    monkeypatch.setattr("app.services.campaign_service.NeverBounceService",lambda *args: nb)
    for source in ["google_maps","web_research","company_websites"]:
        identity = store.identity("user_" + source)
        campaign = service.create(identity,CampaignPlan(name="Test",source=source,niche="Clinics",city="Austin",state="Texas",query="Austin clinics",websites=["https://example.com"],research_websites=False))
        from threading import Event
        service._run(identity,campaign,Event())
        records = store.list(identity,"lead")
        assert len(records) == 1
        assert records[0]["category"] == expected
        assert records[0]["lead"]["verified"] == (result == "valid")
        assert records[0]["lead"]["verification"]["result"] == result
        assert store.get(identity,"campaign",campaign["id"])["status"] == "completed"
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
    assert store.list(user,"lead")[0]["category"] == "excluded"
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
        for key,result in [('good','valid'),('bad','catchall')]:
            item={"id":key,"company":"=Example","industry":"Clinic","location":"Austin","domain":"example.com","category":"verified", "stage":"new", "campaign_ids":[],"source":"google_maps","assessment":{"fit":"unknown"},"lead":{"verified":True,"contact":{"email":"owner@example.com"},"verification":{"result":result}}}
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


def test_research_tools_strict_and_no_execution_tool():
    for tool in RESEARCH_TOOLS:
        assert tool['strict'] is True
        assert tool['parameters']['additionalProperties'] is False
        assert set(tool['parameters']['required']) == set(tool['parameters']['properties'])
    assert not any('start' in tool['name'] for tool in RESEARCH_TOOLS)


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
