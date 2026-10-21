#!/usr/bin/env bash
# Publish docs/wiki/ to the repository's GitHub wiki.
#
# The wiki is a separate git repository (<repo>.wiki.git). GitHub creates it
# only after the first page is saved in the web UI, so create any page once by
# hand ("Create the first page" on the Wiki tab), then run this script.
# docs/wiki/ is the source of truth: wiki edits made on GitHub are overwritten.
set -euo pipefail

repo="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
root="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

git clone --quiet "git@github.com:${repo}.wiki.git" "$work"
find "$work" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$root/docs/wiki/." "$work/"
if [ -d "$root/docs/images" ]; then
  mkdir -p "$work/images"
  cp -R "$root/docs/images/." "$work/images/"
fi
# In the repository pages link as Page-Name.md (so they work when browsing
# docs/wiki/ on GitHub); the wiki wants bare page names.
for page in "$work"/*.md; do
  sed -i.bak -E 's/\]\(([A-Za-z0-9_-]+)\.md(#[^)]*)?\)/](\1\2)/g; s#\]\(\.\./images/#](images/#g' "$page"
  rm -f "$page.bak"
done
cd "$work"
git add -A
if git diff --cached --quiet; then
  echo "wiki already up to date"
  exit 0
fi
git commit --quiet -m "Sync wiki from docs/wiki ($(git -C "$root" rev-parse --short HEAD))"
git push --quiet origin HEAD
echo "published docs/wiki to https://github.com/${repo}/wiki"
