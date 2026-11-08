"""GitHub access as the Jean Paul GitHub App. Every call here blocks."""

import urllib.request
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote, urlparse

from github import Auth, GithubIntegration
from github.GithubException import GithubException
from github.GithubObject import NotSet
from github.Issue import Issue
from github.IssueComment import IssueComment
from github.Repository import Repository

from jean_paul import report

# Marks an issue as a report; the bot only mirrors issues carrying it.
REPORT_LABEL = "discord"

DOWNLOAD_TIMEOUT_SECONDS = 30


def connect(
    app_id: int, private_key: str, repo_name: str, attachments_name: str
) -> tuple[Repository, Repository, str]:
    """Authenticate as the App's installation on `repo_name`.

    Also return the attachments repo, unchecked, and the App's login.
    """
    owner, name = repo_name.split("/")
    integration = GithubIntegration(auth=Auth.AppAuth(app_id, private_key))
    login = f"{integration.get_app().slug}[bot]"
    installation = integration.get_repo_installation(owner, name)
    client = installation.get_github_for_installation()
    return client.get_repo(repo_name), client.get_repo(attachments_name, lazy=True), login


def check_repo(repo: Repository, attachments: Repository) -> list[str]:
    """Return a description of each thing missing on the GitHub side."""
    problems = []
    try:
        repo.get_label(REPORT_LABEL)
    except GithubException as error:
        if error.status != 404:
            raise
        problems.append(
            f"{repo.full_name} has no label '{REPORT_LABEL}'. Create it under Issues → Labels."
        )
    try:
        # Reading any field fetches the lazily opened repo.
        attachments.default_branch  # noqa: B018
    except GithubException as error:
        if error.status != 404:
            raise
        problems.append(
            f"The App can't see {attachments.full_name}. Create it, or add it to the App's "
            "installation."
        )
    return problems


def thread_index(repo: Repository, bot_login: str) -> dict[int, int]:
    """Map forum thread id to issue number, from every issue the bot wrote.

    All issues, not only labelled ones, so removing the label can't cause a duplicate.
    Markers in other people's issues are ignored: anyone can write in a public repo.
    """
    index = {}
    # PyGithub sends a login string as is, though its annotation wants a NamedUser.
    for issue in repo.get_issues(state="all", creator=bot_login):  # ty: ignore[invalid-argument-type]
        thread_id = report.thread_id_in(issue.body)
        if thread_id is not None:
            index[thread_id] = issue.number
    return index


def newest_forwarded(repo: Repository, number: int, bot_login: str) -> int | None:
    """The newest Discord message the bot forwarded to issue `number`, if any.

    Only the bot's own comments are trusted.
    """
    forwarded = [
        report.message_id_in(comment.body)
        for comment in repo.get_issue(number).get_comments()
        if comment.user.login == bot_login
    ]
    # Discord ids grow with time, so the largest is the newest.
    return max((message_id for message_id in forwarded if message_id is not None), default=None)


def labelled_issues(repo: Repository, since: datetime | None) -> list[Issue]:
    """Every labelled issue, open or closed, updated at or after `since`, oldest first."""
    issues = repo.get_issues(
        state="all",
        labels=[REPORT_LABEL],
        sort="updated",
        direction="asc",
        since=since if since is not None else NotSet,
    )
    return [issue for issue in issues if issue.pull_request is None]


def create_report_issue(repo: Repository, title: str, body: str) -> Issue:
    return repo.create_issue(title=title, body=body, labels=[REPORT_LABEL])


def add_comment(repo: Repository, number: int, body: str) -> None:
    repo.get_issue(number).create_comment(body)


def comments_after(repo: Repository, number: int, after: int, bot_login: str) -> list[IssueComment]:
    """Issue `number`'s comments newer than comment `after`, oldest first, but the bot's own."""
    return [
        comment
        for comment in repo.get_issue(number).get_comments()
        if comment.id > after and comment.user.login != bot_login
    ]


def store_attachment(attachments: Repository, path: str, content: bytes) -> str:
    """Commit `content` at `path`, unless an earlier try did; return a link that serves it."""
    try:
        attachments.create_file(path, f"Add {path}", content)
    except GithubException as error:
        # 422 when the file is already there, but also for other refusals.
        if error.status != 422 or not _exists(attachments, path):
            raise
    return (
        f"https://raw.githubusercontent.com/{attachments.full_name}/"
        f"{attachments.default_branch}/{quote(path)}"
    )


def download(url: str) -> tuple[str, bytes]:
    """A file attached on GitHub, with its name.

    Raises:
        OSError: the download failed.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "jean-paul"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        # GitHub redirects to storage whose path ends in the file's name.
        return PurePosixPath(urlparse(response.url).path).name, response.read()


def _exists(repo: Repository, path: str) -> bool:
    try:
        repo.get_contents(path)
    except GithubException as error:
        if error.status != 404:
            raise
        return False
    return True
