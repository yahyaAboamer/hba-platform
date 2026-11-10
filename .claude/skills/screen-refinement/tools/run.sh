#!/bin/bash
# usage: run.sh <web-dir|staging> <out-dir> '<sizes json>' '<only json|null>' [dark|light]
R="$(cd "$(dirname "$0")" && pwd)"
sed -e "s#__WEB__#$1#" -e "s#__OUT__#$2#" -e "s#__SIZES__#$3#" -e "s#__ONLY__#$4#" -e "s#__THEME__#${5:-dark}#" "$R/harness.tpl.js" > "$R/harness.js"
cd "$R" && playwright-cli -s=hba --raw run-code --filename=harness.js
