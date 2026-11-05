"""Provider-agnostic model layer with a privacy gate (§8, §9).

Models only ever *suggest*: a category, a document type, a field value. They
never compute money and never confirm anything. Every call passes the
privacy gate first and is logged as AI activity.

Privacy levels:
  L2 local_only    – only providers running on this machine.
  L1 swiss_hosted  – local, plus providers hosted in Switzerland.
  L0 cloud_ai      – any configured provider, still per-document consent.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from ..classify.rules import Suggestion

LEVEL_ALLOWS = {
    "local_only": {"local"},
    "swiss_hosted": {"local", "swiss"},
    "cloud_ai": {"local", "swiss", "external"},
}


class PrivacyViolation(PermissionError):
    pass


class Provider(Protocol):
    name: str
    locality: str  # local, swiss, external

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class OpenAICompatible:
    """Ollama, llama.cpp, vLLM, Infomaniak, OpenAI and others speak this API."""

    name: str
    base_url: str
    model: str
    locality: str
    api_key: Optional[str] = None
    timeout: float = 60.0

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(self.base_url.rstrip("/") + "/chat/completions", body,
                                     {"Content-Type": "application/json",
                                      **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["choices"][0]["message"]["content"]


@dataclass
class Anthropic:
    name: str
    model: str
    api_key: str
    locality: str = "external"
    timeout: float = 60.0

    def complete(self, system: str, user: str) -> str:
        body = json.dumps({"model": self.model, "max_tokens": 512, "system": system,
                           "messages": [{"role": "user", "content": user}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", body, {
            "Content-Type": "application/json", "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return "".join(b.get("text", "") for b in json.load(resp)["content"])


@dataclass
class Scripted:
    """Deterministic provider for tests and demos."""

    name: str = "scripted"
    locality: str = "local"
    answers: dict = field(default_factory=dict)

    def complete(self, system: str, user: str) -> str:
        for key, value in self.answers.items():
            if key in user:
                return value
        return "{}"


@dataclass
class Orchestrator:
    """Routes tasks to providers in order, enforcing the privacy level per document,
    redacting identifiers before anything leaves the machine, falling back on
    errors and preferring providers with a better track record."""

    level: str = "local_only"
    routes: dict[str, list] = field(default_factory=dict)  # task -> [Provider, ...] (fallback order)
    log: Callable[[str, str, str, str, dict], None] = lambda task, provider, locality, summary, details: None
    document_privacy: Callable[[Optional[str]], Optional[str]] = lambda document_id: None
    stats: dict[str, list[int]] = field(default_factory=dict)  # provider -> [answered, failed]

    def score(self, provider) -> float:
        ok, bad = self.stats.get(provider.name, [0, 0])
        return (ok + 1) / (ok + bad + 2)  # Laplace-smoothed success rate

    def _ordered(self, task: str) -> list:
        providers = self.routes.get(task, [])
        return sorted(providers, key=lambda p: (-round(self.score(p), 1), providers.index(p)))

    def run(self, task: str, system: str, user: str, document_id: Optional[str] = None,
            validate: Optional[Callable[[str], bool]] = None) -> Optional[str]:
        from ..privacy import document_may_leave, redact

        doc_privacy = self.document_privacy(document_id) if document_id else self.level
        for provider in self._ordered(task):
            if provider.locality not in LEVEL_ALLOWS[self.level] or \
                    not document_may_leave(self.level, doc_privacy, provider.locality):
                self.log(task, provider.name, provider.locality, "skipped by privacy level",
                         {"level": self.level, "document_privacy": doc_privacy})
                continue
            payload, removed = (user, []) if provider.locality == "local" else redact(user)
            try:
                answer = provider.complete(system, payload)
            except Exception as exc:  # fall back to the next provider
                self.stats.setdefault(provider.name, [0, 0])[1] += 1
                self.log(task, provider.name, provider.locality, "failed", {"error": str(exc)[:300]})
                continue
            if validate is not None and not validate(answer):
                self.stats.setdefault(provider.name, [0, 0])[1] += 1
                self.log(task, provider.name, provider.locality, "answer rejected by validation", {"chars": len(answer)})
                continue
            self.stats.setdefault(provider.name, [0, 0])[0] += 1
            self.log(task, provider.name, provider.locality, "answered",
                     {"chars_sent": len(payload), "redacted": removed, "left_machine": provider.locality != "local"})
            return answer
        return None

    def classify(self, counterparty: str, description: str, categories: list[tuple[str, ...]],
                 document_id: Optional[str] = None) -> Optional[Suggestion]:
        options = [" / ".join(p) for p in categories]
        system = ("You categorise a financial record. Choose exactly one category from the list, "
                  "or 'none' if unsure. Reply as JSON {\"category\": str, \"confidence\": 0..1, \"reason\": str}. "
                  "Never invent a category.")
        user = f"Counterparty: {counterparty}\nDescription: {description}\nCategories:\n" + "\n".join(options)
        answer = self.run("classify", system, user, document_id)
        if not answer:
            return None
        try:
            data = json.loads(answer[answer.find("{"): answer.rfind("}") + 1])
            choice = data.get("category", "none")
            if choice not in options:  # the model cannot create categories
                return None
            conf = min(float(data.get("confidence", 0.5)), 0.75)  # AI alone never reaches review-free confidence
            return Suggestion(tuple(choice.split(" / ")), conf, "ai", str(data.get("reason", ""))[:200])
        except (ValueError, TypeError):
            return None


def provider_from_config(cfg: dict):
    """{"type": "openai_compatible"|"anthropic", "name":..., "locality": local|swiss|external, ...}"""
    kind = cfg.get("type", "openai_compatible")
    if kind == "anthropic":
        return Anthropic(cfg["name"], cfg["model"], cfg["api_key"], cfg.get("locality", "external"))
    return OpenAICompatible(cfg["name"], cfg["base_url"], cfg["model"], cfg["locality"], cfg.get("api_key"))


def orchestrator_from_config(config: dict, **kwargs) -> Orchestrator:
    providers = {c["name"]: provider_from_config(c) for c in config.get("providers", [])}
    routes = {task: [providers[n] for n in names if n in providers] for task, names in config.get("routes", {}).items()}
    return Orchestrator(level=config.get("level", "local_only"), routes=routes, **kwargs)
