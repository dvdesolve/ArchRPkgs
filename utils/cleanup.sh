#!/usr/bin/bash

### Management utility to cleanup build trails in source directories

find ../packages -type f -name *.tar.gz -delete
find ../packages -type f -name *.tar.bz2 -delete
find ../packages -type f -name *.zst -delete
find ../packages -type f -name *namcap.log -delete
find ../packages -type f -name *prepare.log -delete
find ../packages -type f -name *build.log -delete
find ../packages -type f -name *package.log -delete

exit 0
