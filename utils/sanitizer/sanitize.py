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
        "LGPL-2.1",
        "LGPL-2",
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

MC_nc = ""
MC_error = ""
MC_ok = ""
MC_warn = ""
MC_info = ""
MC_data = ""
MC_old = ""
MC_new = ""

MT_skipping = f'. Skipping'
MT_exiting = f'. Exiting'


## helper functions
def colorize():
    global MC_nc, MC_error, MC_ok, MC_warn, MC_info, MC_data, MC_old, MC_new, MT_skipping, MT_exiting

    MC_red = "\033[1;31m"
    MC_green = "\033[1;32m"
    MC_yellow = "\033[1;33m"
    MC_blue = "\033[1;34m"
    MC_purple = "\033[1;35m"
    MC_nc = "\033[0m"
    MC_error = MC_red
    MC_ok = MC_green
    MC_warn = MC_yellow
    MC_info = MC_purple
    MC_data = MC_blue
    MC_old = MC_red
    MC_new = MC_green

    MT_skipping = f'. {MC_yellow}Skipping{MC_nc}'
    MT_exiting = f'. {MC_red}Exiting{MC_nc}'

def archver(rver):
    """ convert R package version to conform to Arch standards
        https://wiki.archlinux.org/index.php/R_package_guidelines """

    return re.sub(r"[:-]", ".", rver)

def archname(rname):
    """ convert R package name to conform to Arch standards
        https://wiki.archlinux.org/index.php/R_package_guidelines """

    return f'r-{rname.lower()}'

def compare_ver(old, new):
    """ compare to archversions """

    old = [int(x) for x in old.split(".")]
    new = [int(x) for x in new.split(".")]

    if old < new:
        return -1
    elif old > new:
        return 1
    else:
        return 0

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
                print(f'{MC_error}[ERR ]{MC_nc}'
                      f' Failed to delete {MC_data}{fp}{MC_nc}: {e}')

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

            # TODO add check for file size equality
            if force_down or not os.path.isfile(fp):
                print(f'{MC_info}[INFO]{MC_nc}'
                      f' Downloading {MC_data}{fn}{MC_nc}...')

                try:
                    with urlopen(pkgurl) as response2, open(fp, "wb") as pkgsrc:
                        data = response2.read()
                        pkgsrc.write(data)


                except Exception as e:
                    print(f'{MC_error}[ERR ]{MC_nc}'
                          f' Error occured during downloading {MC_data}{fn}{MC_nc}: {e}')

            # extract DESCRIPTION file from package
            orig_name = fn.split('_')[0]
            dfn = os.path.join(CACHE_ROOT, "descs", f'{package["Name"]}.desc')

            srcgz = tarfile.open(fp)

            with srcgz.extractfile(f'{orig_name}/DESCRIPTION') as s_file, open(dfn, "wb") as d_file:
                data = s_file.read()
                d_file.write(data)

            srcgz.close()

    except Exception as e:
        print(f'{MC_error}[ERR ]{MC_nc}'
              f' Error occured during retrieving {MC_data}{package["URL"]}{MC_nc}: {e}')

def check_version(current, upstream):
    """ check for updates """

    if compare_ver(current, upstream) == -1:
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Package is outdated: {MC_old}{current}{MC_nc} vs {MC_new}{upstream}{MC_nc}')

def check_title(current, upstream):
    """ check if package description have changed """

    if current != upstream:
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Package description differs from upstream: {MC_old}{current}{MC_nc} vs {MC_new}{upstream}{MC_nc}')

def check_arch(current, upstream):
    """ check for architecture specification violations """

    if upstream == "yes" and sorted(current) != sorted(["i686", "x86_64"]):
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Architectures should be {MC_data}i686, x86_64{MC_nc}')
    elif upstream == "no" and current != ["any"]:
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Architecture should be {MC_data}any{MC_nc}')

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

    lics_new = list(lics_new)

    if len(lics_new) == 0:
        lics_new.append("unknown")

    if len(lics_new) >= 2 and "unknown" in lics_new:
        lics_new.remove("unknown")

    # check for each current license presented in PKGBUILD
    lics_our = current.copy()

    for l in current:
        # if we've found exact match
        if l in lics_new:
            # remove from both lists
            lics_new.remove(l)
            lics_our.remove(l)

    # TODO in case of unknown license should install LICENSE/LICENCE file
    if len(lic) != 0:
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Unknown licenses: {MC_data}{lic}{MC_nc}')

    if len(lics_new) != 0:
        lics_new.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Missing licenses: {MC_data}{" ".join(lics_new)}{MC_nc}')

    if len(lics_our) != 0:
        lics_our.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Extra licenses: {MC_data}{" ".join(lics_our)}{MC_nc}')

