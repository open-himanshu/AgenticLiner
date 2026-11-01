"""
Provider-switchable LLM caller for the Autopilot agent mode.

Supports PROVIDER=gemini|groq|ollama read from the environment.
Model names come from GEMINI_MODEL / GROQ_MODEL / OLLAMA_MODEL.
No hardcoded model names.  Retries on HTTP 429/503.
Automatic function calling is disabled so our loop runs every tool.

Adapted from legacy_team/backend/planner/test_tool_calling.py and
legacy_team/backend/planner/llm_doctor.py — the originals are untouched.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
MAX_RATE_LIMIT_RETRIES = 6


class ProviderError(Exception):
    """Raised when an LLM provider returns a non-retryable error."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_env(name: str, fallback: str = "") -> str:
    """Read, strip quotes/BOM, and return an env var."""
    value = os.getenv(name, fallback).strip()
    return value.strip("\"'\ufeff\r\n").strip()


def _retry_delay(headers: Any, body: str) -> float:
    """Parse Retry-After or body text for a suitable backoff delay."""
    if headers:
        retry_after = (
            getattr(headers, "get", lambda *_: None)("Retry-After")
            or getattr(headers, "get", lambda *_: None)("retry-after")
        )
        if retry_after:
            try:
                return max(0.0, float(retry_after)) + 1.0
            except (TypeError, ValueError):
                try:
                    rt = parsedate_to_datetime(retry_after)
                    if rt.tzinfo is None:
                        rt = rt.replace(tzinfo=timezone.utc)
                    return max(0.0, (rt - datetime.now(timezone.utc)).total_seconds()) + 1.0
                except (TypeError, ValueError, OverflowError):
                    pass
        retry_after_ms = getattr(headers, "get", lambda *_: None)("retry-after-ms")
        if retry_after_ms:
            try:
                return max(0.0, float(retry_after_ms) / 1000) + 1.0
            except (TypeError, ValueError):
                pass
    match = re.search(
        r"try again in\s+(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?|ms|minutes?|mins?|m|seconds?|secs?|s)\b",
        body, re.IGNORECASE,
    )
    if match:
        delay = float(match.group(1))
        unit = match.group(2).lower()
        if unit in {"ms", "msec", "msecs", "millisecond", "milliseconds"}:
            delay /= 1000
        elif unit in {"m", "min", "mins", "minute", "minutes"}:
            delay *= 60
        return max(0.0, delay) + 1.0
    return 1.0


def _safe_error(body: str, api_key: str = "") -> str:
    """Redact secrets from error messages."""
    if api_key:
        body = body.replace(api_key, "[REDACTED]")
    return re.sub(
        r"(?im)authorization\s*[:=][^\r\n,;}]*",
        "Authorization: [REDACTED]",
        body,
    )


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

