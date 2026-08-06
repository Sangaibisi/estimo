"""Estimo connectors (S9): Confluence, Bitbucket-first git hosting, Jira, curation."""

from estimo_connectors.base import RatePlan, SourceDocument, resolve_secret
from estimo_connectors.canonical import CANONICAL_AUTHORITY, approve, generate_candidate
from estimo_connectors.confluence import ConfluenceConnector, storage_to_text
from estimo_connectors.db import CONNECTION_KINDS, CanonicalPage, Connection, SyncRun
from estimo_connectors.discovery import DiscoveryUnsupported, remote_repos
from estimo_connectors.gitrepo import GitSyncError, RepoState, clone_or_fetch
from estimo_connectors.hosting import (
    HostedRepo,
    clone_username,
    list_repos,
    push_event_branches,
    verify_webhook,
)
from estimo_connectors.jira import JiraConnector, JiraIssue
from estimo_connectors.sync import effective_secret, run_sync

__all__ = [
    "CANONICAL_AUTHORITY",
    "CONNECTION_KINDS",
    "CanonicalPage",
    "ConfluenceConnector",
    "Connection",
    "DiscoveryUnsupported",
    "GitSyncError",
    "HostedRepo",
    "JiraConnector",
    "JiraIssue",
    "RatePlan",
    "RepoState",
    "SourceDocument",
    "SyncRun",
    "approve",
    "clone_or_fetch",
    "clone_username",
    "effective_secret",
    "generate_candidate",
    "list_repos",
    "push_event_branches",
    "remote_repos",
    "resolve_secret",
    "run_sync",
    "storage_to_text",
    "verify_webhook",
]
