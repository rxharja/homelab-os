"""
title: Seerr
description: Search Seerr, suggest titles we don't have, and request movies and shows.
version: 0.1.1
"""

# Install: Open WebUI > Workspace > Tools > + > paste this file, then set the API key valve.
# Requests made with the API key are attributed to its owner (the Seerr admin) and auto-approved.

import asyncio
import re
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, Field
from yarl import URL

MEDIA_STATUS = {
    1: "not requested", 2: "requested, pending", 3: "requested, processing",
    4: "partially available", 5: "available", 6: "deleted", 7: "blacklisted",
}
REQUEST_STATUS = {1: "pending approval", 2: "approved", 3: "declined", 4: "failed", 5: "completed"}

# TMDB genre ids; TV merges some movie genres (e.g. action + adventure).
GENRES = {
    "movie": {
        "action": 28, "adventure": 12, "animation": 16, "animated": 16, "comedy": 35, "crime": 80,
        "documentary": 99, "documentaries": 99, "drama": 18, "family": 10751, "fantasy": 14, "history": 36,
        "horror": 27, "music": 10402, "mystery": 9648, "romance": 10749,
        "science fiction": 878, "sci-fi": 878, "thriller": 53, "war": 10752, "western": 37,
    },
    "tv": {
        "action": 10759, "adventure": 10759, "animation": 16, "animated": 16, "comedy": 35, "crime": 80,
        "documentary": 99, "documentaries": 99, "drama": 18, "family": 10751, "kids": 10762, "mystery": 9648,
        "reality": 10764, "science fiction": 10765, "sci-fi": 10765, "fantasy": 10765,
        "war": 10768, "politics": 10768, "western": 37,
    },
}


class SeerrError(Exception):
    pass


def _title(result: dict) -> str:
    name = result.get("title") or result.get("name") or "?"
    date = result.get("releaseDate") or result.get("firstAirDate") or ""
    return f"{name} ({date[:4]})" if date else name


def _summary(result: dict, limit: int = 200) -> str:
    # Split only before a capital so abbreviations like "U.C. 0079" stay intact.
    text = re.split(r"(?<=[.!?])\s+(?=[A-Z])", (result.get("overview") or "").strip())[0]
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _status(result: dict) -> str:
    info = result.get("mediaInfo") or {}
    return MEDIA_STATUS.get(info.get("status"), "not requested")


