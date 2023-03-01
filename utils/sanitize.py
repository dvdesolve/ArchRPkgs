#!/usr/bin/env python3

""" Helper for sanitizing R packages """

## import necessary modules
import argparse
import os
import re
import sys
from urllib.parse import urlparse
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

SUPPORTED_REPOS = [
    {
        "name": "CRAN",
        "url": "cran.r-project.org",
        "table_regex": r"<table>(.*?)</table>",
        "table_match_index": 1,
        "arch_regex": r"<tr>\n<td>NeedsCompilation:</td>\n<td>(.*?)</td>",
        "arch_match_index": 1,
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

SCRIPT_VERSION = "0.0.1"


## helper functions
def check_arch(package, repo):
    """ check violation of architecture specifications """

    # get NeedsCompilation info from repository
    if repo["name"] == "Bioconductor":
        print("{}[WARN]{} Architecture info checkup for {}Bioconductor{} repo isn't implemented (yet){}".format(
                MessageColor.warn, MessageColor.nc,
                MessageColor.data, MessageColor.nc,
                MessageText.skipping))
    else:
        with urlopen(package["URL"]) as response:
            html = response.read().decode("utf-8")

            table_regex = repo["table_regex"]
            table_pattern = re.compile(table_regex, flags=re.DOTALL)
            table_match = table_pattern.search(html)

            if table_match:
                # recheck
                html = table_match.group(repo["table_match_index"])

                arch_regex = repo["arch_regex"]
                arch_pattern = re.compile(arch_regex, flags = re.DOTALL)
                arch_match = arch_pattern.search(html)

                if arch_match:
                    if arch_match.group(repo["arch_match_index"]) == "yes" and sorted(package["Arch"]) != sorted(["i686", "x86_64"]):
                        print("{}[WARN]{} Architectures for {}{}{} should be {}i686, x86_64{}".format(
                            MessageColor.warn, MessageColor.nc,
                            MessageColor.data, package["Name"], MessageColor.nc,
                            MessageColor.data, MessageColor.nc))
                    elif arch_match.group(repo["arch_match_index"]) == "no" and package["Arch"] != ["any"]:
                        print("{}[WARN]{} Architecture for {}{}{} should be {}any{}".format(
                            MessageColor.warn, MessageColor.nc,
                            MessageColor.data, package["Name"], MessageColor.nc,
                            MessageColor.data, MessageColor.nc))


def sanitize(packages):
    """ sanitize packages """

    # list of packages to be processed
    if len(packages) == 0:
        rootdir = os.path.join("..", "packages")
        dirlist = [name for name in os.listdir(rootdir) if os.path.isdir(os.path.join(rootdir, name))]
    else:
        dirlist = packages

    # final list to be processed
    pkglist = []

    # for each of the package listed get its URL for future online requests
    for package in dirlist:
        name = os.path.join("..", "packages", package, ".SRCINFO")

        if os.path.isfile(name):
            with open(name, "rt") as f:
                srcinfo = f.readlines()

                pkgarchs = []
                pkglics = []
                pkgdeps = []
                pkgoptdeps = []

                for line in srcinfo:
                    token = line.strip()

                    if token.startswith("url = "):
                        pkgurl = token.split(" = ")[1].strip()

                    if token.startswith("arch = "):
                        pkgarchs.append(token.split(" = ")[1].strip())

                    if token.startswith("license = "):
                        pkglics.append(token.split(" = ")[1].strip())

                    if token.startswith("depends = "):
                        pkgdeps.append(token.split(" = ")[1].strip())

                    if token.startswith("optdepends = "):
                        pkgoptdeps.append(token.split(" = ")[1].strip())

                # add package to the list
                pkg = {"Name": package, "URL": pkgurl, "Arch": pkgarchs, "License": pkglics, "Depends": pkgdeps, "Optdepends": pkgoptdeps}
                pkglist.append(pkg)
        else:
            print("{}[WARN]{} Info for package {}{}{} can't be read{}".format(
                MessageColor.warn, MessageColor.nc,
                MessageColor.data, package, MessageColor.nc,
                MessageText.skipping))

    # check if there's something to do
    if len(pkglist) == 0:
        print("{}[INFO]{} There are no R packages to be processed".format(
            MessageColor.info, MessageColor.nc))

        return

    # we'll sanitize NOW!
    for package in pkglist:
        # get repo information from package URL
        domain = "{uri.netloc}".format(uri = urlparse(package["URL"])).lower()

        if not any(r["url"] == domain for r in SUPPORTED_REPOS):
            return "{}[WARN]{} Package {}{}{}: repository {}{}{} is unsupported (yet){}".format(
                    MessageColor.warn, MessageColor.nc,
                    MessageColor.data, package["Name"], MessageColor.nc,
                    MessageColor.data, domain, MessageColor.nc,
                    MessageText.skipping)

        repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

        print("{}[INFO]{} Processing package {}{}{}".format(
            MessageColor.info, MessageColor.nc,
            MessageColor.data, package["Name"], MessageColor.nc))

        # implemented checks
        check_arch(package, repo)

def main():
    """ main routine """

    parser = argparse.ArgumentParser(prog = 'ArchRPkgs sanitizer',
                                     description = 'Sanitize and validate R packages')

    parser.add_argument('packages', nargs = '*', help = 'list of packages to be sanitized. If list is empty then all packages in current repo will be sanitized')
    args = vars(parser.parse_args())

    # sanitize
    print("{}[INFO]{} Will sanitize and validate R packages".format(
        MessageColor.info, MessageColor.nc))

    sanitize(args["packages"])

    print()

    # final print
    print("{}[OK]{} Job done".format(
        MessageColor.ok, MessageColor.nc))


## main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
