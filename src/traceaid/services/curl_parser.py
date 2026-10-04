"""A deliberately small, non-executing cURL command parser.

TraceAid supports the options commonly copied from browser developer tools.
Unsupported options fail closed instead of silently changing request meaning.
No shell is invoked and ``@file`` payloads are rejected.
"""

from __future__ import annotations

import base64
import json
import shlex
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import JsonValue

from traceaid.models import RequestSpec


class CurlParseError(ValueError):
    """Raised when a cURL command is malformed or unsupported."""


_NO_VALUE_OPTIONS = {
    "--compressed",
    "--fail",
    "--fail-with-body",
    "--insecure",
    "--location",
    "--show-error",
    "--silent",
    "-L",
    "-S",
    "-f",
    "-k",
    "-s",
    "-v",
    "--verbose",
}

_IGNORED_VALUE_OPTIONS = {
    "--connect-timeout",
    "--max-time",
    "--output",
    "--retry",
    "--retry-delay",
    "--user-agent",  # handled separately before this set
    "-o",
}


@dataclass
class _ParsedCurl:
    method: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    data: list[str] = field(default_factory=list)
    force_get: bool = False
    json_mode: bool = False


def _option_value(tokens: list[str], index: int, option: str) -> tuple[str, int]:
    token = tokens[index]
    if token.startswith(f"{option}="):
        return token.split("=", 1)[1], index
    if token != option:
        # Compact short option, e.g. -XPOST or -HAccept:application/json.
        if option.startswith("-") and not option.startswith("--") and token.startswith(option):
            return token[len(option) :], index
        raise CurlParseError(f"internal parser error for {option}")
    if index + 1 >= len(tokens):
        raise CurlParseError(f"{option} requires a value")
    return tokens[index + 1], index + 1


def _set_header(headers: dict[str, str], raw_header: str) -> None:
    if ":" not in raw_header:
        raise CurlParseError(f"invalid header {raw_header!r}; expected 'Name: value'")
    name, value = raw_header.split(":", 1)
    name = name.strip()
    if not name:
        raise CurlParseError("header name may not be empty")
    # cURL treats an empty value as removal. For an isolated request model the
    # least surprising representation is simply to omit it.
    if not value.strip():
        headers.pop(name, None)
        return
    headers[name] = value.strip()


def _has_header(headers: dict[str, str], name: str) -> bool:
    needle = name.casefold()
    return any(key.casefold() == needle for key in headers)


