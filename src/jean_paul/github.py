"""GitHub access as the Jean Paul GitHub App. Every call here blocks."""

from datetime import datetime

from github import Auth, GithubIntegration
from github.GithubException import GithubException
from github.GithubObject import NotSet
from github.Issue import Issue
from github.Repository import Repository

from jean_paul import report

# Marks an issue as a report; the bot only mirrors issues carrying it.
REPORT_LABEL = "discord"


def connect(app_id: int, private_key: str, repo_name: str) -> tuple[Repository, str]:
    """Authenticate as the App's installation on `repo_name`; also return the App's login."""
    owner, name = repo_name.split("/")
    integration = GithubIntegration(auth=Auth.AppAuth(app_id, private_key))
    login = f"{integration.get_app().slug}[bot]"
    installation = integration.get_repo_installation(owner, name)
    return installation.get_github_for_installation().get_repo(repo_name), login


def check_repo(repo: Repository) -> list[str]:
    """Return a description of each thing missing on the GitHub side."""
    try:
        repo.get_label(REPORT_LABEL)
    except GithubException as error:
        if error.status != 404:
            raise
        return [f"{repo.full_name} has no label '{REPORT_LABEL}'. Create it under Issues → Labels."]
    return []


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