def check_depends(current, upstream_depends, upstream_imports, upstream_linkingto):
    """ check for problems with dependencies """

    # handle Nones
    upstream_depends = "" if upstream_depends is None else upstream_depends
    upstream_imports = "" if upstream_imports is None else upstream_imports
    upstream_linkingto = "" if upstream_linkingto is None else upstream_linkingto

    # merge and cleanup upstream dependencies
    upstream = ",".join([upstream_depends, upstream_imports, upstream_linkingto]) # join all together
    upstream = upstream.replace(", ", ",") # fix inconsistencies with item separation
    upstream = upstream.replace(")", "") # remove unnecessary closing parenthesis
    upstream = upstream.replace(" (>= ", ">=") # early preparations for version checking
    upstream = upstream.replace("(>= ", ">=")
    upstream = upstream.replace(" (> ", ">=") # TODO should handle strict greater than correctly
    upstream = upstream.replace("(> ", ">=") # TODO should handle strict greater than correctly
    upstream = upstream.split(",") # split to separate dependencies
    upstream = [x for x in upstream if x] # remove empty items
    upstream = list(set(upstream)) # leave only unique items

    # prepend with proper prefix and store into dict
    deps_new = {}

    for d in upstream:
        # split by possible version specifier
        spec = d.split(">=")

        # handle "R" correctly and convert to lowercase
        spec[0] = archname(spec[0]) if spec[0] != "R" else "r"

        # fix version info if necessary
        if len(spec) == 2 and spec[1] is not None:
            spec[1] = archver(spec[1])

        # check if element already exists in dict and update info if necessary
        if spec[0] in deps_new:
            # compare with existing version info and update to newer possible
            if len(spec) == 2:
                if deps_new[spec[0]] is None or compare_ver(deps_new[spec[0]], spec[1]) < 0:
                    deps_new[spec[0]] = spec[1]
        else:
            if len(spec) == 1:
                deps_new[spec[0]] = None
            else:
                deps_new[spec[0]] = spec[1]

    # explicitly add R as dependency
    if "r" not in deps_new:
        deps_new["r"] = None

    # now it's time to populate similar dict for current dependencies
    deps_our = {}

    for d in current:
        # split by possible version specifier
        spec = d.split(">=")

        # check if version spec is presented and add to the dict
        if len(spec) == 1:
            deps_our[spec[0]] = None
        else:
            deps_our[spec[0]] = spec[1]

    # make a copy for iteration
    current = deps_our.copy()

    # now we're ready to walk through the final lists of dependencies and check for problems
    for d in current:
        if d in deps_new:
            # check for version incosistencies
            if deps_our[d] is None and deps_new[d] is not None:
                print(f'{MC_warn}[WARN]{MC_nc}'
                      f' For dependency {MC_data}{d}{MC_nc} version should be set to {MC_data}>={deps_new[d]}{MC_nc}')
            elif deps_our[d] is not None and deps_new[d] is None:
                print(f'{MC_warn}[WARN]{MC_nc}'
                      f' For dependency {MC_data}{d}{MC_nc} version shouldn\'t be set at all')
            elif deps_our[d] is not None and deps_new[d] is not None and compare_ver(deps_our[d], deps_new[d]) != 0:
                print(f'{MC_warn}[WARN]{MC_nc}'
                      f' For dependency {MC_data}{d}{MC_nc} version mismatches with upstream: {MC_old}{deps_our[d]}{MC_nc} vs {MC_new}{deps_new[d]}{MC_nc}')

            # remove from both lists
            deps_new.pop(d)
            deps_our.pop(d)

    # TODO check against suppresion lists
    if len(deps_new) != 0:
        d_new = []

        for d, v in deps_new.items():
            if v is None:
                d_new.append(d)
            else:
                d_new.append(f'{d}>={v}')

        d_new.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Missing dependencies: {MC_data}{" ".join(d_new)}{MC_nc}')

    # TODO check against suppresion lists
    # TODO split by starting string (r-) to tell truly and possibly extra dependencies
    if len(deps_our) != 0:
        d_our = []

        for d, v in deps_our.items():
            if v is None:
                d_our.append(d)
            else:
                d_our.append(f'{d}>={v}')

        d_our.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Extra dependencies: {MC_data}{" ".join(d_our)}{MC_nc}')