def get_provider_config() -> Dict[str, str]:
    """Return provider name and model from environment, raising on missing values."""
    provider = _clean_env("PROVIDER", "gemini").lower()
    if provider == "gemini":
        api_key = _clean_env("GEMINI_API_KEY")
        model = _clean_env("GEMINI_MODEL")
        if not api_key or not model:
            raise ProviderError("GEMINI_API_KEY and GEMINI_MODEL must be set.")
        return {"provider": "gemini", "model": model, "api_key": api_key}
    elif provider == "groq":
        api_key = _clean_env("GROQ_API_KEY")
        model = _clean_env("GROQ_MODEL")
        if not api_key or not model:
            raise ProviderError("GROQ_API_KEY and GROQ_MODEL must be set.")
        return {"provider": "groq", "model": model, "api_key": api_key}
    elif provider == "ollama":
        model = _clean_env("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        return {"provider": "ollama", "model": model or DEFAULT_OLLAMA_MODEL, "api_key": ""}
    else:
        raise ProviderError(f'PROVIDER must be "gemini", "groq", or "ollama", got "{provider}".')


# ---------------------------------------------------------------------------
# Gemini caller
# ---------------------------------------------------------------------------

def _call_gemini(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
    api_key: str,
) -> Dict[str, Any]:
    """Call Gemini with tool declarations, automatic calling disabled."""
    from google import genai
    from google.genai import errors, types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=60_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    declarations = [
        types.FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters_json_schema=t["function"]["parameters"],
        )
        for t in (tools or [])
    ]
    system_instruction = next(
        (m["content"] for m in messages if m["role"] == "system"), ""
    )
    config_kwargs: Dict[str, Any] = {
        "system_instruction": system_instruction,
        "temperature": 0,
    }
    if declarations:
        config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
        config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    config = types.GenerateContentConfig(**config_kwargs)
    contents = _gemini_contents(messages, types)

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
            break
        except errors.APIError as error:
            code = getattr(error, "code", None)
            status_code = getattr(error, "status_code", None)
            error_body = _safe_error(getattr(error, "message", "API error"), api_key)
            http_status = status_code or code
            status_str = str(getattr(error, "status", "")).upper()
            temporary = (
                code in (429, 503)
                or status_code in (429, 503)
                or "UNAVAILABLE" in status_str
                or "RESOURCE_EXHAUSTED" in status_str
            )
            if not temporary or attempt == MAX_RATE_LIMIT_RETRIES:
                raise ProviderError(
                    f"Gemini request failed (HTTP {http_status}): {error_body}"
                ) from None
            delay = _retry_delay(
                getattr(getattr(error, "response", None), "headers", None),
                error_body,
            )
            time.sleep(delay)

    # Parse response
    content = None
    if response.candidates:
        content = response.candidates[0].content
    text_parts, calls = [], []
    if content is not None:
        for part in content.parts or []:
            if part.text:
                text_parts.append(part.text)
            if part.function_call is not None:
                calls.append({
                    "name": part.function_call.name,
                    "arguments": dict(part.function_call.args or {}),
                })
    usage_meta = getattr(response, "usage_metadata", None)
    return {
        "text": "\n".join(text_parts),
        "tool_calls": calls,
        "usage": {
            "prompt_tokens": int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            "completion_tokens": int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            "total_tokens": int(getattr(usage_meta, "total_token_count", 0) or 0),
        },
    }


def _gemini_contents(messages: List[Dict[str, Any]], types: Any) -> list:
    """Convert shared messages into Gemini Content objects."""
    contents = []
    idx = 0
    while idx < len(messages):
        msg = messages[idx]
        role = msg["role"]
        if role == "system":
            idx += 1
            continue
        if role == "tool":
            parts = []
            while idx < len(messages) and messages[idx]["role"] == "tool":
                tm = messages[idx]
                parts.append(types.Part.from_function_response(
                    name=tm["name"],
                    response=json.loads(tm["content"]),
                ))
                idx += 1
            contents.append(types.Content(role="user", parts=parts))
            continue
        if role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append(types.Part(text=msg["content"]))
            for call in msg.get("tool_calls", []):
                parts.append(types.Part(function_call=types.FunctionCall(
                    name=call["name"], args=call["arguments"],
                )))
            contents.append(types.Content(role="model", parts=parts))
        else:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=msg.get("content", ""))],
            ))
        idx += 1
    return contents


# ---------------------------------------------------------------------------
# Groq caller
# ---------------------------------------------------------------------------

def _call_groq(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
    api_key: str,
) -> Dict[str, Any]:
    """Call Groq's OpenAI-compatible chat completions API."""
    import urllib.error
    import urllib.request

    groq_messages = _groq_messages(messages)
    request_payload: Dict[str, Any] = {
        "model": model,
        "messages": groq_messages,
        "temperature": 0,
    }
    if tools:
        request_payload["tools"] = tools
        request_payload["tool_choice"] = "auto"
    if "gpt-oss" in model.lower():
        effort = _clean_env("GROQ_REASONING_EFFORT", "low")
        request_payload["reasoning_effort"] = effort if effort in {"low", "medium", "high"} else "low"

    request_data = json.dumps(request_payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=request_data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AgenticLiner/0.1",
        },
        method="POST",
    )

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            status_code = error.code
            error_body = _safe_error(error.read().decode("utf-8", errors="replace"), api_key)
            error.close()
            if status_code not in (429, 503) or attempt == MAX_RATE_LIMIT_RETRIES:
                raise ProviderError(
                    f"Groq request failed (HTTP {status_code}): {error_body}"
                ) from None
            delay = _retry_delay(error.headers, error_body)
            time.sleep(delay)
        except urllib.error.URLError as error:
            raise ProviderError(f"Could not connect to Groq: {error.reason}") from None

    choices = payload.get("choices")
    if not choices or not isinstance(choices[0].get("message"), dict):
        raise ProviderError("Groq returned an unexpected response.")
    assistant_msg = choices[0]["message"]
    calls = []
    for tc in assistant_msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        arguments = fn.get("arguments", "{}")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            parsed = {}
        calls.append({
            "id": tc.get("id"),
            "name": fn.get("name"),
            "arguments": parsed,
        })
    return {
        "text": assistant_msg.get("content") or "",
        "tool_calls": calls,
        "usage": payload.get("usage", {}),
    }


