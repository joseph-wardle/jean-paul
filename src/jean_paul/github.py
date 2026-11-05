"""GitHub access as the Jean Paul GitHub App. Every call here blocks."""

from github import Auth, GithubIntegration
from github.GithubException import GithubException
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
    for issue in repo.get_issues(state="all"):
        if issue.user.login != bot_login:
            continue
        thread_id = report.thread_id_in(issue.body)
        if thread_id is not None:
            index[thread_id] = issue.number
    return index


def create_report_issue(repo: Repository, title: str, body: str) -> Issue:
    return repo.create_issue(title=title, body=body, labels=[REPORT_LABEL])