def check_optdepends(current, upstream):
    """ check for problems with optional dependencies """

    # handle Nones
    upstream = "" if upstream is None else upstream

    # cleanup upstream dependencies
    upstream = upstream.replace(", ", ",") # fix inconsistencies with item separation
    upstream = re.sub(r" \(.*?\)", "", upstream) # remove version info because it's of no use in PKGBUILD for optdepends
    upstream = re.sub(r"\(.*?\)", "", upstream)
    upstream = upstream.split(",") # split to separate dependencies
    upstream = [x for x in upstream if x] # remove empty items
    upstream = list(set(upstream)) # leave only unique items

    # prepend with proper prefix and store into list
    deps_new = []

    for d in upstream:
        # convert to lowercase
        deps_new.append(archname(d).strip()) # because 2nd regexp in this function can leave unwanted spaces

    # now we're ready to walk through the final lists of dependencies and check for inconsistencies
    deps_our = current.copy()

    for d in current:
        if d in deps_new:
            # remove from both lists
            deps_new.remove(d)
            deps_our.remove(d)

    # TODO check against suppresion lists
    if len(deps_new) != 0:
        deps_new.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Missing optional dependencies: {MC_data}{" ".join(deps_new)}{MC_nc}')

    # TODO check against suppresion lists
    # TODO split by starting string (r-) to tell truly and possibly extra dependencies
    if len(deps_our) != 0:
        deps_our.sort()

        print(f'{MC_warn}[WARN]{MC_nc}'
              f' Extra optional dependencies: {MC_data}{" ".join(deps_our)}{MC_nc}')

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
    r_ver = archver(r_ver[0])
    check_version(package["Version"], r_ver)

    r_title = r_title[0]
    check_title(package["Description"], r_title)

    r_needscomp = r_needscomp[0]
    check_arch(package["Arch"], r_needscomp)

    r_license = r_license[0]
    check_license(package["License"], r_license)

    r_depends = None if (r_depends[0] is robjects.NA_Character or len(r_depends[0]) == 0) else r_depends[0]
    r_imports = None if (r_imports[0] is robjects.NA_Character or len(r_imports[0]) == 0) else r_imports[0]
    r_linkingto = None if (r_linkingto[0] is robjects.NA_Character or len(r_linkingto[0]) == 0) else r_linkingto[0]
    check_depends(package["Depends"], r_depends, r_imports, r_linkingto)

    r_suggests = None if (r_suggests[0] is robjects.NA_Character or len(r_suggests[0]) == 0) else r_suggests[0]
    check_optdepends(package["Optdepends"], r_suggests)

    # TODO check against suppresion lists
    # we can't parse it consistently so just show a warning with its contents if it's non-null
    r_systemreqs = None if (r_systemreqs[0] is robjects.NA_Character or len(r_systemreqs[0]) == 0) else r_systemreqs[0]

    if r_systemreqs is not None:
        print(f'{MC_warn}[WARN]{MC_nc}'
              f' SystemRequirements is not empty, please re-check by hand: {MC_data}{r_systemreqs}{MC_nc}')

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

    # TODO possible parallelization here
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
            print(f'{MC_warn}[WARN]{MC_nc}'
                  f' Info for package {MC_data}{package}{MC_nc} can\'t be read{MT_skipping}')

    # check if there's something to do
    if len(pkglist) == 0:
        print(f'{MC_info}[INFO]{MC_nc}'
              f' There are no R packages to be processed')

        return

    # sort for convenience
    pkglist = sorted(pkglist, key = lambda d: d["Name"])

    # TODO possible parallelization here
    # we'll sanitize NOW!
    for package in pkglist:
        # get repo information from package URL
        domain = "{uri.netloc}".format(uri = urlparse(package["URL"])).lower()

        if not any(r["url"] == domain for r in SUPPORTED_REPOS):
            print(f'{MC_warn}[WARN]{MC_nc}'
                  f' Package {MC_data}{package["Name"]}{MC_nc}: repository {MC_data}{domain}{MC_nc} is unsupported (yet){MT_skipping}')

        repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

        print(f'{MC_info}[INFO]{MC_nc}'
              f' Processing package {MC_data}{package["Name"]}{MC_nc}')

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

    # TODO add optional flags for checking pkgrels, suppressing different kinds of errors/warnings
    parser.add_argument('packages',
                        nargs = '*',
                        help = 'list of packages to be sanitized. If list is empty then all packages in current repo will be sanitized')
    parser.add_argument('-f', # TODO add check for file size equality
                        action = 'store_true',
                        help = 'force to download every package source (by default only missing ones will be downloaded)')
    parser.add_argument('-c',
                        action = 'store_true',
                        help = 'clear package cache before proceeding further. NOTE: if no packages were given on a command line only cache clearing will be done!')
    parser.add_argument('-g',
                        action = 'store_true',
                        help = 'disable coloring')
    parser.add_argument('--version',
                        action = 'version',
                        version = f'Sanitizer v{SCRIPT_VERSION}')
    args = vars(parser.parse_args())

    # process arguments
    if not args["g"]:
        colorize()

    if args["c"]:
        print(f'{MC_info}[INFO]{MC_nc}'
              f' Performing cache clearing...\n')
        clear_cache()

        if len(args["packages"]) == 0:
            print(f'{MC_ok}[OK  ]{MC_nc}'
                  f' Job done')
            sys.exit(0)

    print(f'{MC_info}[INFO]{MC_nc}'
          f' Will sanitize and validate R packages NOW!\n')
    sanitize(args["packages"], args["f"])

    print(f'{MC_ok}[OK  ]{MC_nc}'
          f' Job done')


## main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