class Tools:
    class Valves(BaseModel):
        seerr_url: str = Field(
            default="http://seerr:5055",
            description="Seerr base URL as seen from the Open WebUI container.",
        )
        api_key: str = Field(default="", description="Seerr > Settings > General > API Key.")

    def __init__(self):
        self.valves = self.Valves()

    async def _api(self, method: str, path: str, query: str = "", body: dict | None = None):
        if not self.valves.api_key:
            raise SeerrError("the Seerr API key valve is empty")
        # Seerr rejects '+' for spaces in search queries, so the URL is pre-encoded.
        url = URL(f"{self.valves.seerr_url.rstrip('/')}/api/v1{path}{query}", encoded=True)
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                method, url, json=body, headers={"X-Api-Key": self.valves.api_key}
            ) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    raise SeerrError(f"HTTP {resp.status}: {(data or {}).get('message', 'no message')}")
                return data

    async def _search(self, query: str, media_type: str | None, year: int | None) -> list[dict]:
        data = await self._api("GET", "/search", f"?query={quote(query, safe='')}&page=1")
        results = [r for r in data.get("results", []) if r.get("mediaType") in ("movie", "tv")]
        if media_type in ("movie", "tv"):
            results = [r for r in results if r["mediaType"] == media_type]
        if year:
            dated = [r for r in results if (r.get("releaseDate") or r.get("firstAirDate") or "")[:4] == str(year)]
            results = dated or results
        return results

    async def search_media(self, query: str, media_type: str | None = None, year: int | None = None) -> str:
        """
        Search Seerr for movies and shows and report whether each is available, requested or not requested.
        Use for "do we have X", "is X requested" or "find X".
        :param query: Title to search for.
        :param media_type: "movie" or "tv", if the user said which.
        :param year: Release year, only to disambiguate.
        :return: Up to 6 matches with type, year and status.
        """
        try:
            results = await self._search(query, media_type, year)
            if not results:
                return f"No movies or shows found for '{query}'."
            lines = [
                f"- {_title(r)} [{'show' if r['mediaType'] == 'tv' else 'movie'}]: {_status(r)}"
                for r in results[:6]
            ]
            return "\n".join(lines)
        except (SeerrError, aiohttp.ClientError) as err:
            return f"Seerr error: {err}"

    async def suggest_media(
        self,
        media_type: str = "movie",
        genre: str | None = None,
        topic: str | None = None,
        like_title: str | None = None,
        exclude_genres: list[str] | None = None,
        from_year: int | None = None,
        to_year: int | None = None,
        min_rating: float = 7.0,
    ) -> str:
        """
        Suggest movies, shows or documentaries we don't have yet, by genre, topic, or similar to a title.
        Use for "suggest a documentary", "documentaries about the ocean", "something like Arrival", "a good 90s thriller".
        Present only the titles this returns, described only by their summaries; never add titles, plot details or facts from memory. Nature documentaries are often shows, so try media_type "tv" too.
        After suggesting, let the user pick; request with request_media only when they ask.
        :param media_type: "movie" or "tv".
        :param genre: Genre such as documentary, comedy, thriller, sci-fi, horror, animation.
        :param topic: Subject, franchise or series in one or two words, such as ocean, heist, world war 2, gundam, star trek.
        :param like_title: One specific title the user wants more like ("something like Arrival"); never a franchise name. Overrides genre, topic and years.
        :param exclude_genres: Genres to leave out, e.g. ["animation", "family"] for "nothing animated" or "not for kids".
        :param from_year: Earliest release year.
        :param to_year: Latest release year.
        :param min_rating: Minimum TMDB rating out of 10.
        :return: Up to 8 suggestions with year, rating and a one-line summary.
        """
        try:
            kind = "tv" if media_type == "tv" else "movie"
            # Seerr's discover API can't exclude genres, so filter client-side and fetch a second page to make up for it.
            pages = (1, 2) if exclude_genres else (1,)

            async def fetch(path: str, params: list[str]) -> list[dict]:
                responses = await asyncio.gather(
                    *(self._api("GET", path, "?" + "&".join(params + [f"page={n}"])) for n in pages)
                )
                return [r for resp in responses for r in resp.get("results", [])]

            if like_title:
                seeds = await self._search(like_title, kind, None)
                if not seeds:
                    return f"Couldn't find '{like_title}' to base suggestions on."
                seed = seeds[0]
                kind = seed["mediaType"]
                results = await fetch(f"/{kind}/{seed['id']}/recommendations", [])
                header = f"Like {_title(seed)}:"
            else:
                date = "primaryReleaseDate" if kind == "movie" else "firstAirDate"
                # Models pass subjects like "racing" as genres; treat unknown genres as topics.
                if genre and genre.casefold() not in GENRES[kind]:
                    topic, genre = topic or genre, None
                # Topic-filtered results are niche, so they need a lower vote floor.
                params = ["sortBy=popularity.desc", f"voteAverageGte={min_rating}",
                          f"voteCountGte={30 if topic else 150}"]
                if topic:
                    found = await self._api("GET", "/search/keyword", f"?query={quote(topic, safe='')}&page=1")
                    keywords = found.get("results", [])
                    wanted = topic.casefold()
                    # An exact keyword is precise; partial matches ("street racing") pull in loose fits.
                    matching = (
                        [k for k in keywords if k["name"].casefold() == wanted]
                        or [k for k in keywords if wanted in k["name"].casefold()]
                        or keywords[:3]
                    )
                    if not matching:
                        return f"No TMDB keyword matches '{topic}'. Try a simpler word."
                    # '|' is OR in TMDB's with_keywords.
                    params.append("keywords=" + "%7C".join(str(k["id"]) for k in matching[:5]))
                if genre:
                    params.append(f"genre={GENRES[kind][genre.casefold()]}")
                if from_year:
                    params.append(f"{date}Gte={from_year}-01-01")
                if to_year:
                    params.append(f"{date}Lte={to_year}-12-31")
                results = await fetch(f"/discover/{'movies' if kind == 'movie' else 'tv'}", params)
                about = f" about {topic}" if topic else ""
                header = f"Popular {genre or ''} {'shows' if kind == 'tv' else 'movies'}{about}:".replace("  ", " ")

            excluded = {GENRES[kind][g.casefold()] for g in exclude_genres or [] if g.casefold() in GENRES[kind]}
            if excluded:
                header = header[:-1] + f", excluding {', '.join(exclude_genres)}:"
            fresh = [
                r for r in results
                if _status(r) == "not requested"
                and (r.get("voteAverage") or 0) >= (min_rating if not like_title else 0)
                and not excluded & set(r.get("genreIds") or [])
            ]
            if not fresh:
                return "Nothing new matched; everything found is already available or requested."
            lines = [header]
            for r in fresh[:8]:
                lines.append(f"- {_title(r)}, {r.get('voteAverage', 0):.1f}/10 ({r.get('voteCount', 0)} votes): {_summary(r)}")
            lines.append("(Summaries are as written; repeat or shorten them, never add details.)")
            return "\n".join(lines)
        except (SeerrError, aiohttp.ClientError) as err:
            return f"Seerr error: {err}"

    async def request_media(
        self,
        title: str,
        media_type: str | None = None,
        seasons: list[int] | None = None,
        year: int | None = None,
        __event_call__=None,
    ) -> str:
        """
        Request a movie or show in Seerr so it gets downloaded. Only call this when the user asks to request or add something.
        :param title: Title as the user said it.
        :param media_type: "movie" or "tv", if the user said which.
        :param seasons: Season numbers to request for a show; omit for all seasons.
        :param year: Release year, only to disambiguate.
        :return: What was requested, or why nothing was.
        """
        try:
            results = await self._search(title, media_type, year)
            if not results:
                return f"No movies or shows found for '{title}'."
            exact = [r for r in results if (r.get("title") or r.get("name") or "").casefold() == title.casefold()]
            pick = (exact or results)[0]
            label = _title(pick)
            status = _status(pick)
            if status in ("available", "requested, pending", "requested, processing") and not seasons:
                return f"{label} is already {status}; nothing requested."

            is_tv = pick["mediaType"] == "tv"
            what = f"{label} ({'show, seasons ' + ', '.join(map(str, seasons)) if seasons else 'show, all seasons'})" if is_tv else f"{label} (movie)"
            others = [_title(r) for r in results[:4] if r is not pick]
            if __event_call__:
                message = f"Other matches: {', '.join(others)}" if others else "Only match."
                ok = await __event_call__(
                    {"type": "confirmation", "data": {"title": f"Request {what}?", "message": message}}
                )
                if not ok:
                    return "Cancelled by the user; nothing was requested."

            body = {"mediaType": pick["mediaType"], "mediaId": pick["id"]}
            if is_tv:
                body["seasons"] = seasons or "all"
            await self._api("POST", "/request", body=body)
            return f"Requested {what}. Riven will pick it up from Seerr."
        except (SeerrError, aiohttp.ClientError) as err:
            return f"Seerr error: {err}"

    async def list_requests(self, status: str = "all", count: int = 10) -> str:
        """
        List recent Seerr requests, newest first, with who asked and their state.
        Use for "what's pending", "what did we request lately" or "did anyone request X".
        :param status: One of all, pending, approved, processing, available, failed, completed.
        :param count: How many to list, at most 20.
        :return: Requests with title, requester, request status and availability.
        """
        try:
            allowed = {"all", "pending", "approved", "processing", "available", "failed", "completed"}
            status = status if status in allowed else "all"
            data = await self._api(
                "GET", "/request", f"?take={min(max(count, 1), 20)}&skip=0&filter={status}&sort=added"
            )
            requests = data.get("results", [])
            if not requests:
                return f"No {status} requests."

            async def name(req: dict) -> str:
                media = req.get("media") or {}
                kind = "tv" if req.get("type") == "tv" or media.get("mediaType") == "tv" else "movie"
                try:
                    return _title(await self._api("GET", f"/{kind}/{media.get('tmdbId')}"))
                except (SeerrError, aiohttp.ClientError):
                    return f"TMDB {media.get('tmdbId')}"

            titles = await asyncio.gather(*(name(r) for r in requests))
            lines = []
            for req, title in zip(requests, titles):
                who = (req.get("requestedBy") or {}).get("displayName") or (req.get("requestedBy") or {}).get("email", "?")
                state = REQUEST_STATUS.get(req.get("status"), "?")
                avail = MEDIA_STATUS.get((req.get("media") or {}).get("status"), "?")
                lines.append(f"- {title}: {state}, {avail} (by {who}, {(req.get('createdAt') or '')[:10]})")
            return "\n".join(lines)
        except (SeerrError, aiohttp.ClientError) as err:
            return f"Seerr error: {err}"
