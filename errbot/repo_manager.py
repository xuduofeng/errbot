import logging
import os
import shutil
import subprocess
from collections import namedtuple
from datetime import timedelta, datetime
from os import path
import tarfile
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from urllib.parse import urlparse

import json

import re

from errbot.plugin_manager import check_dependencies
from errbot.storage import StoreMixin
from .utils import ON_WINDOWS

log = logging.getLogger(__name__)


def human_name_for_git_url(url):
    # try to humanize the last part of the git url as much as we can
    s = url.split(":")[-1].split("/")[-2:]
    if s[-1].endswith(".git"):
        s[-1] = s[-1][:-4]
    return str("/".join(s))


INSTALLED_REPOS = "installed_repos"

REPO_INDEXES_CHECK_INTERVAL = timedelta(hours=1)

REPO_INDEX = "repo_index"
LAST_UPDATE = "last_update"

RepoEntry = namedtuple("RepoEntry", "entry_name, name, python, repo, path, avatar_url, documentation")
FIND_WORDS_RE = re.compile(r"(\w[\w']*\w|\w)")


class RepoException(Exception):
    pass


def makeEntry(repo_name, plugin_name, json_value):
    return RepoEntry(
        entry_name=repo_name,
        name=plugin_name,
        python=json_value["python"],
        repo=json_value["repo"],
        path=json_value["path"],
        avatar_url=json_value["avatar_url"],
        documentation=json_value["documentation"],
    )


def tokenizeJsonEntry(json_dict):
    """
    Returns all the words in a repo entry.
    """
    search = " ".join((str(word) for word in json_dict.values()))
    return set(FIND_WORDS_RE.findall(search.lower()))


