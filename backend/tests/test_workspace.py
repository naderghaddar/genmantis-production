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
    assert searched==['Austin','Round Rock','Cedar Park']
    assert result['status']=='shortfall' and result['shortfall']==70
    assert result['progress']['verified']==30 and result['progress']['discovered']==210
    assert [item['leads'] for item in result['locations']]==[10,10,10]
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
    campaign=service.create(user,plan(max_leads=3))
    service._run(user,campaign,Event())
    assert len(store.list(user,'lead'))==3 and nb.verify.call_count==3
    assert store.get(user,'campaign',campaign['id'])['progress']['verified']==3
    # A second request cannot recount saved contacts as new leads.
    repeated=service.create(user,plan(max_leads=3))
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
    assert started['policy_version']=='person-v2'
