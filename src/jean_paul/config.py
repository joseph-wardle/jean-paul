"""Deployment settings and secrets, all read from one directory outside the repo."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("JEAN_PAUL_CONFIG_DIR", "~/.config/jean-paul")).expanduser()
SETTINGS_FILE = CONFIG_DIR / "config.toml"
DISCORD_TOKEN_FILE = CONFIG_DIR / "discord_token"
GITHUB_KEY_FILE = CONFIG_DIR / "github_app.pem"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    guild_id: int
    forum_id: int
    maintainer_channel_id: int
    github_app_id: int
    github_repo: str
    discord_token: str
    github_private_key: str


def load_config() -> Config:
    settings = _read_settings()
    try:
        discord_settings = settings["discord"]
        github_settings = settings["github"]
        return Config(
            guild_id=int(discord_settings["guild_id"]),
            forum_id=int(discord_settings["forum_id"]),
            maintainer_channel_id=int(discord_settings["maintainer_channel_id"]),
            github_app_id=int(github_settings["app_id"]),
            github_repo=str(github_settings["repo"]),
            discord_token=_read_secret(DISCORD_TOKEN_FILE),
            github_private_key=_read_secret(GITHUB_KEY_FILE),
        )
    except KeyError as missing:
        raise ConfigError(
            f"{SETTINGS_FILE} has no setting {missing}. "
            "Compare it with config.example.toml in the repo."
        ) from None


def _read_settings() -> dict:
    try:
        with SETTINGS_FILE.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError:
        raise ConfigError(
            f"{SETTINGS_FILE} does not exist. Copy config.example.toml there and fill it in."
        ) from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{SETTINGS_FILE} is not valid TOML: {error}") from None


def _read_secret(path: Path) -> str:
    try:
        secret = path.read_text().strip()
    except FileNotFoundError:
        raise ConfigError(f"Secret file {path} does not exist.") from None
    if not secret:
        raise ConfigError(f"Secret file {path} is empty.")
    return secret
