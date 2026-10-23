"""
title: Riven
description: Ask Riven which stream it picked, list the alternatives, and blacklist the active one.
version: 0.1.0
"""

# Install: Open WebUI > Workspace > Tools > + > paste this file. Re-paste after edits.
# Talks to Riven's GraphQL API over homelab.network; it has no auth.

from difflib import SequenceMatcher

import aiohttp
from pydantic import BaseModel, Field

NO_PICKING = "Riven picks streams automatically; it can't be told to use a specific one."

# Riven doesn't persist its ranking score, so "best" is approximated from the parsed name.
RESOLUTION_RANK = {"2160p": 5, "1440p": 4, "1080p": 3, "720p": 2, "576p": 1, "480p": 1}
QUALITY_RANK = {
    "bluray remux": 6, "remux": 6, "bluray": 5, "web-dl": 4, "web": 4,
    "webrip": 3, "hdrip": 2, "hdtv": 2, "dvdrip": 1, "dvd": 1,
}

ENTRY = "mediaEntries { originalFilename fileSize(units: gigabyte) { size units } }"
EPISODE = f"id number activeStream {{ infoHash parsedData }} {ENTRY}"

SEARCH = """
query ($search: String!) {
  mediaItems(search: $search, itemsPerPage: 10) {
    items { ... on MediaItem { id title year type state nextScrapeAttemptAt } }
  }
}"""

LIBRARY = """
query ($after: String) {
  mediaItems(after: $after, itemsPerPage: 200) {
    endCursor hasNextPage
    items { ... on MediaItem { id title year type state nextScrapeAttemptAt } }
  }
}"""

MOVIE = f"""
query ($id: ID!) {{
  mediaItemById(id: $id) {{
    ... on Movie {{ id activeStream {{ infoHash parsedData }} {ENTRY} }}
  }}
}}"""

SHOW = f"""
query ($id: ID!) {{
  mediaItemById(id: $id) {{
    ... on Show {{ seasons {{ id number episodes {{ {EPISODE} }} }} }}
  }}
}}"""

ITEM_STREAMS = """
query ($id: ID!) {
  mediaItemById(id: $id) {
    ... on MediaItem {
      type
      activeStream { infoHash }
      streams { infoHash parsedData }
      blacklistedStreams { stream { infoHash } }
    }
    ... on Episode {
      season { streams { infoHash parsedData } blacklistedStreams { stream { infoHash } } }
      show { streams { infoHash parsedData } blacklistedStreams { stream { infoHash } } }
    }
    ... on Season {
      show { streams { infoHash parsedData } blacklistedStreams { stream { infoHash } } }
    }
  }
}"""

BLACKLIST = """
mutation ($id: ID!) { blacklistActiveStream(mediaItemId: $id) }
"""


class RivenError(Exception):
    pass


def _norm(title: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in title.casefold()).split())


def _describe(parsed: dict) -> str:
    bits = [
        parsed.get("resolution"),
        parsed.get("quality"),
        parsed.get("codec"),
        "/".join(parsed.get("hdr") or []),
        "/".join(parsed.get("audio") or []),
        parsed.get("size"),
        parsed.get("group") and f"[{parsed['group']}]",
    ]
    summary = " ".join(b for b in bits if b and b != "unknown")
    return f"{summary or 'unparsed'} | {parsed.get('rawTitle', '?')}"


def _score(parsed: dict) -> tuple:
    return (
        RESOLUTION_RANK.get(parsed.get("resolution", ""), 0),
        bool(parsed.get("remux")),
        QUALITY_RANK.get((parsed.get("quality") or "").lower(), 0),
        bool(parsed.get("hdr")),
        not parsed.get("upscaled"),
    )


def _entry(item: dict) -> str:
    entries = item.get("mediaEntries") or []
    if not entries:
        return "no file downloaded yet"
    e = entries[0]
    size = e.get("fileSize") or {}
    return f"file: {e['originalFilename']} ({size.get('size', '?')} {size.get('units', '')})"


