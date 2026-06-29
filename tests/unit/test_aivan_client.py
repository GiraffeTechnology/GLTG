import pytest
import respx
import httpx
from gltg.integrations.aivan_client import AivanClient


@pytest.mark.asyncio
@respx.mock
async def test_trigger_questionnaire_ok():
    respx.post("http://localhost:8765/invoke").mock(
        return_value=httpx.Response(200, json={"status": "ok", "output": "questionnaire sent"})
    )
    client = AivanClient()
    result = await client.trigger_questionnaire("session-001", {"enquiry_id": "e-001"})
    assert result["status"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_trigger_questionnaire_aivan_error_does_not_raise():
    respx.post("http://localhost:8765/invoke").mock(
        return_value=httpx.Response(200, json={"status": "error", "output": "LLM unavailable"})
    )
    client = AivanClient()
    result = await client.trigger_questionnaire("session-002", {})
    assert result["status"] == "error"   # error from aivan, not an exception
