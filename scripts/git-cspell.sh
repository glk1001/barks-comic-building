echo Spell checking uncommited python files:

echo
git diff --name-only --diff-filter=ACMRTUXB HEAD | grep '\.py$'

echo
git diff --name-only --diff-filter=ACMRTUXB HEAD | grep '\.py$' | xargs bunx cspell --no-must-find-files