class Tools:
    class Valves(BaseModel):
        riven_url: str = Field(
            default="http://riven:3000/",
            description="Riven GraphQL endpoint as seen from the Open WebUI container.",
        )
        max_streams: int = Field(default=8, description="Alternatives listed per request.")

    def __init__(self):
        self.valves = self.Valves()

    async def _gql(self, query: str, **variables) -> dict:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self.valves.riven_url, json={"query": query, "variables": variables}
            ) as resp:
                body = await resp.json(content_type=None)
        if body.get("errors"):
            raise RivenError("; ".join(e.get("message", "?") for e in body["errors"]))
        return body["data"]

    async def _find(self, title: str, year: int | None) -> tuple[dict, str]:
        data = await self._gql(SEARCH, search=title)
        items = [i for i in data["mediaItems"]["items"] if i]
        if not items:
            return await self._closest(title)
        if year:
            items = [i for i in items if int(i.get("year") or 0) == year] or items
        exact = [i for i in items if i["title"].casefold() == title.casefold()]
        pick = (exact or items)[0]
        others = [f"{i['title']} ({int(i['year'] or 0)})" for i in items if i is not pick]
        note = f"Other matches: {', '.join(others[:4])}." if len(exact) != 1 and others else ""
        return pick, note

    async def _closest(self, title: str) -> tuple[dict, str]:
        # Riven's search is a substring match, so misheard voice input ("Wrecket Ralph") finds nothing.
        library, after = [], None
        for _ in range(10):
            page = (await self._gql(LIBRARY, after=after))["mediaItems"]
            library += [i for i in page["items"] if i]
            if not page["hasNextPage"]:
                break
            after = page["endCursor"]
        wanted = _norm(title)
        scored = sorted(
            ((SequenceMatcher(None, wanted, _norm(i["title"])).ratio(), i) for i in library),
            key=lambda si: si[0],
            reverse=True,
        )
        if not scored or scored[0][0] < 0.6:
            raise RivenError(f"Riven has nothing matching '{title}'.")
        pick = scored[0][1]
        return pick, (
            f"No exact match for '{title}'; assumed {pick['title']}. "
            "Tell the user which title was used so they can correct it."
        )

    async def _episodes(self, show_id: str, season: int | None, episode: int | None) -> list[dict]:
        data = await self._gql(SHOW, id=show_id)
        out = []
        for s in data["mediaItemById"]["seasons"]:
            if season is not None and s["number"] != season:
                continue
            for e in s["episodes"]:
                if episode is not None and e["number"] != episode:
                    continue
                out.append({**e, "season": s["number"], "season_id": s["id"]})
        return out

    async def get_active_stream(
        self, title: str, season: int | None = None, episode: int | None = None, year: int | None = None
    ) -> str:
        """
        Tell which stream (torrent) Riven picked for a movie or show, and the file it downloaded.
        For shows, narrow down with season and episode; without them, streams are grouped across episodes.
        :param title: Movie or show title as the user said it.
        :param season: Season number, for shows.
        :param episode: Episode number, for shows (needs season).
        :param year: Release year, only to disambiguate titles.
        :return: The active stream(s) with resolution, quality, codec, release group and raw torrent name.
        """
        try:
            item, note = await self._find(title, year)
            head = f"{item['title']} ({int(item['year'] or 0)}), state: {item['state']}."
            if item["type"] == "movie":
                movie = (await self._gql(MOVIE, id=item["id"]))["mediaItemById"]
                stream = movie.get("activeStream")
                if not stream:
                    retry = item.get("nextScrapeAttemptAt")
                    when = f" Next attempt: {retry}." if retry else ""
                    return f"{head} No stream picked yet.{when} {NO_PICKING} {note}"
                return f"{head}\nActive stream: {_describe(stream['parsedData'])}\n{_entry(movie)}\n{note}"

            episodes = await self._episodes(item["id"], season, episode)
            if not episodes:
                return f"{head} No matching episodes in Riven. {note}"
            groups: dict[str, list[str]] = {}
            parsed: dict[str, dict] = {}
            missing = []
            for e in episodes:
                code = f"S{e['season']:02d}E{e['number']:02d}"
                stream = e.get("activeStream")
                if not stream:
                    missing.append(code)
                    continue
                groups.setdefault(stream["infoHash"], []).append(code)
                parsed[stream["infoHash"]] = stream["parsedData"]
            lines = [head]
            for h, codes in groups.items():
                span = codes[0] if len(codes) == 1 else f"{codes[0]}-{codes[-1]} ({len(codes)} eps)"
                lines.append(f"{span}: {_describe(parsed[h])}")
            if len(episodes) == 1 and groups:
                lines.append(_entry(episodes[0]))
            if missing:
                lines.append(f"No stream yet: {', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}")
            if note:
                lines.append(note)
            return "\n".join(lines)
        except (RivenError, aiohttp.ClientError) as err:
            return f"Riven error: {err}"

    async def list_streams(
        self, title: str, season: int | None = None, episode: int | None = None, year: int | None = None
    ) -> str:
        """
        List the streams Riven scraped for a movie, show, season or episode, best first, marking the active one.
        Use this for "what's the best available stream" or "what else is there".
        :param title: Movie or show title as the user said it.
        :param season: Season number, for shows.
        :param episode: Episode number, for shows (needs season).
        :param year: Release year, only to disambiguate titles.
        :return: Ranked alternatives. Ranking is by resolution, remux, source and HDR, not Riven's exact score.
        """
        try:
            item, note = await self._find(title, year)
            target_id = item["id"]
            if item["type"] == "show" and season is not None:
                episodes = await self._episodes(item["id"], season, episode)
                if not episodes:
                    return f"No S{season:02d}{f'E{episode:02d}' if episode else ''} in Riven for {item['title']}."
                target_id = episodes[0]["id"] if episode is not None else episodes[0]["season_id"]

            data = (await self._gql(ITEM_STREAMS, id=target_id))["mediaItemById"]
            levels = [data] + [data[k] for k in ("season", "show") if data.get(k)]
            streams: dict[str, dict] = {}
            blacklisted = set()
            for level in levels:
                blacklisted |= {b["stream"]["infoHash"] for b in level.get("blacklistedStreams", [])}
                for s in level.get("streams", []):
                    streams.setdefault(s["infoHash"], s["parsedData"])
            active = (data.get("activeStream") or {}).get("infoHash")
            # Mirrors Riven's titleSimilarity check, so off-title scrape results aren't listed.
            wanted = item["title"].casefold()
            usable = {
                h: p for h, p in streams.items()
                if h not in blacklisted and not p.get("trash") and not p.get("threeD")
                and SequenceMatcher(None, wanted, (p.get("title") or "").casefold()).ratio() >= 0.85
            }
            ranked = sorted(usable.items(), key=lambda hp: _score(hp[1]), reverse=True)
            if not ranked:
                return f"No usable streams scraped for {item['title']}. {note}"
            dropped = len(streams) - len(usable) - len(blacklisted & streams.keys())
            lines = [
                f"{item['title']}: {len(ranked)} usable streams, {len(blacklisted)} blacklisted"
                + (f", {dropped} off-title or 3D skipped." if dropped else ".")
            ]
            for n, (h, p) in enumerate(ranked[: self.valves.max_streams], 1):
                lines.append(f"{n}. {'[ACTIVE] ' if h == active else ''}{_describe(p)}")
            if active and active not in dict(ranked[: self.valves.max_streams]):
                lines.append("The active stream is not in this top list.")
            if not active:
                lines.append("No stream is active yet.")
            lines.append(f"{NO_PICKING} Blacklisting the active one makes it pick the next.")
            if note:
                lines.append(note)
            return "\n".join(lines)
        except (RivenError, aiohttp.ClientError) as err:
            return f"Riven error: {err}"

    async def blacklist_active_stream(
        self,
        title: str,
        season: int | None = None,
        episode: int | None = None,
        year: int | None = None,
        __event_call__=None,
    ) -> str:
        """
        Blacklist the stream Riven is using for a movie or episode, so it picks the next best one.
        A season pack is blacklisted for every episode in it. Only call this when the user asks to blacklist.
        :param title: Movie or show title as the user said it.
        :param season: Season number, required for shows.
        :param episode: Episode number; optional if the whole season shares one pack.
        :param year: Release year, only to disambiguate titles.
        :return: What was blacklisted, or why nothing was.
        """
        try:
            item, note = await self._find(title, year)
            if item["type"] == "movie":
                movie = (await self._gql(MOVIE, id=item["id"]))["mediaItemById"]
                stream = movie.get("activeStream")
                target, label = item["id"], item["title"]
            else:
                if season is None:
                    return "Which season (and episode)? Blacklisting works per episode or per season pack."
                episodes = [e for e in await self._episodes(item["id"], season, episode) if e.get("activeStream")]
                hashes = {e["activeStream"]["infoHash"] for e in episodes}
                if len(hashes) > 1:
                    return (
                        f"Season {season} of {item['title']} uses {len(hashes)} different streams. "
                        "Which episode should I blacklist?"
                    )
                stream = episodes[0]["activeStream"] if episodes else None
                target = episodes[0]["id"] if episodes else None
                label = f"{item['title']} S{season:02d}" + (f"E{episode:02d}" if episode else "")
            if not stream:
                return f"{label} has no active stream to blacklist."

            desc = _describe(stream["parsedData"])
            if __event_call__:
                ok = await __event_call__(
                    {
                        "type": "confirmation",
                        "data": {"title": f"Blacklist stream for {label}?", "message": desc},
                    }
                )
                if not ok:
                    return "Cancelled by the user; nothing was blacklisted."

            await self._gql(BLACKLIST, id=target)
            return f"Blacklisted {desc} for {label}. Riven is re-processing it and will pick the next best stream. {note}"
        except (RivenError, aiohttp.ClientError) as err:
            return f"Riven error: {err}"
