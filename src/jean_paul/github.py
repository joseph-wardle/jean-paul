"""GitHub access as the Jean Paul GitHub App."""

from github import Auth, GithubIntegration
from github.GithubException import GithubException
from github.Repository import Repository

# Marks an issue as a report; the bot only mirrors issues carrying it.
REPORT_LABEL = "discord"


def connect(app_id: int, private_key: str, repo_name: str) -> Repository:
    """Authenticate as the App's installation on `repo_name`."""
    owner, name = repo_name.split("/")
    integration = GithubIntegration(auth=Auth.AppAuth(app_id, private_key))
    installation = integration.get_repo_installation(owner, name)
    return installation.get_github_for_installation().get_repo(repo_name)


def check_repo(repo: Repository) -> list[str]:
    """Return a description of each thing missing on the GitHub side."""
    try:
        repo.get_label(REPORT_LABEL)
    except GithubException as error:
        if error.status != 404:
            raise
        return [f"{repo.full_name} has no label '{REPORT_LABEL}'. Create it under Issues → Labels."]
    return []
