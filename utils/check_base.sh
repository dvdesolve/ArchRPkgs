#!/usr/bin/bash

while read p; do
    grep --color=auto -rnw ../packages -e "r-${p}"
done < ../rbase.txt

exit 0
