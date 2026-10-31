"""Offline-safe diagnostics for configured language-model providers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import socket
import time
from typing import Any, Literal
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field

from backend.planner import test_tool_calling as mock_agent


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAX_RETRIES = 1
TOOL_NAME = "get_event_checklist"


class PlanProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["dance", "hackathon", "seminar"]
    headcount: int = Field(gt=0)
    budget: int = Field(ge=0)


class ChecklistArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["dance", "hackathon", "seminar"]


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    host: str
    port: int
    api_key: str
    model: str
    request_timeout: float


@dataclass
class StageResult:
    provider: str
    stage: str
    status: str
    seconds: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_class: str = "-"
    message: str = "-"


class ProviderFailure(Exception):
    def __init__(
        self,
        status_code: int | None,
        body: str,
        headers: Any = None,
    ) -> None:
        super().__init__(body or f"HTTP status {status_code}")
        self.status_code = status_code
        self.body = body
        self.headers = headers


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip(" \t\r\n\ufeff\"'").strip()


def redact_text(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\r\n,;}\"]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"(?i)\b(?:AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z_-]{20,})\b", "[REDACTED]", text)
    return text


def load_configuration() -> None:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=REPOSITORY_ROOT / ".env", override=True)
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "GROQ_REASONING_EFFORT",
        "OLLAMA_MODEL",
        "OLLAMA_HOST",
    ):
        value = clean_value(os.getenv(name))
        if value:
            os.environ[name] = value


def provider_config(name: str) -> tuple[ProviderConfig | None, str | None]:
    if name == "gemini":
        key = clean_value(os.getenv("GEMINI_API_KEY"))
        model = clean_value(os.getenv("GEMINI_MODEL"))
        missing = [
            env_name
            for env_name, value in (("GEMINI_API_KEY", key), ("GEMINI_MODEL", model))
            if not value
        ]
        if missing:
            return None, ", ".join(missing)
        return ProviderConfig(name, "generativelanguage.googleapis.com", 443, key, model, 60), None
    if name == "groq":
        key = clean_value(os.getenv("GROQ_API_KEY"))
        model = clean_value(os.getenv("GROQ_MODEL"))
        missing = [
            env_name
            for env_name, value in (("GROQ_API_KEY", key), ("GROQ_MODEL", model))
            if not value
        ]
        if missing:
            return None, ", ".join(missing)
        return ProviderConfig(name, "api.groq.com", 443, key, model, 60), None
    host = clean_value(os.getenv("OLLAMA_HOST")) or "http://localhost:11434"
    host = host.removeprefix("http://").removeprefix("https://").rstrip("/")
    hostname, separator, port_text = host.partition(":")
    port = int(port_text) if separator and port_text.isdigit() else 11434
    model = clean_value(os.getenv("OLLAMA_MODEL")) or mock_agent.DEFAULT_OLLAMA_MODEL
    return ProviderConfig(name, hostname or "localhost", port, "", model, 120), None


def retry_delay(headers: Any, body: str) -> float:
    if headers:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                try:
                    retry_time = parsedate_to_datetime(retry_after)
                    if retry_time.tzinfo is None:
                        retry_time = retry_time.replace(tzinfo=timezone.utc)
                    return max(
                        0.0,
                        (retry_time - datetime.now(timezone.utc)).total_seconds(),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        retry_after_ms = headers.get("retry-after-ms")
        if retry_after_ms:
            try:
                return max(0.0, float(retry_after_ms) / 1000)
            except (TypeError, ValueError):
                pass

    match = re.search(
        r"try again in\s+(\d+(?:\.\d+)?)\s*(milliseconds?|msecs?|ms|minutes?|mins?|m|seconds?|secs?|s)\b",
        body,
        re.IGNORECASE,
    )
    if not match:
        return 1.0
    delay = float(match.group(1))
    unit = match.group(2).lower()
    if unit in {"ms", "msec", "msecs", "millisecond", "milliseconds"}:
        return delay / 1000
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return delay * 60
    return delay


def call_with_retry(callable_: Any, config: ProviderConfig) -> tuple[Any, dict[str, int]]:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response, usage = callable_()
            return response, usage
        except ProviderFailure as error:
            if error.status_code not in (429, 503) or attempt >= MAX_RETRIES:
                raise
            delay = retry_delay(error.headers, error.body)
            print(
                f"  retrying {config.name} after HTTP {error.status_code} "
                f"in {delay:g} seconds (one retry maximum)"
            )
            time.sleep(delay)
    raise RuntimeError("provider retry loop ended unexpectedly")


def usage_from_gemini(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    return {
        "prompt_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
        "completion_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        "total_tokens": int(getattr(usage, "total_token_count", 0) or 0),
    }


def usage_from_openai(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def usage_from_ollama(payload: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = int(payload.get("prompt_eval_count") or 0)
    completion_tokens = int(payload.get("eval_count") or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def gemini_client(config: ProviderConfig):
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=config.api_key,
        http_options=types.HttpOptions(
            timeout=int(config.request_timeout * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def gemini_generate(client: Any, provider_config: ProviderConfig, **kwargs: Any):
    from google.genai import errors

    try:
        response = client.models.generate_content(model=provider_config.model, **kwargs)
    except errors.APIError as error:
        status = getattr(error, "status_code", None) or getattr(error, "code", None)
        headers = getattr(getattr(error, "response", None), "headers", None)
        raise ProviderFailure(status, str(getattr(error, "message", error)), headers) from error
    return response, usage_from_gemini(response)


def groq_post(config: ProviderConfig, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AgenticLiner-Doctor/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8", errors="replace")
        raise ProviderFailure(error.code, body_text, error.headers) from error
    except (TimeoutError, socket.timeout) as error:
        raise TimeoutError("Groq request timed out") from error
    return body, usage_from_openai(body)


def ollama_post(config: ProviderConfig, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    request = urllib.request.Request(
        f"http://{config.host}:{config.port}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        body_text = error.read().decode("utf-8", errors="replace")
        raise ProviderFailure(error.code, body_text, error.headers) from error
    except (TimeoutError, socket.timeout) as error:
        raise TimeoutError("Ollama request timed out") from error
    return body, usage_from_ollama(body)


def call_groq_stage(config: ProviderConfig, messages: list[dict[str, Any]], **kwargs: Any):
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0,
        **kwargs,
    }
    if "gpt-oss" in config.model.lower():
        effort = clean_value(os.getenv("GROQ_REASONING_EFFORT")) or "low"
        payload["reasoning_effort"] = effort if effort in {"low", "medium", "high"} else "low"
    return call_with_retry(lambda: groq_post(config, payload), config)


def call_ollama_stage(config: ProviderConfig, messages: list[dict[str, Any]], **kwargs: Any):
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
        **kwargs,
    }
    return call_with_retry(lambda: ollama_post(config, payload), config)


def run_network_check(config: ProviderConfig) -> None:
    with socket.create_connection(
        (config.host, config.port), timeout=10
    ):
        pass


def extract_gemini_function_call(response: Any):
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if part.function_call is not None:
                return candidate.content, part.function_call
    return None, None


def extract_ollama_function_call(payload: dict[str, Any]):
    message = payload.get("message") or {}
    calls = message.get("tool_calls") or []
    if not calls:
        return message, None
    function = calls[0].get("function") or {}
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    return message, {"name": function.get("name"), "arguments": arguments}


def extract_groq_function_call(message: dict[str, Any]):
    calls = message.get("tool_calls") or []
    if not calls:
        return None
    call = calls[0]
    function = call.get("function") or {}
    arguments = function.get("arguments") or "{}"
    if isinstance(arguments, str):
        arguments = json.loads(arguments)
    return {
        "id": call.get("id") or "doctor-tool-call",
        "name": function.get("name"),
        "arguments": arguments,
    }


def run_provider_stage(
    config: ProviderConfig,
    stage: str,
    operation: Any,
) -> StageResult:
    started_at = time.monotonic()
    try:
        usage = operation()
        return StageResult(
            provider=config.name,
            stage=stage,
            status="PASS",
            seconds=time.monotonic() - started_at,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
    except Exception as error:
        status = "TIMEOUT" if isinstance(error, (TimeoutError, socket.timeout)) else "FAIL"
        message = error.body if isinstance(error, ProviderFailure) else str(error)
        result = StageResult(
            provider=config.name,
            stage=stage,
            status=status,
            seconds=time.monotonic() - started_at,
            error_class=type(error).__name__,
            message=redact_text(message, (config.api_key,)),
        )
        return result


def report_stage(result: StageResult) -> None:
    print(
        f"{result.provider} {result.stage}: {result.status}; "
        f"seconds={result.seconds:.2f}; "
        f"tokens(prompt={result.prompt_tokens}, "
        f"completion={result.completion_tokens}, total={result.total_tokens}); "
        f"error_class={result.error_class}; message={result.message}"
    )


def ping_stage(config: ProviderConfig) -> dict[str, int]:
    if config.name == "gemini":
        from google.genai import types

        client = gemini_client(config)
        _, usage = call_with_retry(
            lambda: gemini_generate(
                client,
                config,
                contents="Say OK",
                config=types.GenerateContentConfig(temperature=0),
            ),
            config,
        )
        return usage
    if config.name == "groq":
        payload, usage = call_groq_stage(
            config,
            [{"role": "user", "content": "Say OK"}],
        )
        _ = payload["choices"][0]["message"].get("content", "")
        return usage
    payload, usage = call_ollama_stage(
        config,
        [{"role": "user", "content": "Say OK"}],
    )
    _ = payload.get("message", {}).get("content", "")
    return usage


def json_stage(config: ProviderConfig) -> dict[str, int]:
    prompt = (
        "Return a JSON object with event_type, headcount, and budget for a "
        "dance event, 150 students, budget 20000."
    )
    if config.name == "gemini":
        from google.genai import types

        client = gemini_client(config)
        response, usage = call_with_retry(
            lambda: gemini_generate(
                client,
                config,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=PlanProbe,
                ),
            ),
            config,
        )
        text = response.text
    elif config.name == "groq":
        payload, usage = call_groq_stage(
            config,
            [{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        text = payload["choices"][0]["message"].get("content", "")
    else:
        payload, usage = call_ollama_stage(
            config,
            [{"role": "user", "content": prompt}],
            format="json",
        )
        text = payload.get("message", {}).get("content", "")
    PlanProbe.model_validate_json(text)
    return usage


def tool_stage(config: ProviderConfig) -> dict[str, int]:
    schema = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "enum": ["dance", "hackathon", "seminar"],
            }
        },
        "required": ["event_type"],
        "additionalProperties": False,
    }
    declaration = {
        "name": TOOL_NAME,
        "description": "Get the checklist for a supported event type.",
        "parameters": schema,
    }
    prompt = "Call get_event_checklist for event_type dance, then summarize the result."

    if config.name == "gemini":
        from google import genai
        from google.genai import types

        client = gemini_client(config)
        function_declaration = types.FunctionDeclaration(
            name=TOOL_NAME,
            description=declaration["description"],
            parameters_json_schema=schema,
        )
        tool = types.Tool(function_declarations=[function_declaration])
        first_response, first_usage = call_with_retry(
            lambda: gemini_generate(
                client,
                config,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[tool],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True
                    ),
                    temperature=0,
                ),
            ),
            config,
        )
        native_content, function_call = extract_gemini_function_call(first_response)
        if function_call is None or function_call.name != TOOL_NAME:
            raise ValueError("Gemini did not return the requested function call")
        arguments = ChecklistArguments.model_validate(function_call.args or {})
        result = mock_agent.get_event_checklist(arguments.event_type)
        response_content = types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name=TOOL_NAME,
                    response={"result": result},
                )
            ],
        )
        second_response, second_usage = call_with_retry(
            lambda: gemini_generate(
                client,
                config,
                contents=[native_content, response_content],
                config=types.GenerateContentConfig(temperature=0),
            ),
            config,
        )
        if not (second_response.text or "").strip():
            raise ValueError("Gemini returned no final answer after tool result")
        return sum_usage(first_usage, second_usage)

    if config.name == "groq":
        groq_tool = {
            "type": "function",
            "function": {**declaration, "strict": True},
        }
        first_payload, first_usage = call_groq_stage(
            config,
            [{"role": "user", "content": prompt}],
            tools=[groq_tool],
            tool_choice="auto",
        )
        assistant_message = first_payload["choices"][0]["message"]
        call = extract_groq_function_call(assistant_message)
        if call is None or call["name"] != TOOL_NAME:
            raise ValueError("Groq did not return the requested function call")
        arguments = ChecklistArguments.model_validate(call["arguments"])
        result = mock_agent.get_event_checklist(arguments.event_type)
        messages = [
            {"role": "user", "content": prompt},
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": TOOL_NAME,
                "content": json.dumps({"result": result}),
            },
        ]
        second_payload, second_usage = call_groq_stage(config, messages)
        final_text = second_payload["choices"][0]["message"].get("content") or ""
        if not final_text.strip():
            raise ValueError("Groq returned no final answer after tool result")
        return sum_usage(first_usage, second_usage)

    ollama_tool = {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": declaration["description"],
            "parameters": schema,
        },
    }
    first_payload, first_usage = call_ollama_stage(
        config,
        [{"role": "user", "content": prompt}],
        tools=[ollama_tool],
    )
    assistant_message, call = extract_ollama_function_call(first_payload)
    if call is None or call["name"] != TOOL_NAME:
        raise ValueError("Ollama did not return the requested function call")
    arguments = ChecklistArguments.model_validate(call["arguments"])
    result = mock_agent.get_event_checklist(arguments.event_type)
    messages = [
        {"role": "user", "content": prompt},
        assistant_message,
        {
            "role": "tool",
            "tool_name": TOOL_NAME,
            "content": json.dumps({"result": result}),
        },
    ]
    second_payload, second_usage = call_ollama_stage(config, messages)
    final_text = second_payload.get("message", {}).get("content") or ""
    if not final_text.strip():
        raise ValueError("Ollama returned no final answer after tool result")
    return sum_usage(first_usage, second_usage)


def sum_usage(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    return {
        key: first.get(key, 0) + second.get(key, 0)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }


def run_provider(config: ProviderConfig) -> list[StageResult]:
    stages = (
        ("network", lambda: (run_network_check(config), {})[1]),
        ("ping", lambda: ping_stage(config)),
        ("json", lambda: json_stage(config)),
        ("tool", lambda: tool_stage(config)),
    )
    results = []
    for stage_name, operation in stages:
        result = run_provider_stage(config, stage_name, operation)
        report_stage(result)
        results.append(result)
    return results


def print_skipped_provider(name: str, missing: str) -> list[StageResult]:
    message = f"skipped; missing {missing}"
    print(f"{name}: {message}")
    return [
        StageResult(name, stage, "SKIP", error_class="ConfigurationError", message=message)
        for stage in ("network", "ping", "json", "tool")
    ]


def print_summary(results: list[StageResult]) -> None:
    print("\nSummary")
    print(f"{'provider':<10} {'stage':<8} {'status':<8} {'seconds':>8} {'tokens':>10}")
    for result in results:
        print(
            f"{result.provider:<10} {result.stage:<8} {result.status:<8} "
            f"{result.seconds:>8.2f} {result.total_tokens:>10}"
        )
    for provider in ("gemini", "groq", "ollama"):
        provider_results = [result for result in results if result.provider == provider]
        if not provider_results:
            continue
        statuses = {result.stage: result.status for result in provider_results}
        if statuses.get("tool") == "PASS":
            verdict = "usable for tool calling"
        elif statuses.get("ping") == "PASS" or statuses.get("json") == "PASS":
            verdict = "usable for text only"
        else:
            verdict = "not usable now"
        print(f"{provider}: {verdict}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check configured LLM providers.")
    parser.add_argument(
        "--provider",
        choices=("gemini", "groq", "ollama", "all"),
        default="all",
    )
    args = parser.parse_args(argv)
    load_configuration()
    providers = ("gemini", "groq", "ollama") if args.provider == "all" else (args.provider,)
    all_results = []
    for name in providers:
        config, missing = provider_config(name)
        if config is None:
            all_results.extend(print_skipped_provider(name, missing or "configuration"))
        else:
            all_results.extend(run_provider(config))
    print_summary(all_results)
    return 0 if all(result.status in ("PASS", "SKIP") for result in all_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
