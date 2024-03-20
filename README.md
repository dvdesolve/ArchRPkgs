# R packages for Arch Linux
This repository contains ready-to-use `PKGBUILD`s for manual building of R packages and installing them with Pacman.

## PROJECT IS GOING TO ARCHIVE
Unfortunately, I have no more time and power to keep project alive. It was great experience and I hope that my work helped someone. Since 20.03.2024 the project is going to be read only. Latest binary build available up to this date will reside in my repository till 01.01.2025 and then will be deleted. This GitHub repo is going to be archived but will remain accessible to anyone. Hope that enthusiasts will take it for their needs and improve existing toolset presented in this repo. Thank you, everyone!

## Adding packages
If you don't know how to write your own `PKGBUILD`s feel free to ask me for adding new package via issue mechanism of GitHub.

Otherwise, if you have experience with writing build scripts for Arch Linux please first check [corresponding ArchWiki article](https://wiki.archlinux.org/title/R_package_guidelines) about creating R-specific packages. When your `PKGBUILD` will be ready don't forget to generate proper `.SRCINFO` for it (e. g. with `makepkg --printsrcinfo > .SRCINFO`) and open pull request. It's highly advised to check build in [clean chroot](https://wiki.archlinux.org/title/DeveloperWiki:Building_in_a_clean_chroot) to track down possible issues.

## Binary repository
All of packages presented in current repository are also exist in compiled binary form and placed in my own repository. Default upstream `makepkg.conf` is used during package building and every package is signed with my PGP signature.

To use my repository for installing R packages you should add the following block at the end of your `/etc/pacman.conf`:
```
[desolve]
Server = https://desolve.ru/archrepo/$arch
```
Currently only `x86_64` architecture is supported but `i686` and ARM-specific repos can appear soon. Also don't forget to add my public GPG key to your local pacman keyring. You can refer [to this chapter](https://wiki.archlinux.org/title/Pacman/Package_signing#Adding_unofficial_keys) of ArchWiki or just use the following two commands:
```
# pacman-key --recv-keys DD3BF75DCD96541AC723B7CD6A4CD3276CA8EBBD
# pacman-key --lsign-key DD3BF75DCD96541AC723B7CD6A4CD3276CA8EBBD
```
Please also note that this repository can contain some extra packages which are not R-related (such as Qt4), so please be careful and check what and from where you're installing.

For more information see [this](https://wiki.archlinux.org/title/Unofficial_user_repositories#desolve) ArchWiki subsection.

## Reporting bugs, problems, requests
To propose your ideas, report bugs etc. feel free to use issues mechanism of GitHub.