def which(program):
    if ON_WINDOWS:
        program += ".exe"

    def is_exe(file_path):
        return os.path.isfile(file_path) and os.access(file_path, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


class BotRepoManager(StoreMixin):
    """
    Manages the repo list, git clones/updates or the repos.
    """

    def __init__(self, storage_plugin, plugin_dir, plugin_indexes):
        """
        Make a repo manager.
        :param storage_plugin: where the manager store its state.
        :param plugin_dir: where on disk it will git clone the repos.
        :param plugin_indexes: a list of URL / path to get the json repo index.
        """
        super().__init__()
        self.plugin_indexes = plugin_indexes
        self.storage_plugin = storage_plugin
        self.plugin_dir = plugin_dir
        self.open_storage(storage_plugin, "repomgr")

    def shutdown(self):
        self.close_storage()

    def check_for_index_update(self):
        if REPO_INDEX not in self:
            log.info("No repo index, creating it.")
            self.index_update()
            return

        if datetime.fromtimestamp(self[REPO_INDEX][LAST_UPDATE]) < datetime.now() - REPO_INDEXES_CHECK_INTERVAL:
            log.info("Index is too old, update it.")
            self.index_update()

    def index_update(self):
        index = {LAST_UPDATE: datetime.now().timestamp()}
        for source in reversed(self.plugin_indexes):
            try:
                if urlparse(source).scheme in ("http", "https"):
                    with urlopen(url=source, timeout=10) as request:  # nosec
                        log.debug("Update from remote source %s...", source)
                        encoding = request.headers.get_content_charset()
                        content = request.read().decode(encoding if encoding else "utf-8")
                else:
                    with open(source, encoding="utf-8", mode="r") as src_file:
                        log.debug("Update from local source %s...", source)
                        content = src_file.read()
                index.update(json.loads(content))
            except (HTTPError, URLError, IOError):
                log.exception("Could not update from source %s, keep the index as it is.", source)
                break
        else:
            # nothing failed so ok, we can store the index.
            self[REPO_INDEX] = index
            log.debug("Stored %d repo entries.", len(index) - 1)

    def get_repo_from_index(self, repo_name):
        """
        Retrieve the list of plugins for the repo_name from the index.

        :param repo_name: the name of hte repo
        :return: a list of RepoEntry
        """
        plugins = self[REPO_INDEX].get(repo_name, None)
        if plugins is None:
            return None
        result = []
        for name, plugin in plugins.items():
            result.append(makeEntry(repo_name, name, plugin))
        return result

    def search_repos(self, query):
        """
        A simple search feature, keywords are AND and case insensitive on all the fields.

        :param query: a string query
        :return: an iterator of RepoEntry
        """
        # first see if we are up to date.
        self.check_for_index_update()
        if REPO_INDEX not in self:
            log.error("No index.")
            return
        query_work_set = set(FIND_WORDS_RE.findall(query.lower()))
        for repo_name, plugins in self[REPO_INDEX].items():
            if repo_name == LAST_UPDATE:
                continue
            for plugin_name, plugin in plugins.items():
                if query_work_set.intersection(tokenizeJsonEntry(plugin)):
                    yield makeEntry(repo_name, plugin_name, plugin)

    def get_installed_plugin_repos(self):
        return self.get(INSTALLED_REPOS, {})

    def add_plugin_repo(self, name, url):
        repos = self.get_installed_plugin_repos()
        repos[name] = url
        self[INSTALLED_REPOS] = repos

    def set_plugin_repos(self, repos):
        """ Used externally.
        """
        self[INSTALLED_REPOS] = repos

    def get_all_repos_paths(self):
        return [os.path.join(self.plugin_dir, d) for d in self.get(INSTALLED_REPOS, {}).keys()]

    def install_repo(self, repo):
        """
        Install the repository from repo

        :param repo:
            The url, git url or path on disk of a repository. It can point to either a git repo or
             a .tar.gz of a plugin
        :returns:
            The path on disk where the repo has been installed on.
        :raises: :class:`~RepoException` if an error occured.
        """
        self.check_for_index_update()

        # try to find if we have something with that name in our index
        if repo in self[REPO_INDEX]:
            human_name = repo
            repo_url = next(iter(self[REPO_INDEX][repo].values()))["repo"]
        elif not repo.endswith("tar.gz"):
            # This is a repo url, make up a plugin definition for it
            human_name = human_name_for_git_url(repo)
            repo_url = repo
        else:
            repo_url = repo

        git_path = which("git")
        if not git_path:
            raise RepoException(
                "git command not found: You need to have git installed on "
                "your system to be able to install git based plugins."
            )

        # TODO: Update download path of plugin.
        if repo_url.endswith("tar.gz"):
            fo = urlopen(repo_url)  # nosec
            tar = tarfile.open(fileobj=fo, mode="r:gz")
            tar.extractall(path=self.plugin_dir)
            s = repo_url.split(":")[-1].split("/")[-1]
            human_name = s[:-len(".tar.gz")]
        else:
            human_name = human_name or human_name_for_git_url(repo_url)
            p = subprocess.Popen(
                [git_path, "clone", repo_url, human_name],
                cwd=self.plugin_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            feedback = p.stdout.read().decode("utf-8")
            error_feedback = p.stderr.read().decode("utf-8")
            if p.wait():
                raise RepoException("Could not load this plugin: \n\n%s\n\n---\n\n%s" % (feedback, error_feedback))

        self.add_plugin_repo(human_name, repo_url)
        return os.path.join(self.plugin_dir, human_name)

    def update_repos(self, repos):
        """
        This git pulls the specified repos on disk.
        Yields tuples like (name, success, reason)
        """
        git_path = which("git")
        if not git_path:
            yield (
                "everything",
                False,
                "git command not found: You need to have git installed on "
                "your system to be able to install git based plugins.",
            )

        # protects for update outside of what we know is installed
        names = set(self.get_installed_plugin_repos().keys()).intersection(set(repos))

        for d in (path.join(self.plugin_dir, name) for name in names):
            p = subprocess.Popen([git_path, "pull"], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            feedback = p.stdout.read().decode("utf-8") + "\n" + "-" * 50 + "\n"
            err = p.stderr.read().strip().decode("utf-8")
            if err:
                feedback += err + "\n" + "-" * 50 + "\n"
            dep_err, missing_pkgs = check_dependencies(d)
            if dep_err:
                feedback += dep_err + "\n"
            yield d, not p.wait(), feedback

    def update_all_repos(self):
        return self.update_repos(self.get_installed_plugin_repos().keys())

    def uninstall_repo(self, name):
        repo_path = path.join(self.plugin_dir, name)
        # ignore errors because the DB can be desync'ed from the file tree.
        shutil.rmtree(repo_path, ignore_errors=True)
        repos = self.get_installed_plugin_repos()
        del (repos[name])
        self.set_plugin_repos(repos)
