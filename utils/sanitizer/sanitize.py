#!/usr/bin/env python3

""" Helper for sanitizing R packages """

## import necessary modules
import argparse
import os
import re
import rpy2
import rpy2.robjects as robjects
from rpy2.robjects.packages import importr, data
import shutil
import sys
import tarfile
from urllib.parse import urlparse, urljoin
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

    skipping = f'. {MessageColor.yellow}Skipping{MessageColor.nc}'
    exiting = f'. {MessageColor.red}Exiting{MessageColor.nc}'


## some defaults
PKG_ROOT = os.path.join("..", "..", "packages")
CACHE_ROOT = "cache"

SUPPORTED_REPOS = [
        {
            "name": "CRAN",
            "url": "cran.r-project.org",
            "pkg_regex": r"<td> Package&nbsp;source: </td>\n<td> <a href=\"(.*?)\">"
        }
]

SUPPORTED_LICS = {
        "AGPL-3": "AGPL3",
        "Apache License": "Apache",
        "Apache License (== 2.0)": "Apache",
        "Apache License 2.0": "Apache",
        "Artistic-2.0": "Artistic2.0",
        "BSD_2_clause": "BSD",
        "BSD_3_clause": "BSD",
        "BSL-1.0": "custom:BSL-1.0",
        "CC0": "custom:CC0",
        "Common Public License Version 1.0": "CPL",
        "GPL": "GPL",
        "GPL (>= 2)": "GPL2",
        "GPL (>= 2.0)": "GPL2",
        "GPL (>= 3)": "GPL3",
        "GPL (>= 3.0)": "GPL3",
        "GPL-2": "GPL2",
        "GPL-3": "GPL3",
        "LGPL": "LGPL",
        "LGPL (>= 2)": "LGPL2.1",
        "LGPL (>= 2.1)": "LGPL2.1",
        "LGPL (>= 3)": "LGPL3",
        "LGPL-2": "LGPL2.1",
        "LGPL-2.1": "LGPL2.1",
        "LGPL-3": "GPL3",
        "MPL-1.1": "MPL",
        "MPL-2.0": "MPL2",
        "MIT": "MIT",
        "Unlimited": "unknown"
}

LIC_ORDER = [
        "AGPL-3",
        "Apache License (== 2.0)",
        "Apache License 2.0",
        "Apache License",
        "Artistic-2.0",
        "BSD_2_clause",
        "BSD_3_clause",
        "BSL-1.0",
        "CC0",
        "Common Public License Version 1.0",
        "LGPL (>= 2.1)",
        "LGPL (>= 2)",
        "LGPL (>= 3)",
        "LGPL-2",
        "LGPL-2.1",
        "LGPL-3",
        "LGPL",
        "GPL (>= 2.0)",
        "GPL (>= 2)",
        "GPL (>= 3.0)",
        "GPL (>= 3)",
        "GPL-2",
        "GPL-3",
        "GPL",
        "MIT",
        "MPL-1.1",
        "MPL-2.0",
        "Unlimited"
]

SCRIPT_VERSION = "0.0.1"


## helper functions
#def process_deps(deplist):
#    result = deplist.split(",")
#
#    for i, s in enumerate(result):
#        pkg = s.strip()
#
#        nv = pkg.split(" (", 1)
#        name = nv[0]
#        ver = nv[1].rstrip(")") if len(nv) == 2 else None
#
#        result[i] = "{} ~~~ {}".format(name, ver)
#
#    return result

def clear_cache():
    """ clear package cache """

    for sd in ["packages", "descs"]:
        for fn in os.listdir(os.path.join(CACHE_ROOT, sd)):
            fp = os.path.join(CACHE_ROOT, sd, fn)

            try:
                if os.path.isfile(fp) or os.path.islink(fp):
                    os.unlink(fp)
                elif os.path.isdir(fp):
                    shutil.rmtree(fp)
            except Exception as e:
                print(f'{MessageColor.error}[ERR ]{MessageColor.nc}'
                      f' Failed to delete {MessageColor.data}{fp}{MessageColor.nc}: {e}')

