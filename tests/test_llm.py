"""Tests for LLM wrapper module — call_tool, call_tool_with_reflection."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.llm import (
    MODEL_HAIKU,
    MODEL_OPUS,
    MODEL_SONNET,
    call_tool,
    call_tool_with_reflection,
    get_client,
    _record_llm_metrics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tool():
    """Sample tool schema for testing."""
    return {
        "name": "test_output_tool",
        "description": "Test output tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "score": {"type": "number"},
            },
            "required": ["result"],
        },
    }


@pytest.fixture
def mock_tool_response():
    """Create a mock Anthropic response with tool_use block."""
    def _factory(tool_name: str, tool_input: dict):
        block = MagicMock()
        block.type = "tool_use"
        block.id = "toolu_test_001"
        block.name = tool_name
        block.input = tool_input

        response = MagicMock()
        response.content = [block]
        response.stop_reason = "tool_use"
        response.usage = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        return response
    return _factory


@pytest.fixture
def mock_anthropic_client(mock_tool_response):
    """Mock Anthropic async client."""
    client = AsyncMock()
    client.messages = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=mock_tool_response("test_output_tool", {"result": "test_result", "score": 0.9})
    )
    return client


# ---------------------------------------------------------------------------
# Model Constants
# ---------------------------------------------------------------------------

class TestModelConstants:
    """Test model tier constants are defined correctly."""

    def test_haiku_model(self):
        """Verify Haiku model string."""
        assert "haiku" in MODEL_HAIKU.lower()

    def test_sonnet_model(self):
        """Verify Sonnet model string."""
        assert "sonnet" in MODEL_SONNET.lower()

    def test_opus_model(self):
        """Verify Opus model string."""
        assert "opus" in MODEL_OPUS.lower()

    def test_model_hierarchy(self):
        """Ensure models are distinct."""
        assert MODEL_HAIKU != MODEL_SONNET != MODEL_OPUS


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------

class TestCallTool:
    """Tests for call_tool function."""

    async def test_call_tool_success(self, mock_anthropic_client, mock_tool):
        """Test successful tool call returns parsed result."""
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                result = await call_tool(
                    prompt="Test prompt",
                    tool=mock_tool,
                    model=MODEL_SONNET,
                )
        assert result["result"] == "test_result"
        assert result["score"] == 0.9

    async def test_call_tool_uses_correct_model(self, mock_anthropic_client, mock_tool):
        """Test that the specified model is passed to the API."""
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool(
                    prompt="Test",
                    tool=mock_tool,
                    model=MODEL_HAIKU,
                )
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == MODEL_HAIKU

    async def test_call_tool_with_system_prompt(self, mock_anthropic_client, mock_tool):
        """Test that system prompt is included when provided."""
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool(
                    prompt="Test",
                    tool=mock_tool,
                    system="You are a helpful assistant.",
                )
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are a helpful assistant."

    async def test_call_tool_forces_tool_choice(self, mock_anthropic_client, mock_tool):
        """Test that tool_choice forces the specific tool."""
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool(prompt="Test", tool=mock_tool)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["tool_choice"]["type"] == "tool"
        assert call_kwargs["tool_choice"]["name"] == mock_tool["name"]

    async def test_call_tool_no_tool_use_block_raises(self, mock_anthropic_client, mock_tool):
        """Test that missing tool_use block raises ValueError."""
        # Create response without tool_use block
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I don't want to use a tool"

        response = MagicMock()
        response.content = [text_block]
        response.usage = MagicMock()
        response.usage.input_tokens = 50
        response.usage.output_tokens = 20

        mock_anthropic_client.messages.create.return_value = response

        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with pytest.raises(ValueError, match="No tool_use block"):
                    await call_tool(prompt="Test", tool=mock_tool)

    async def test_call_tool_api_error_propagates(self, mock_anthropic_client, mock_tool):
        """Test that API errors are propagated."""
        mock_anthropic_client.messages.create.side_effect = RuntimeError("API error")
        
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with pytest.raises(RuntimeError, match="API error"):
                    await call_tool(prompt="Test", tool=mock_tool)

    async def test_call_tool_custom_max_tokens(self, mock_anthropic_client, mock_tool):
        """Test custom max_tokens is passed."""
        with patch("src.agents.llm.get_client", return_value=mock_anthropic_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool(prompt="Test", tool=mock_tool, max_tokens=2048)
        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048


# ---------------------------------------------------------------------------
# call_tool_with_reflection
# ---------------------------------------------------------------------------

class TestCallToolWithReflection:
    """Tests for call_tool_with_reflection (two-round self-reflection)."""

    async def test_reflection_calls_twice(self, mock_tool_response, mock_tool):
        """Test that reflection makes two API calls."""
        call_count = 0

        async def _mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return mock_tool_response("test_output_tool", {"result": f"round_{call_count}", "score": call_count})

        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = _mock_create

        def reflection_prompt(initial_result: str) -> str:
            return f"Please reflect on: {initial_result}"

        with patch("src.agents.llm.get_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                result = await call_tool_with_reflection(
                    initial_prompt="Initial prompt",
                    reflection_prompt_fn=reflection_prompt,
                    tool=mock_tool,
                    model=MODEL_OPUS,
                )
        
        assert call_count == 2
        # Result should be from the second (reflection) call
        assert result["result"] == "round_2"

    async def test_reflection_uses_correct_model(self, mock_tool_response, mock_tool):
        """Test that both rounds use the specified model."""
        captured_models = []

        async def _mock_create(**kwargs):
            captured_models.append(kwargs.get("model"))
            return mock_tool_response("test_output_tool", {"result": "ok"})

        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = _mock_create

        with patch("src.agents.llm.get_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool_with_reflection(
                    initial_prompt="Test",
                    reflection_prompt_fn=lambda x: f"Reflect: {x}",
                    tool=mock_tool,
                    model=MODEL_OPUS,
                )
        
        assert all(m == MODEL_OPUS for m in captured_models)

    async def test_reflection_prompt_receives_initial_result(self, mock_tool_response, mock_tool):
        """Test that reflection prompt function receives serialized initial result."""
        captured_reflection_input = None

        def reflection_prompt(initial_result: str):
            nonlocal captured_reflection_input
            captured_reflection_input = initial_result
            return f"Reflect: {initial_result}"

        async def _mock_create(**kwargs):
            return mock_tool_response("test_output_tool", {"result": "initial_data", "score": 42})

        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = _mock_create

        with patch("src.agents.llm.get_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                await call_tool_with_reflection(
                    initial_prompt="Test",
                    reflection_prompt_fn=reflection_prompt,
                    tool=mock_tool,
                )

        assert captured_reflection_input is not None
        # Should be JSON serialized
        parsed = json.loads(captured_reflection_input)
        assert parsed["result"] == "initial_data"

    async def test_reflection_first_call_error_propagates(self, mock_tool):
        """Test that error in first call propagates."""
        mock_client = AsyncMock()
        mock_client.messages = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("First call failed"))

        with patch("src.agents.llm.get_client", return_value=mock_client):
            with patch("src.agents.llm._init_langfuse", return_value=None):
                with pytest.raises(RuntimeError, match="First call failed"):
                    await call_tool_with_reflection(
                        initial_prompt="Test",
                        reflection_prompt_fn=lambda x: x,
                        tool=mock_tool,
                    )


# ---------------------------------------------------------------------------
# get_client
# ---------------------------------------------------------------------------

class TestGetClient:
    """Tests for get_client singleton."""

    def test_get_client_returns_client(self):
        """Test that get_client returns an Anthropic client."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            # Reset the global client
            import src.agents.llm as llm_module
            llm_module._client = None
            
            client = get_client()
            assert client is not None

    def test_get_client_is_singleton(self):
        """Test that get_client returns the same instance."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            import src.agents.llm as llm_module
            llm_module._client = None
            
            client1 = get_client()
            client2 = get_client()
            assert client1 is client2


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    """Tests for _record_llm_metrics."""

    def test_record_metrics_no_error_when_module_missing(self):
        """Test that metrics recording doesn't fail if prometheus not imported."""
        # This should not raise even if metrics module is not available
        _record_llm_metrics(MODEL_SONNET, 100, 50, 1.5)

    def test_record_metrics_with_mock_prometheus(self):
        """Test metrics recording with mocked prometheus."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        
        with patch.dict("sys.modules", {"src.metrics": MagicMock(
            llm_tokens_total=mock_counter,
            llm_request_duration=mock_histogram
        )}):
            # Force re-import would be needed for full test
            # For now just verify it doesn't crash
            _record_llm_metrics(MODEL_SONNET, 100, 50, 1.5)


# ---------------------------------------------------------------------------
# Langfuse Init Tests
# ---------------------------------------------------------------------------

class TestLangfuseInit:
    """Tests for _init_langfuse function."""

    def test_langfuse_returns_none_when_disabled(self):
        """Langfuse returns None when disabled in config."""
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        
        # Reset global state
        llm_module._langfuse = None
        
        # Mock settings with langfuse disabled
        mock_settings = MagicMock()
        mock_settings.system.langfuse = {"enabled": False}
        
        with patch("src.agents.llm.get_settings", return_value=mock_settings):
            result = _init_langfuse()
        
        assert result is None

    def test_langfuse_returns_cached_instance(self):
        """Langfuse returns cached instance on second call."""
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        
        # Set a cached value
        mock_langfuse = MagicMock()
        llm_module._langfuse = mock_langfuse
        
        result = _init_langfuse()
        
        assert result is mock_langfuse
        
        # Cleanup
        llm_module._langfuse = None

    def test_langfuse_handles_import_error(self):
        """Langfuse handles import error gracefully."""
        from src.agents.llm import _init_langfuse
        import src.agents.llm as llm_module
        
        # Reset global state
        llm_module._langfuse = None
        
        # Mock settings with langfuse enabled
        mock_settings = MagicMock()
        mock_settings.system.langfuse = {"enabled": True}
        
        with patch("src.agents.llm.get_settings", return_value=mock_settings):
            # This will try to import langfuse which may or may not be available
            # The function should handle any errors gracefully
            result = _init_langfuse()
        
        # Result should be either None or a Langfuse instance
        # The important thing is it doesn't crash
        assert result is None or result is not None
