#!/usr/bin/bash

### Management utility to check whether R packages from base distribution are listed as deps

while read p; do
    grep --color=auto -rnw ../packages -e "r-${p}"
done < ../rbase.txt

exit 0