def _append_query(url: str, raw_data: str) -> str:
    parsed = urlsplit(url)
    existing = parse_qsl(parsed.query, keep_blank_values=True)
    incoming = parse_qsl(raw_data, keep_blank_values=True)
    query = urlencode([*existing, *incoming], doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _decode_body(raw: str) -> JsonValue:
    try:
        return cast(JsonValue, json.loads(raw))
    except (TypeError, json.JSONDecodeError):
        return raw


def _normalise_command(command: str) -> list[str]:
    if not command or not command.strip():
        raise CurlParseError("cURL command may not be empty")
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        raise CurlParseError(f"could not parse cURL command: {exc}") from exc
    if not tokens:
        raise CurlParseError("cURL command may not be empty")
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable not in {"curl", "curl.exe"}:
        raise CurlParseError("command must start with curl")
    return tokens


def parse_curl(command: str) -> RequestSpec:
    """Parse a cURL command into :class:`RequestSpec` without executing it."""

    tokens = _normalise_command(command)
    parsed = _ParsedCurl()
    index = 1

    while index < len(tokens):
        token = tokens[index]

        if token in _NO_VALUE_OPTIONS:
            index += 1
            continue

        if token in {"-G", "--get"}:
            parsed.force_get = True
            index += 1
            continue

        if token in {"-I", "--head"}:
            parsed.method = "HEAD"
            index += 1
            continue

        if token == "--json" or token.startswith("--json="):
            value, index = _option_value(tokens, index, "--json")
            if value.startswith("@"):
                raise CurlParseError("file-backed request bodies are not accepted")
            parsed.data.append(value)
            parsed.json_mode = True
            index += 1
            continue

        matched = False
        for option in ("--request", "-X"):
            if (
                token == option
                or token.startswith(f"{option}=")
                or (option == "-X" and token.startswith("-X") and len(token) > 2)
            ):
                value, index = _option_value(tokens, index, option)
                parsed.method = value.upper()
                matched = True
                break
        if matched:
            index += 1
            continue

        for option in ("--header", "-H"):
            if (
                token == option
                or token.startswith(f"{option}=")
                or (option == "-H" and token.startswith("-H") and len(token) > 2)
            ):
                value, index = _option_value(tokens, index, option)
                _set_header(parsed.headers, value)
                matched = True
                break
        if matched:
            index += 1
            continue

        data_options = (
            "--data",
            "--data-ascii",
            "--data-binary",
            "--data-raw",
            "--data-urlencode",
            "-d",
        )
        for option in data_options:
            compact = option == "-d" and token.startswith("-d") and len(token) > 2
            if token == option or token.startswith(f"{option}=") or compact:
                value, index = _option_value(tokens, index, option)
                if value.startswith("@"):
                    raise CurlParseError("file-backed request bodies are not accepted")
                parsed.data.append(value)
                matched = True
                break
        if matched:
            index += 1
            continue

        if token == "--url" or token.startswith("--url="):
            value, index = _option_value(tokens, index, "--url")
            if parsed.url is not None:
                raise CurlParseError("only one request URL is supported")
            parsed.url = value
            index += 1
            continue

        if (
            token in {"--user", "-u"}
            or token.startswith("--user=")
            or (token.startswith("-u") and len(token) > 2)
        ):
            option = "--user" if token.startswith("--") else "-u"
            value, index = _option_value(tokens, index, option)
            encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
            parsed.headers["Authorization"] = f"Basic {encoded}"
            index += 1
            continue

        if (
            token in {"--cookie", "-b"}
            or token.startswith("--cookie=")
            or (token.startswith("-b") and len(token) > 2)
        ):
            option = "--cookie" if token.startswith("--") else "-b"
            value, index = _option_value(tokens, index, option)
            if value.startswith("@"):
                raise CurlParseError("file-backed cookies are not accepted")
            parsed.headers["Cookie"] = value
            index += 1
            continue

        if (
            token in {"--user-agent", "-A"}
            or token.startswith("--user-agent=")
            or (token.startswith("-A") and len(token) > 2)
        ):
            option = "--user-agent" if token.startswith("--") else "-A"
            value, index = _option_value(tokens, index, option)
            parsed.headers["User-Agent"] = value
            index += 1
            continue

        if token in _IGNORED_VALUE_OPTIONS or any(
            token.startswith(f"{option}=")
            for option in _IGNORED_VALUE_OPTIONS
            if option.startswith("--")
        ):
            option = token.split("=", 1)[0]
            _, index = _option_value(tokens, index, option)
            index += 1
            continue

        if token.startswith("-"):
            raise CurlParseError(f"unsupported cURL option: {token}")

        if parsed.url is not None:
            raise CurlParseError("only one request URL is supported")
        parsed.url = token
        index += 1

    if not parsed.url:
        raise CurlParseError("cURL command does not contain a URL")

    raw_body = "&".join(parsed.data) if parsed.data else None
    method = parsed.method or ("POST" if raw_body is not None else "GET")

    if parsed.force_get:
        method = "GET"
        if raw_body:
            parsed.url = _append_query(parsed.url, raw_body)
            raw_body = None

    if parsed.json_mode:
        if not _has_header(parsed.headers, "Content-Type"):
            parsed.headers["Content-Type"] = "application/json"
        if not _has_header(parsed.headers, "Accept"):
            parsed.headers["Accept"] = "application/json"

    body = _decode_body(raw_body) if raw_body is not None else None
    return RequestSpec(method=method, url=parsed.url, headers=parsed.headers, body=body)


__all__ = ["CurlParseError", "parse_curl"]