def get_src(package, repo, force_down):
    """ download package source and extract DESCRIPTION """

    try:
        with urlopen(package["URL"]) as response:
            html = response.read().decode("utf-8")

            pkg_regex = repo["pkg_regex"]
            pkg_pattern = re.compile(pkg_regex, flags = re.DOTALL)
            pkgurl = urljoin(package["URL"], pkg_pattern.findall(html)[0])

            fn = os.path.basename(urlparse(pkgurl).path)
            fp = os.path.join(CACHE_ROOT, "packages", fn)

            if force_down or not os.path.isfile(fp):
                print(f'{MessageColor.info}[INFO]{MessageColor.nc}'
                      f' Downloading {MessageColor.data}{fn}{MessageColor.nc}...')

                try:
                    with urlopen(pkgurl) as response2, open(fp, "wb") as pkgsrc:
                        data = response2.read()
                        pkgsrc.write(data)


                except Exception as e:
                    print(f'{MessageColor.error}[ERR ]{MessageColor.nc}'
                          f' Error occured during downloading {MessageColor.data}{fn}{MessageColor.nc}: {e}')

            # extract DESCRIPTION file from package
            orig_name = fn.split('_')[0]
            dfn = os.path.join(CACHE_ROOT, "descs", f'{package["Name"]}.desc')

            srcgz = tarfile.open(fp)

            with srcgz.extractfile(f'{orig_name}/DESCRIPTION') as s_file, open(dfn, "wb") as d_file:
                data = s_file.read()
                d_file.write(data)

            srcgz.close()

    except Exception as e:
        print(f'{MessageColor.error}[ERR ]{MessageColor.nc}'
              f' Error occured during retrieving {MessageColor.data}{package["URL"]}{MessageColor.nc}: {e}')

def check_version(current, upstream):
    """ check for updates """

    # compare versions in field-by-field way
    our = [int(x) for x in current.split(".")]
    new = [int(x) for x in upstream.split(".")]

    if our < new:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Package is outdated: {MessageColor.old}{current}{MessageColor.nc} vs {MessageColor.new}{upstream}{MessageColor.nc}')

def check_title(current, upstream):
    """ check if package description have changed """

    if current != upstream:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Package description differs from upstream: {MessageColor.old}{current}{MessageColor.nc} vs {MessageColor.new}{upstream}{MessageColor.nc}')

def check_arch(current, upstream):
    """ check for architecture specification violations """

    if upstream == "yes" and sorted(current) != sorted(["i686", "x86_64"]):
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Architectures should be {MessageColor.data}i686, x86_64{MessageColor.nc}')
    elif upstream == "no" and current != ["any"]:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Architecture should be {MessageColor.data}any{MessageColor.nc}')

def check_license(current, upstream):
    """ check for license specification violations """

    # at first we should remove unrelated symbols and terms from license name
    lic = upstream
    lic = lic.replace("file LICENSE", "")
    lic = lic.replace("file LICENCE", "")
    lic = lic.replace(" |", "")
    lic = lic.replace(" +", "")
    lic = lic.strip()

    lics_new = set()

    # populate set with upstream licenses
    for l in LIC_ORDER:
        # if we've found exact match
        if lic.find(l) != -1:
            lics_new.add(SUPPORTED_LICS[l])
            lic = lic.replace(l, "")
            lic = lic.strip()

            # if we've already checked everything just exit
            if len(lic) == 0:
                break

    # check for each current license presented in PKGBUILD
    lics_our = current.copy()

    for l in current:
        # if we've found exact match
        if l in lics_new:
            lics_new.remove(l)
            lics_our.remove(l)

    if len(lics_new) != 0:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Missing licenses: {MessageColor.data}{lics_new}{MessageColor.nc}')

    if len(lics_our) != 0:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' Extra licenses: {MessageColor.data}{lics_our}{MessageColor.nc}')

