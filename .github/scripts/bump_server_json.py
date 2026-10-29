"""Move both version fields in server.json when a release bumps package.json.

The MCP Registry rejects a republish of an existing version, and it checks the
published npm package at server.json's package version. Both the server version
and the npm package version have to move together. A blind replace of the old
version string is safe here: those two fields are the only places it appears.
"""


def bump_server_json(text: str, old: str, new: str) -> str:
    needle = f'"version": "{old}"'
    count = text.count(needle)
    if count != 2:
        raise ValueError(f"server.json: expected 2 version fields at {old!r}, found {count}")
    return text.replace(needle, f'"version": "{new}"')
