#!/usr/bin/env python3

""" Management utility to check and validate R packages for Arch Linux """

## import necessary modules
import argparse
import git
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


## helper classes
class RequestError(Exception):
    """ handle non-ok network requests """

    def __init__(self, status, reason):
        self.status = status
        self.reason = reason

class RepoSearchError(Exception):
    """ handle unsuccessful upstream lookups """

    def __init__(self, reason):
        self.reason = reason

class MessageColor:
    """ color codes """

    red = "\033[1;31m"
    green = "\033[1;32m"
    yellow = "\033[1;33m"
    blue = "\033[1;34m"
    purple = "\033[1;35m"
    nc = "\033[0m"
    error = red
    ok = green
    warn = yellow
    info = purple
    data = blue
    old = red
    new = green

class MessageText:
    """ messages """

    skipping = ". {}Skipping{}".format(MessageColor.yellow, MessageColor.nc)
    exiting = ". {}Exiting{}".format(MessageColor.red, MessageColor.nc)

class ProgressCounter:
    """ progress counter """

    def __init__(self, manager, initval=0):
        """ assign our own storage and lock instance """

        self.val = manager.Value('i', initval)
        self.lock = manager.RLock()

    def increment(self):
        """ just increment counter by 1 """

        with self.lock:
            self.val.value += 1

    @property
    def value(self):
        """ return integer value """

        with self.lock:
            return self.val.value


## some defaults
PKGS_DEFAULT = [
        "base", "boot", "class", "cluster", "codetools", "compiler",
        "datasets", "foreign", "graphics", "grDevices", "grid", "KernSmooth",
        "lattice", "MASS", "Matrix", "methods", "mgcv", "nlme",
        "nnet", "parallel", "rpart", "spatial", "splines", "stats",
        "stats4", "survival", "tcltk", "tools", "utils"
        ]

GIT_REPO = "https://github.com/dvdesolve/ArchRPkgs.git"

SUPPORTED_REPOS = [
    {
        "name": "CRAN",
        "url": "cran.r-project.org",
        "table_regex": r"<table summary=\"Package(.*?) summary\">(.*?)</table>",
        "table_match_index": 2,
        "version_regex": r"<tr>\n<td>Version:</td>\n<td>(.*?)</td>",
        "version_match_index": 1
    },

    {
        "name": "Bioconductor",
        "url": "bioconductor.org",
        "table_regex": r"<table class=\"details\">(.*?)</table>",
        "table_match_index": 1,
        "version_regex": r"<tr(.*?)>\n(\s*)<td>Version</td>\n(\s*)<td>(.*?)</td>",
        "version_match_index": 4
    }
]

SCRIPT_VERSION = "0.1.0"


## helper functions
def check_updates(package):
    """ check updates for single package """

    # some repositories are not supported yet
    domain = "{uri.netloc}".format(uri=urlparse(package["URL"])).lower()

    if not any(r["url"] == domain for r in SUPPORTED_REPOS):
        return "{}[WARN]{} Package {}{}{}: repository {}{}{} is unsupported (yet){}".format(
            MessageColor.warn, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.data, domain, MessageColor.nc,
            MessageText.skipping)

    repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

    # get version info from repository
    try:
        with urlopen(package["URL"]) as response:
            html = response.read().decode("utf-8")

            table_regex = repo["table_regex"]
            table_pattern = re.compile(table_regex, flags=re.DOTALL)
            table_match = table_pattern.search(html)

            if table_match:
                # recheck
                html = table_match.group(repo["table_match_index"])

                version_regex = repo["version_regex"]
                version_pattern = re.compile(version_regex, flags=re.DOTALL)
                version_match = version_pattern.search(html)

                if version_match:
                    package["UpstreamVersion"] = version_match.group(repo["version_match_index"])

                    # make UpstreamVersion to conform with Arch standards
                    # https://wiki.archlinux.org/index.php/R_package_guidelines
                    package["UpstreamVersion"] = re.sub(r"[:-]", ".", package["UpstreamVersion"])
                else:
                    raise RepoSearchError("can't find version info")
            else:
                raise RepoSearchError("can't find package info")

    except HTTPError as err:
        return "{}[WARN]{} Package {}{}{}: error while doing repository request: server returned {}{}{}{}".format(
            MessageColor.warn, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.data, str(err.code), MessageColor.nc,
            MessageText.skipping)

    except URLError as err:
        return "{}[WARN]{} Package {}{}{}: error while trying to connect to repository: {}{}{}{}".format(
            MessageColor.warn, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.data, str(err.reason), MessageColor.nc,
            MessageText.skipping)

    except RequestError as err:
        return "{}[WARN]{} Package {}{}{}: error while fetching request data from repository: {}{} {}{}{}".format(
            MessageColor.warn, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.data, str(err.status), str(err.reason), MessageColor.nc,
            MessageText.skipping)

    except RepoSearchError as err:
        return "{}[WARN]{} Package {}{}{}: error while processing repository response: {}{}{}{}".format(
            MessageColor.warn, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.data, str(err.reason), MessageColor.nc,
            MessageText.skipping)

    # compare versions in field-by-field way
    our = [int(x) for x in package["Version"].split(".")]
    upstream = [int(x) for x in package["UpstreamVersion"].split(".")]

    if our < upstream:
        return "{}[INFO]{} Package {}{}{} is outdated: {}{}{} (repository) vs {}{}{} ({})".format(
            MessageColor.info, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc,
            MessageColor.old, package["Version"], MessageColor.nc,
            MessageColor.new, package["UpstreamVersion"], MessageColor.nc, repo["name"])