def check_depends(current, upstream_depends, upstream_imports, upstream_linkingto):
    """ check for problems with dependencies """

    # TODO
    # split by comma, strip whitespaces, prepend with 'r-' (ignoring R itself), parse version info Arch-way and compare with PKGBUILD (also check for extra dependencies)
    pass

def check_optdepends(current, upstream):
    """ check for problems with optional dependencies """

    # TODO
    # split by comma, strip whitespaces, prepend with 'r-' (ignoring R itself), parse version info Arch-way and compare with PKGBUILD (also check for extra dependencies)
    pass

def parse_description(package):
    robjects.r['options'](warn = -1) # suppress unrelated warnings
    base = importr('base') # read.dcf(), colnames(), gsub(), as.character(), ifelse()

    dfn = os.path.join(CACHE_ROOT, "descs", f'{package["Name"]}.desc')

    rcode = (f'x <- read.dcf("{dfn}")\n'
             'fields <- colnames(x)\n\n'
             'ver <- gsub("\\n", " ", as.character(x[1, "Version"]), fixed = TRUE)\n'
             'title <- gsub("\\n", " ", as.character(x[1, "Title"]), fixed = TRUE)\n'
             'needscomp <- gsub("\\n", " ", ifelse("NeedsCompilation" %in% fields, as.character(x[1, "NeedsCompilation"]), "no"), fixed = TRUE)\n'
             'license <- gsub("\\n", " ", as.character(x[1, "License"]), fixed = TRUE)\n'
             'depends <- gsub("\\n", " ", ifelse("Depends" %in% fields, as.character(x[1, "Depends"]), NA), fixed = TRUE)\n'
             'imports <- gsub("\\n", " ", ifelse("Imports" %in% fields, as.character(x[1, "Imports"]), NA), fixed = TRUE)\n'
             'linkingto <- gsub("\\n", " ", ifelse("LinkingTo" %in% fields, as.character(x[1, "LinkingTo"]), NA), fixed = TRUE)\n'
             'suggests <- gsub("\\n", " ", ifelse("Suggests" %in% fields, as.character(x[1, "Suggests"]), NA), fixed = TRUE)\n'
             'systemreqs <- gsub("\\n", " ", ifelse("SystemRequirements" %in% fields, as.character(x[1, "SystemRequirements"]), NA), fixed = TRUE)\n')
    robjects.r(rcode)

    r_ver = robjects.globalenv['ver']
    r_title = robjects.globalenv['title']
    r_needscomp = robjects.globalenv['needscomp']
    r_license = robjects.globalenv['license']
    r_depends = robjects.globalenv['depends']
    r_imports = robjects.globalenv['imports']
    r_linkingto = robjects.globalenv['linkingto']
    r_suggests = robjects.globalenv['suggests']
    r_systemreqs = robjects.globalenv['systemreqs']

    # convert to Arch standards first
    # https://wiki.archlinux.org/index.php/R_package_guidelines
    r_ver = re.sub(r"[:-]", ".", r_ver[0])
    check_version(package["Version"], r_ver)

    r_title = r_title[0]
    check_title(package["Description"], r_title)

    r_needscomp = r_needscomp[0]
    check_arch(package["Arch"], r_needscomp)

    r_license = r_license[0]
    check_license(package["License"], r_license)

    r_depends = None if r_depends[0] is robjects.NA_Character else r_depends[0]
    r_imports = None if r_imports[0] is robjects.NA_Character else r_imports[0]
    r_linkingto = None if r_linkingto[0] is robjects.NA_Character else r_linkingto[0]
    check_depends(package["Depends"], r_depends, r_imports, r_linkingto)

    r_suggests = None if r_suggests[0] is robjects.NA_Character else r_suggests[0]
    check_optdepends(package["Optdepends"], r_suggests)

    # we can't parse it consistently so just show a warning with its contents if it's non-null
    r_systemreqs = None if r_systemreqs[0] is robjects.NA_Character else r_systemreqs[0]

    if r_systemreqs is not None:
        print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
              f' SystemRequirements is not empty, please re-check by hand: {MessageColor.data}{r_systemreqs}{MessageColor.nc}')

    return package