def _groq_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert shared messages to Groq's OpenAI-compatible format."""
    converted = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            converted.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", "call"),
                "name": msg["name"],
                "content": msg["content"],
            })
        elif role == "assistant":
            am: Dict[str, Any] = {"role": "assistant", "content": msg.get("content") or None}
            if msg.get("tool_calls"):
                am["tool_calls"] = [
                    {
                        "id": call.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                    for i, call in enumerate(msg["tool_calls"])
                ]
            converted.append(am)
        else:
            converted.append({"role": role, "content": msg.get("content", "")})
    return converted


# ---------------------------------------------------------------------------
# Ollama caller
# ---------------------------------------------------------------------------

def _call_ollama(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
) -> Dict[str, Any]:
    """Call Ollama's local chat API with tool definitions."""
    import urllib.error
    import urllib.request

    host = _clean_env("OLLAMA_HOST", "http://localhost:11434")
    host = host.removeprefix("http://").removeprefix("https://").rstrip("/")
    hostname, separator, port_text = host.partition(":")
    port = int(port_text) if separator and port_text.isdigit() else 11434
    hostname = hostname or "localhost"

    ollama_msgs = _ollama_messages(messages)
    body_payload: Dict[str, Any] = {
        "model": model,
        "messages": ollama_msgs,
        "stream": False,
        "options": {"temperature": 0},
    }
    if tools:
        body_payload["tools"] = tools
    request_data = json.dumps(body_payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://{hostname}:{port}/api/chat",
        data=request_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            status_code = error.code
            error_body = error.read().decode("utf-8", errors="replace")
            error.close()
            if status_code not in (429, 503) or attempt == MAX_RATE_LIMIT_RETRIES:
                raise ProviderError(
                    f"Ollama request failed (HTTP {status_code}): {error_body}"
                ) from None
            delay = _retry_delay(error.headers, error_body)
            time.sleep(delay)
        except urllib.error.URLError as error:
            raise ProviderError(
                "Ollama is not running or is unreachable."
            ) from None

    assistant_msg = payload.get("message")
    if not isinstance(assistant_msg, dict):
        raise ProviderError(f"Ollama returned an unexpected response: {payload}")
    calls = []
    for tc in assistant_msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        calls.append({
            "name": fn.get("name"),
            "arguments": fn.get("arguments", {}),
        })
    return {
        "text": assistant_msg.get("content") or "",
        "tool_calls": calls,
        "usage": {
            "prompt_tokens": payload.get("prompt_eval_count", 0),
            "completion_tokens": payload.get("eval_count", 0),
            "total_tokens": (
                payload.get("prompt_eval_count", 0)
                + payload.get("eval_count", 0)
            ),
        },
    }


def _ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert shared messages into Ollama's chat format."""
    converted = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            converted.append({
                "role": "tool",
                "tool_name": msg["name"],
                "content": msg["content"],
            })
        elif role == "assistant":
            am: Dict[str, Any] = {"role": "assistant", "content": msg.get("content", "")}
            if msg.get("tool_calls"):
                am["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in msg["tool_calls"]
                ]
            converted.append(am)
        else:
            converted.append({"role": role, "content": msg.get("content", "")})
    return converted


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

def call_llm(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Dispatch one LLM turn.  Returns a dict with keys:
      text, tool_calls, usage  (and provider, model for metadata).
    Raises ProviderError on any non-retryable failure.
    """
    tools = tools or []
    if config is None:
        config = get_provider_config()
    provider = config["provider"]
    model = config["model"]
    api_key = config.get("api_key", "")

    if provider == "gemini":
        result = _call_gemini(messages, tools, model, api_key)
    elif provider == "groq":
        result = _call_groq(messages, tools, model, api_key)
    elif provider == "ollama":
        result = _call_ollama(messages, tools, model)
    else:
        raise ProviderError(f'Unknown provider: {provider}')

    result["provider"] = provider
    result["model"] = model
    return result

