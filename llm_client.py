"""
Vera LLM Client — Multi-provider with fallback chain.
Primary: OpenAI GPT-4o | Fallback: Gemini 2.0 Flash, DeepSeek, Groq
"""

from __future__ import annotations
import json
import os
import asyncio
from typing import Optional
import httpx


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION — Set your API keys here or via env vars
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://kp661-mopj2trp-southeastasia.cognitiveservices.azure.com/")
AZURE_OPENAI_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "vera-gpt-5.4-mini")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# Model choices
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

TIMEOUT = 12  # seconds — must fit within 10s tick budget with margin


class LLMResponse:
    """Wrapper for LLM responses."""
    def __init__(self, text: str, provider: str, model: str):
        self.text = text
        self.provider = provider
        self.model = model

    def parse_json(self) -> dict:
        """Extract JSON from response text (handles markdown code blocks)."""
        text = self.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"No valid JSON found in response: {text[:200]}")


class LLMClient:
    """Multi-provider LLM client with automatic fallback."""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=TIMEOUT)
        self._providers = self._build_provider_chain()

    def _build_provider_chain(self) -> list[dict]:
        """Build ordered list of available providers."""
        chain = []
        if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT:
            chain.append({
                "name": "azure_openai",
                "model": AZURE_OPENAI_DEPLOYMENT_NAME,
                "call": self._call_azure_openai
            })
        elif OPENAI_API_KEY:
            chain.append({
                "name": "openai",
                "model": OPENAI_MODEL,
                "call": self._call_openai
            })
        if GEMINI_API_KEY:
            chain.append({
                "name": "gemini",
                "model": GEMINI_MODEL,
                "call": self._call_gemini
            })
        if GROQ_API_KEY:
            chain.append({
                "name": "groq",
                "model": GROQ_MODEL,
                "call": self._call_groq
            })
        if DEEPSEEK_API_KEY:
            chain.append({
                "name": "deepseek",
                "model": "deepseek-chat",
                "call": self._call_deepseek
            })
        return chain

    @property
    def primary_provider(self) -> str:
        if self._providers:
            return f"{self._providers[0]['name']} ({self._providers[0]['model']})"
        return "none configured"

    @property
    def is_configured(self) -> bool:
        return bool(self._providers)

    async def complete(self, system: str, user: str, temperature: float = 0.1,
                       json_mode: bool = True) -> LLMResponse:
        """
        Call LLM with automatic fallback chain.
        Tries each provider in order until one succeeds.
        """
        errors = []
        for provider in self._providers:
            try:
                text = await provider["call"](system, user, temperature, json_mode)
                return LLMResponse(text, provider["name"], provider["model"])
            except Exception as e:
                errors.append(f"{provider['name']}: {e}")
                continue

        raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")

    async def _call_azure_openai(self, system: str, user: str, temperature: float,
                                 json_mode: bool) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        body = {
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": 800,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        endpoint = AZURE_OPENAI_ENDPOINT.rstrip("/")
        url = f"{endpoint}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"

        resp = await self._http.post(
            url,
            headers={"api-key": AZURE_OPENAI_API_KEY,
                     "Content-Type": "application/json"},
            json=body
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _call_openai(self, system: str, user: str, temperature: float,
                           json_mode: bool) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        body = {
            "model": OPENAI_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 800,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        resp = await self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json=body
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _call_gemini(self, system: str, user: str, temperature: float,
                           json_mode: bool) -> str:
        full_prompt = f"{system}\n\n{user}" if system else user
        body = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 800
            }
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"

        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}")
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def _call_groq(self, system: str, user: str, temperature: float,
                         json_mode: bool) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        body = {
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 800,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        resp = await self._http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json=body
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def _call_deepseek(self, system: str, user: str, temperature: float,
                             json_mode: bool) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        body = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 800,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        resp = await self._http.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                     "Content-Type": "application/json"},
            json=body
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    async def close(self):
        await self._http.aclose()