def sanitize(packages, force_down):
    """ perform package sanitizing """

    # list of packages to be processed
    if len(packages) == 0:
        dirlist = [name for name in os.listdir(PKG_ROOT) if os.path.isdir(os.path.join(PKG_ROOT, name))]
    else:
        dirlist = packages

    # final list to be processed
    pkglist = []

    # for each of the package listed get its URL for future online requests
    for package in dirlist:
        name = os.path.join(PKG_ROOT, package, ".SRCINFO")

        if os.path.isfile(name):
            with open(name, "rt") as f:
                srcinfo = f.readlines()

                pkgarchs = []
                pkglics = []
                pkgdeps = []
                pkgoptdeps = []

                for line in srcinfo:
                    token = line.strip()

                    if token.startswith("pkgver = "):
                        pkgver = token.split(" = ")[1].strip()

                    if token.startswith("pkgdesc = "):
                        pkgdesc = token.split(" = ")[1].strip()

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
                pkg = {"Name": package, "Version": pkgver, "Description": pkgdesc, "URL": pkgurl, "Arch": pkgarchs, "License": pkglics, "Depends": pkgdeps, "Optdepends": pkgoptdeps}
                pkglist.append(pkg)
        else:
            print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
                  f' Info for package {MessageColor.data}{package}{MessageColor.nc} can\'t be read{MessageText.skipping}')

    # check if there's something to do
    if len(pkglist) == 0:
        print(f'{MessageColor.info}[INFO]{MessageColor.nc}'
              f' There are no R packages to be processed')

        return

    # we'll sanitize NOW!
    for package in pkglist:
        # get repo information from package URL
        domain = "{uri.netloc}".format(uri = urlparse(package["URL"])).lower()

        if not any(r["url"] == domain for r in SUPPORTED_REPOS):
            print(f'{MessageColor.warn}[WARN]{MessageColor.nc}'
                  f' Package {MessageColor.data}{package["Name"]}{MessageColor.nc}: repository {MessageColor.data}{domain}{MessageColor.nc} is unsupported (yet){MessageText.skipping}')

        repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

        print(f'{MessageColor.info}[INFO]{MessageColor.nc}'
              f' Processing package {MessageColor.data}{package["Name"]}{MessageColor.nc}')

        # download package source first
        get_src(package, repo, force_down)

        # parse DESCRIPTION and perform checks
        parse_description(package)

        # print empty line after each package
        print()


def main():
    """ main routine """

    parser = argparse.ArgumentParser(prog = 'ArchRPkgs sanitizer',
                                     description = 'Sanitize and validate R packages')

    parser.add_argument('packages',
                        nargs = '*',
                        help = 'list of packages to be sanitized. If list is empty then all packages in current repo will be sanitized')
    parser.add_argument('-f',
                        action = 'store_true',
                        help = 'force to download every package source (by default only missing ones will be downloaded)')
    parser.add_argument('-c',
                        action = 'store_true',
                        help = 'clear package cache before proceeding further. NOTE: if no packages were given on a command line only cache clearing will be done!')
    parser.add_argument('--version',
                        action = 'version',
                        version = f'Sanitizer v{SCRIPT_VERSION}')
    args = vars(parser.parse_args())

    # process arguments
    if args["c"]:
        print(f'{MessageColor.info}[INFO]{MessageColor.nc}'
              f' Performing cache clearing...\n')
        clear_cache()

        if len(args["packages"]) == 0:
            print(f'{MessageColor.ok}[OK  ]{MessageColor.nc}'
                  f' Job done')
            sys.exit(0)

    print(f'{MessageColor.info}[INFO]{MessageColor.nc}'
          f' Will sanitize and validate R packages NOW!\n')
    sanitize(args["packages"], args["f"])

    print(f'{MessageColor.ok}[OK  ]{MessageColor.nc}'
          f' Job done')


## main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
