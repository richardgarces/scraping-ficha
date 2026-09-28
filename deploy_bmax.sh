#!/usr/bin/env bash
# deploy_bmax.sh - interactive deploy script to push and checkout to bmax host
# Usage: ./deploy_bmax.sh

set -euo pipefail

REMOTE_HOST="richard@192.168.1.198"
REMOTE_PORT=2222
REMOTE_PATH="/home/richard/precios"

function prompt() {
  read -r -p "$1" REPLY
}

function push_repo() {
  local repo_dir="$1"
  local branch="$2"
  echo "\n==> Pushing $repo_dir (branch $branch) to bmax..."
  pushd "$repo_dir" > /dev/null
  git add -A
  git commit -m "deploy: sync changes before deploy" || echo "No changes to commit"
  git push bmax "$branch" --set-upstream
  popd > /dev/null
}

function remote_checkout() {
  local branch="$1"
  local work_tree="$2"
  local git_dir="$3"
  echo "\n==> Running remote checkout on bmax..."
  ssh -p ${REMOTE_PORT} ${REMOTE_HOST} \
    "mkdir -p ${work_tree} && git --work-tree=${work_tree} --git-dir=${git_dir} fetch --all && git --work-tree=${work_tree} --git-dir=${git_dir} checkout -f ${branch}"
}

function remote_run() {
  local cmd="$1"
  echo "\n==> Running remote command: $cmd"
  ssh -p ${REMOTE_PORT} ${REMOTE_HOST} "$cmd"
}

function menu() {
  echo "Deploy menu for bmax"
  echo "1) Push and deploy 'scraping' repo (main)"
  echo "2) Push and deploy 'docling' repo (bmax branch)"
  echo "3) Push both and deploy"
  echo "4) Remote only (checkout without pushing)"
  echo "5) Exit"
  prompt "Choose an option: "
  case "$REPLY" in
    1) option=1 ;; 2) option=2 ;; 3) option=3 ;; 4) option=4 ;; *) exit 0 ;;
  esac

  if [[ $option -eq 1 || $option -eq 3 ]]; then
    # scraping repo
    SCRAPING_DIR="$(pwd)/scraping"
    SCRAPING_BRANCH="main"
    prompt "Push local changes for scraping? (Y/n) " && [[ "$REPLY" =~ ^([nN])$ ]] || push_repo "$SCRAPING_DIR" "$SCRAPING_BRANCH"
    prompt "Deploy scraping remotely (checkout) now? (Y/n) " && [[ "$REPLY" =~ ^([nN])$ ]] || remote_checkout "$SCRAPING_BRANCH" "$REMOTE_PATH" "$REMOTE_PATH"
    prompt "Any remote command to run after deploy (service restart)? Leave empty to skip: "
    if [[ -n "$REPLY" ]]; then
      remote_run "$REPLY"
    fi
  fi

  if [[ $option -eq 2 || $option -eq 3 ]]; then
    DOCLING_DIR="$(pwd)/docling"
    DOCLING_BRANCH="bmax"
    prompt "Push local changes for docling? (Y/n) " && [[ "$REPLY" =~ ^([nN])$ ]] || push_repo "$DOCLING_DIR" "$DOCLING_BRANCH"
    prompt "Deploy docling remotely (checkout) now? (Y/n) " && [[ "$REPLY" =~ ^([nN])$ ]] || remote_checkout "$DOCLING_BRANCH" "/home/richard/precios" "/home/richard/precios"
    prompt "Any remote command to run after deploy (service restart)? Leave empty to skip: "
    if [[ -n "$REPLY" ]]; then
      remote_run "$REPLY"
    fi
  fi

  if [[ $option -eq 4 ]]; then
    prompt "Branch to checkout remotely (default main): "
    branch=${REPLY:-main}
    remote_checkout "$branch" "$REMOTE_PATH" "$REMOTE_PATH"
  fi

  echo "\nDone."
}

menu
