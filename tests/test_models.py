import io
import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from scope_lab.model_client import ModelError, NoRedirect, check_url, profile_config, chat


class FakeOpener:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.requests = result, error, []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.result).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"VLLM_API_KEY": "fake-test-key-only"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = profile_config("qwen")
        self.result = {"model": "fixture", "choices": [{"message": {"content": "READY"}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9}}

    def test_request_shape_and_usage(self):
        opener = FakeOpener(self.result)
        result = chat(self.config, [{"role": "user", "content": "READY?"}], opener=opener)
        request = opener.requests[0]
        body = json.loads(request.data)
        self.assertTrue(request.full_url.endswith("/v1/chat/completions"))
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-test-key-only")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(result["usage"]["total_tokens"], 9)
        self.assertNotIn("fake-test-key-only", json.dumps(result))

    def test_missing_key_fails_before_request(self):
        os.environ.pop("VLLM_API_KEY")
        opener = FakeOpener(self.result)
        with self.assertRaises(ModelError):
            chat(self.config, [], opener=opener)
        self.assertFalse(opener.requests)

    def test_exaone_requires_explicit_model(self):
        with self.assertRaises(ModelError):
            profile_config("exaone")
        os.environ["EXAONE_MODEL"] = "LGAI-EXAONE/EXAONE-4.0-1.2B"
        self.assertEqual(profile_config("exaone")["model"], os.environ["EXAONE_MODEL"])

    def test_commercial_requires_configuration(self):
        with self.assertRaises(ModelError):
            profile_config("api")
        os.environ.update(COMMERCIAL_BASE_URL="https://example.invalid/v1", COMMERCIAL_MODEL="test-model", COMMERCIAL_API_KEY="fake")
        self.assertEqual(profile_config("api")["extra_body"], {})

    def test_url_validation(self):
        for url in ("http://remote.example/v1", "https://key@example.com/v1", "https://example.com/v1?key=abc", "file:///tmp/api", ""):
            with self.assertRaises(ModelError):
                check_url(url)
        for url in ("http://127.0.0.1:8000/v1", "http://[::1]:8000/v1", "https://example.com/v1"):
            self.assertEqual(check_url(url), url)

    def test_http_error_no_body_or_key_disclosure(self):
        error = urllib.error.HTTPError("https://example.com", 401, "denied", {}, io.BytesIO(b"fake-test-key-only"))
        with self.assertRaisesRegex(ModelError, "HTTP 401") as context:
            chat(self.config, [], opener=FakeOpener(error=error))
        self.assertNotIn("fake-test-key-only", str(context.exception))

    def test_no_automatic_retry(self):
        opener = FakeOpener(error=urllib.error.URLError("timeout"))
        with self.assertRaises(ModelError):
            chat(self.config, [], opener=opener)
        self.assertEqual(len(opener.requests), 1)

    def test_malformed_completion_rejected(self):
        for result in ({}, {"choices": []}, {"choices": [{"message": {"content": None}}]},
                       {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}):
            with self.assertRaises(ModelError):
                chat(self.config, [], opener=FakeOpener(result))

    def test_redirect_is_not_followed(self):
        with self.assertRaises(ModelError):
            NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.invalid")

    def test_reflected_key_redacted(self):
        self.result["choices"][0]["message"]["content"] = "oops fake-test-key-only"
        result = chat(self.config, [], opener=FakeOpener(self.result))
        self.assertNotIn("fake-test-key-only", json.dumps(result))

    def test_extra_body_cannot_override_destination_payload(self):
        self.config["extra_body"] = {"messages": []}
        with self.assertRaises(ModelError):
            chat(self.config, [], opener=FakeOpener(self.result))


if __name__ == "__main__":
    unittest.main()

