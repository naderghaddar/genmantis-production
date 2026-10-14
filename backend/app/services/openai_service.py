from fastapi import HTTPException
from openai import APIError, OpenAI

from app.agents.system_prompt import SYSTEM_PROMPT
from app.config import Settings
from app.models.agent_schemas import AgentInterpretation, ConversationData


class OpenAIService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        if not self.settings.openai_key:
            raise HTTPException(503, "Set OPENAI_API_KEY in backend/.env to use the assistant. Manual search remains available.")
        return OpenAI(api_key=self.settings.openai_key, timeout=30, max_retries=1)

    @staticmethod
    def check_budget(conversation: ConversationData):
        if conversation.usage.input_tokens + conversation.usage.output_tokens >= 100000 or conversation.usage.requests >= 80:
            raise HTTPException(429, "Conversation token/request budget reached. Start a new conversation.")
        conversation.usage.requests += 1

    @staticmethod
    def record_usage(conversation: ConversationData, response):
        usage = response.usage
        if usage:
            conversation.usage.input_tokens += usage.input_tokens
            conversation.usage.output_tokens += usage.output_tokens

    def interpret(self, conversation: ConversationData, message: str):
        self.check_budget(conversation)
        try:
            with self._client() as client:
                history = [{"role": item.role, "content": item.content} for item in conversation.messages[-12:]] if not conversation.previous_response_id else []
                response = client.responses.parse(model=self.settings.openai_model, instructions=SYSTEM_PROMPT,
                    previous_response_id=conversation.previous_response_id, store=True,
                    input=[*history, {"role": "developer", "content": "Authoritative current plan: " + conversation.plan.model_dump_json()},
                           {"role": "user", "content": message}],
                    tools=[], tool_choice="none", parallel_tool_calls=False,
                    text_format=AgentInterpretation, max_output_tokens=2500)
            self.record_usage(conversation, response)
            if response.status != "completed" or response.output_parsed is None or any(item.type == "function_call" for item in response.output):
                raise HTTPException(502, "The assistant could not prepare a valid response. Please try again.")
            return AgentInterpretation.model_validate(response.output_parsed), response.id
        except (APIError, ValueError):
            raise HTTPException(502, "OpenAI is unavailable or returned an invalid response. Check model access and API configuration, then retry.") from None

    def tool_turn(self, conversation: ConversationData, tool: dict, inputs: list[dict], previous_id: str | None, force: bool):
        self.check_budget(conversation)
        try:
            with self._client() as client:
                response = client.responses.create(model=self.settings.openai_model, instructions=SYSTEM_PROMPT,
                    previous_response_id=previous_id, store=True, input=inputs, tools=[tool],
                    tool_choice={"type": "function", "name": tool["name"]} if force else "none",
                    parallel_tool_calls=False, max_output_tokens=1800)
            self.record_usage(conversation, response)
            if response.status != "completed":
                raise HTTPException(502, "Assistant tool request did not complete. Retry the same plan confirmation.")
            return response
        except APIError:
            raise HTTPException(502, "OpenAI tool request failed. Retry the same plan confirmation.") from None
