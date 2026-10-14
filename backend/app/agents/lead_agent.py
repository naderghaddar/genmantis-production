import json
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException

from app.agents.tool_registry import START_LEAD_GENERATION, execute_tool
from app.models.agent_schemas import AgentMessageRequest, ChatMessage, ConversationData, ConversationView
from app.services.conversation_store import ConversationStore
from app.services.openai_service import OpenAIService
from app.services.run_store import RunManager
from app.services.search_plan_service import update_plan


class LeadAgent:
    def __init__(self, store: ConversationStore, openai: OpenAIService, manager: RunManager):
        self.store, self.openai, self.manager = store, openai, manager

    @contextmanager
    def locked(self, conversation_id: str):
        lock = self.store.operation_lock(conversation_id)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Another conversation action is in progress. Please wait and retry.")
        try:
            yield
        finally:
            lock.release()

    def view(self, conversation: ConversationData) -> ConversationView:
        run = None
        if conversation.run_id:
            try:
                run = self.manager.get(conversation.run_id, conversation.owner_id)
            except HTTPException:
                if conversation.plan.status == "running":
                    conversation.plan.status = "failed"
                    self.append(conversation, "The run is no longer available in this backend process. Check Apify Console before starting a new search.")
                    self.store.save(conversation)
            if run and run.status in {"completed", "failed"} and conversation.announced_run_status != run.status:
                if conversation.executions.get(str(conversation.plan.version)) == run.run_id:
                    conversation.plan.status = "completed" if run.status == "completed" else "failed"
                conversation.announced_run_status = run.status
                if run.status == "failed":
                    message = "Your lead search failed. " + run.message
                else:
                    p = run.progress
                    message = (f"Your search is complete. {p.businesses_eligible} businesses were eligible for enrichment; "
                               f"{p.verified_emails} have a verified selected contact and {p.unverified_contacts} have an unverified selected contact. "
                               f"{p.businesses_filtered} were excluded by filters or the business limit. Your CSV files are ready.")
                self.append(conversation, message)
                self.store.save(conversation)
        return ConversationView(id=conversation.id, messages=conversation.messages, plan=conversation.plan,
            confirmation_required=conversation.plan.status in {"ready_for_confirmation", "confirmed"} and str(conversation.plan.version) not in conversation.executions, run=run, usage=conversation.usage)

    @staticmethod
    def append(conversation: ConversationData, content: str):
        conversation.messages.append(ChatMessage(id=uuid4().hex, role="assistant", content=content))

    def create(self, owner: str):
        return self.view(self.store.create(owner))

    def get(self, conversation_id: str, owner: str):
        with self.locked(conversation_id):
            return self.view(self.store.get(conversation_id, owner))

    def message(self, conversation_id: str, owner: str, body: AgentMessageRequest):
        with self.locked(conversation_id):
            conversation = self.store.get(conversation_id, owner)
            if any(message.id == body.message_id for message in conversation.messages):
                return self.view(conversation)
            if len(conversation.messages) >= 81:
                raise HTTPException(429, "Conversation message limit reached. Start a new conversation.")
            if not body.message.strip():
                raise HTTPException(422, "Enter a message.")
            try:
                interpretation, response_id = self.openai.interpret(conversation, body.message.strip())
            except HTTPException:
                self.store.save(conversation)
                raise
            previous_version = conversation.plan.version
            previous_status = conversation.plan.status
            conversation.plan = update_plan(conversation.plan, interpretation)
            if conversation.plan.version != previous_version:
                conversation.approved_version = None
            elif previous_status in {"confirmed", "running", "completed", "failed"}:
                conversation.plan.status = previous_status
            conversation.previous_response_id = response_id
            conversation.messages.append(ChatMessage(id=body.message_id, role="user", content=body.message.strip()))
            reply = interpretation.assistant_message
            if conversation.plan.limitations:
                reply += "\n\n" + "\n".join(conversation.plan.limitations)
            self.append(conversation, reply)
            self.store.save(conversation)
            return self.view(conversation)

    def edit(self, plan_id: str, owner: str, version: int):
        conversation = self.store.get(plan_id, owner, by_plan=True)
        with self.locked(conversation.id):
            conversation = self.store.get(plan_id, owner, by_plan=True)
            if version != conversation.plan.version:
                raise HTTPException(409, "This plan version is stale. Refresh the conversation.")
            conversation.plan.version += 1
            conversation.plan.status = "collecting_requirements"
            conversation.approved_version = None
            self.append(conversation, "Tell me what you'd like to change in this search.")
            self.store.save(conversation)
            return self.view(conversation)

    def confirm(self, plan_id: str, owner: str, version: int):
        conversation = self.store.get(plan_id, owner, by_plan=True)
        with self.locked(conversation.id):
            conversation = self.store.get(plan_id, owner, by_plan=True)
            if version != conversation.plan.version:
                raise HTTPException(409, "This plan version is stale. Review the updated plan before confirming.")
            if str(version) in conversation.executions:
                return self.view(conversation)
            if version in conversation.execution_attempted_versions:
                raise HTTPException(409, "An interrupted execution is recorded. Check Apify Console before preparing a new plan version.")
            if conversation.plan.status not in {"ready_for_confirmation", "confirmed"} or conversation.plan.limitations:
                raise HTTPException(409, "Complete a supported search plan before confirming.")
            try:
                self.manager.settings.require_keys()
            except ValueError as error:
                raise HTTPException(503, str(error)) from error
            # Validation and ownership precede the durable, exact-version approval record.
            request = conversation.plan.execution_request()
            conversation.approved_version = version
            conversation.plan.status = "confirmed"
            self.store.save(conversation)
            try:
                response = self.openai.tool_turn(conversation, START_LEAD_GENERATION,
                    [{"role": "developer", "content": "The user clicked Start Lead Search for this exact approved plan. Call start_lead_generation with exactly: " + request.model_dump_json()}],
                    conversation.previous_response_id, True)
            except HTTPException:
                self.store.save(conversation)
                raise
            calls = [item for item in response.output if item.type == "function_call"]
            if len(calls) != 1:
                raise HTTPException(502, "Expected exactly one lead-generation tool call. No new job was started.")
            call = calls[0]
            result = execute_tool(call.name, call.arguments, conversation, owner, self.manager, self.store.save)
            # Save execution immediately, before any model follow-up can fail or be retried.
            conversation.previous_response_id = response.id
            self.append(conversation, "Your lead search has started. Progress below comes directly from the running job.")
            self.store.save(conversation)
            try:
                final = self.openai.tool_turn(conversation, START_LEAD_GENERATION,
                    [{"type": "function_call_output", "call_id": call.call_id, "output": json.dumps(result)}], response.id, False)
                # No further function calls are dispatched. The entire loop is bounded to two turns.
                if not any(item.type == "function_call" for item in final.output):
                    conversation.previous_response_id = final.id
                else:
                    conversation.previous_response_id = None
            except HTTPException:
                # The job exists and remains associated with the approved version.
                conversation.previous_response_id = None
            self.store.save(conversation)
            return self.view(conversation)
