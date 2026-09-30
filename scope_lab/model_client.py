"""Minimal non-streaming OpenAI-compatible transport; credentials stay in host env."""

import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


class ModelError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ModelError("Redirect refused; configure the final API endpoint explicitly")


def check_url(url):
    if not isinstance(url, str):
        raise ModelError("Base URL is required")
    parsed = urllib.parse.urlsplit(url)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() for c in url)):
        raise ModelError("Base URL must not contain credentials, query, fragment, or whitespace")
    local = parsed.hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ModelError("Use HTTPS or a loopback HTTP endpoint through an SSH tunnel")
    return url.rstrip("/")


def profile_config(name):
    profiles = {
        "qwen": {"base_url": os.getenv("QWEN_BASE_URL", "http://127.0.0.1:8000/v1"),
                 "model": os.getenv("QWEN_MODEL", "Qwen/Qwen3-8B"), "key_env": "VLLM_API_KEY",
                 "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
        "exaone": {"base_url": os.getenv("EXAONE_BASE_URL", "http://127.0.0.1:8000/v1"),
                   "model": os.getenv("EXAONE_MODEL", ""), "key_env": "VLLM_API_KEY", "extra_body": {}},
        "api": {"base_url": os.getenv("COMMERCIAL_BASE_URL", ""),
                "model": os.getenv("COMMERCIAL_MODEL", ""), "key_env": "COMMERCIAL_API_KEY", "extra_body": {}},
    }
    if name not in profiles:
        raise ModelError("Unknown profile")
    config = profiles[name]
    config["base_url"] = check_url(config["base_url"])
    if not config["model"].strip():
        raise ModelError("Set {}_MODEL to the exact served model identifier".format("EXAONE" if name == "exaone" else "COMMERCIAL"))
    if not os.getenv(config["key_env"]):
        raise ModelError("Missing environment variable: " + config["key_env"])
    return config


def chat(config, messages, timeout=60, max_tokens=128, opener=None):
    base = check_url(config["base_url"])
    if not isinstance(config.get("model"), str) or not config["model"].strip():
        raise ModelError("Missing model")
    key = os.getenv(config["key_env"])
    if not key:
        raise ModelError("Missing environment variable: " + config["key_env"])
    if timeout <= 0 or type(max_tokens) is not int or max_tokens <= 0:
        raise ModelError("timeout and max_tokens must be positive")
    body = {"model": config["model"], "messages": messages, "max_tokens": max_tokens, "stream": False}
    extra = config.get("extra_body", {})
    if set(extra) - {"chat_template_kwargs", "temperature", "top_p", "seed"}:
        raise ModelError("Unsupported extra_body key")
    body.update(extra)
    request = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    # Disable environment HTTP proxies so keys are not sent through an accidental proxy.
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    start = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ModelError("API response too large")
        result = json.loads(raw)
        choice = result["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ModelError("No textual completion (reasoning-only/tool-call responses are not a passing smoke test)")
        if choice.get("finish_reason") != "stop":
            raise ModelError("Completion did not finish normally; adjust token budget or provider configuration")
        usage = result.get("usage", {})
        if not isinstance(usage, dict):
            raise ModelError("Malformed usage")
        safe_usage = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int}
        # Never put arbitrary response metadata into logs; redact a reflected exact key.
        return {"content": content.replace(key, "[REDACTED]"), "model_requested": config["model"],
                "model_returned": str(result.get("model", "unknown")).replace(key, "[REDACTED]"),
                "finish_reason": "stop", "usage": safe_usage,
                "elapsed_seconds": round(time.monotonic() - start, 4), "is_mock": False}
    except urllib.error.HTTPError as exc:
        raise ModelError("API HTTP {} (response body omitted; no automatic retry)".format(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ModelError("API connection failed or timed out (no automatic retry)") from None
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        if isinstance(exc, ModelError):
            raise
        raise ModelError("Malformed API completion") from None