def checker_worker(packages, total, finished, output):
    """ main worker function for parallel updates checking """

    for package in packages:
        # print current progress
        with finished.lock:
            finished.increment()

            print("{}[INFO]{} Processing package {}{}{}/{}{}{}...".format(
                MessageColor.info, MessageColor.nc,
                MessageColor.data, str(finished.value), MessageColor.nc,
                MessageColor.data, str(total), MessageColor.nc),
                  end=("\r" if finished.value < total else " "))

        # check package for updates
        res = check_updates(package)

        # store result (if any)
        if res:
            output.append(res)


def check():
    """ check packages for updates """

    # create temporary directory for repo cloning
    t = tempfile.mkdtemp()

    # clone base repository
    git.Repo.clone_from(GIT_REPO, t, branch="master", depth=1)

    # prepare future package list
    pkglist = []

    # traverse all available packages in our repository
    for root, subdirs, files in os.walk(os.path.join(t, "packages")):
        for file in files:
            if file == ".SRCINFO":
                fname = os.path.join(root, file)

                with open(fname, "rt") as f:
                    srcinfo = f.readlines()

                for line in srcinfo:
                    token = line.strip()

                    if token.startswith("pkgname = "):
                        pkgname = token.split(" = ")[1].strip()

                    if token.startswith("url = "):
                        pkgurl = token.split(" = ")[1].strip()

                    if token.startswith("pkgver = "):
                        pkgver = token.split(" = ")[1].strip()

                package = {"Name": pkgname, "Version": pkgver, "URL": pkgurl}
                pkglist.append(package)

    if len(pkglist) == 0:
        print("{}[ERROR]{} There are no R packages found in the repository".format(
            MessageColor.error, MessageColor.nc))

        return

    # we'll check for updates NOW!
    # use 2x all available CPU cores
    # it's safe to oversubscribe because usual bottleneck is the network
    # connection
    num_proc = multiprocessing.cpu_count() * 2
    mgr = multiprocessing.Manager()
    pool = multiprocessing.Pool(processes=num_proc)

    # calculate load per worker
    pkg_total = len(pkglist)
    pkgs_per_proc = pkg_total // num_proc

    # shared memory objects

    # we need that fucking workaround because multiprocessing.Manager()
    # doesn't provide get_lock() for Value objects
    finished = ProgressCounter(mgr, 0)
    output_info = mgr.list()

    # load balancing
    for i in range(num_proc):
        start_i = i * pkgs_per_proc
        end_i = ((i + 1) * pkgs_per_proc) if i != (num_proc - 1) else None

        pool.apply_async(checker_worker, (pkglist[start_i:end_i], pkg_total, finished, output_info))

    # wait for all guys
    pool.close()
    pool.join()

    # print summary
    print("{}done{}".format(MessageColor.ok, MessageColor.nc))

    if len(output_info) == 0:
        print("{}[OK]{} All R packages are up-to-date".format(
            MessageColor.ok, MessageColor.nc))
    else:
        for line in output_info:
            print(line)

    shutil.rmtree(t)


def validate():
    pass


def main():
    """ main routine """

    # get command line options
    parser = argparse.ArgumentParser(description="Easy management of R packages for Arch Linux")
    parser.add_argument("command", choices=["check", "validate"], help="operation to execute")
    parser.add_argument("--version", action="version", version="%(prog)s " + SCRIPT_VERSION)
    cmdline_args = vars(parser.parse_args())

    command = cmdline_args["command"]

    if command == "check":
        print("{}[INFO]{} Will check R packages for updates".format(
            MessageColor.info, MessageColor.nc))

        check()

        print()
    elif command == "validate":
        print("{}[INFO]{} Will validate R packages for errors".format(
            MessageColor.info, MessageColor.nc))

        validate()

        print()

    # final print
    print("{}[OK]{} Job done".format(
        MessageColor.ok, MessageColor.nc))


## main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
