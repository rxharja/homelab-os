"""
title: Paperless
description: Search Paperless documents and read their OCR text to answer questions about them.
version: 0.1.0
"""

# Install: Open WebUI > Workspace > Tools > + > paste this file. Re-paste after edits.
# Each user sets their own Paperless token (tool's user valves), so answers only draw on
# documents that user can see in Paperless.

import re

import aiohttp
from pydantic import BaseModel, Field


class PaperlessError(Exception):
    pass


def _plain(html: str) -> str:
    # Search highlights wrap matches in <span class="match">.
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


class Tools:
    class Valves(BaseModel):
        paperless_url: str = Field(
            default="http://paperless:8000",
            description="Paperless base URL as seen from the Open WebUI container.",
        )
        public_url: str = Field(
            default="",
            description="Browser URL for links in answers, e.g. https://docs.example.com. Empty = no links.",
        )
        max_chars: int = Field(
            default=6000,
            description="OCR text returned per document; keeps a reply inside the model's 16k context.",
        )

    class UserValves(BaseModel):
        api_token: str = Field(default="", description="Paperless > My Profile > API Auth Token.")

    def __init__(self):
        self.valves = self.Valves()

    async def _api(self, path: str, token: str, params: dict | None = None) -> dict:
        if not token:
            raise PaperlessError("set your Paperless API token in this tool's user settings")
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{self.valves.paperless_url.rstrip('/')}/api{path}",
                params=params,
                headers={"Authorization": f"Token {token}"},
            ) as resp:
                if resp.status in (401, 403):
                    raise PaperlessError("Paperless rejected the API token")
                if resp.status == 404:
                    raise PaperlessError("not found (or not visible to you)")
                if resp.status >= 400:
                    raise PaperlessError(f"HTTP {resp.status}: {(await resp.text())[:200]}")
                return await resp.json(content_type=None)

    async def _names(self, kind: str, ids: set[int], token: str) -> dict[int, str]:
        if not ids:
            return {}
        data = await self._api(
            f"/{kind}/", token, {"id__in": ",".join(map(str, ids)), "page_size": len(ids)}
        )
        return {r["id"]: r["name"] for r in data.get("results", [])}

    def _link(self, doc_id: int) -> str:
        base = self.valves.public_url.rstrip("/")
        return f" {base}/documents/{doc_id}/details" if base else ""

    @staticmethod
    def _token(user: dict | None) -> str:
        valves = (user or {}).get("valves")
        if isinstance(valves, dict):
            return valves.get("api_token", "")
        return getattr(valves, "api_token", "") or ""

    async def search_documents(self, query: str, limit: int = 5, __user__: dict | None = None) -> str:
        """
        Full-text search the user's Paperless documents (bills, letters, contracts, receipts, manuals).
        Use first for any question about their documents, then read_document on the best match.
        :param query: Keywords, e.g. "car insurance renewal 2026" or "water heater warranty".
        :param limit: Number of results, default 5.
        :return: Matching documents with id, date, correspondent, type and the matched passages.
        """
        try:
            token = self._token(__user__)
            data = await self._api(
                "/documents/", token, {"query": query, "page_size": max(1, min(limit, 10))}
            )
            docs = data.get("results", [])
            if not docs:
                return f"No documents match '{query}'. Try fewer or different keywords."
            corr = await self._names("correspondents", {d["correspondent"] for d in docs if d.get("correspondent")}, token)
            types = await self._names("document_types", {d["document_type"] for d in docs if d.get("document_type")}, token)
            lines = [f"{data.get('count', len(docs))} match(es); top {len(docs)}:"]
            for d in docs:
                meta = ", ".join(
                    x for x in (
                        (d.get("created") or "")[:10],
                        corr.get(d.get("correspondent")),
                        types.get(d.get("document_type")),
                    ) if x
                )
                hit = _plain((d.get("__search_hit__") or {}).get("highlights", ""))
                lines.append(f"- [id {d['id']}] {d['title']} ({meta}){self._link(d['id'])}")
                if hit:
                    lines.append(f"  …{hit[:300]}…")
            return "\n".join(lines)
        except (PaperlessError, aiohttp.ClientError) as err:
            return f"Paperless error: {err}"

    async def read_document(self, document_id: int, __user__: dict | None = None) -> str:
        """
        Read one Paperless document's OCR text, to answer a question about its contents
        (amounts, dates, policy numbers, terms). Get the id from search_documents.
        :param document_id: The document id from search_documents.
        :return: Title, date and the document's text (truncated if long). Cite the title in the answer.
        """
        try:
            token = self._token(__user__)
            d = await self._api(f"/documents/{int(document_id)}/", token)
            text = (d.get("content") or "").strip()
            if not text:
                return f"'{d['title']}' has no OCR text yet."
            cut = len(text) > self.valves.max_chars
            body = text[: self.valves.max_chars]
            note = f"\n[truncated: showing {self.valves.max_chars} of {len(text)} characters]" if cut else ""
            return f"{d['title']} ({(d.get('created') or '')[:10]}){self._link(d['id'])}\n\n{body}{note}"
        except (PaperlessError, aiohttp.ClientError, ValueError) as err:
            return f"Paperless error: {err}"
