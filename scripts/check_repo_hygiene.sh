#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

FAIL=0

check_not_tracked() {
    local pattern="$1"
    local label="$2"
    local matches
    matches=$(git ls-files -z "$pattern" 2>/dev/null | tr '\0' '\n' || true)
    if [ -n "$matches" ]; then
        echo -e "${RED}FAIL${NC}: $label is tracked by git:"
        echo "$matches"
        FAIL=1
    else
        echo -e "${GREEN}OK${NC}: $label not tracked"
    fi
}

check_not_tracked_glob() {
    local pattern="$1"
    local label="$2"
    local matches
    matches=$(git ls-files -z ":(glob)$pattern" 2>/dev/null | tr '\0' '\n' || true)
    if [ -n "$matches" ]; then
        echo -e "${RED}FAIL${NC}: $label is tracked by git:"
        echo "$matches"
        FAIL=1
    else
        echo -e "${GREEN}OK${NC}: $label not tracked"
    fi
}

check_not_tracked '.env' '.env files'
check_not_tracked '.env.*' '.env.* files'
check_not_tracked_glob '**/.env' 'nested .env files'
check_not_tracked_glob '**/.env.*' 'nested .env.* files'
check_not_tracked '*.pyc' '*.pyc files'
check_not_tracked_glob '**/__pycache__' '__pycache__ directories'
check_not_tracked_glob '**/.venv' '.venv directories'
check_not_tracked_glob '**/venv' 'venv directories'
check_not_tracked_glob '**/node_modules' 'node_modules directories'
check_not_tracked_glob '**/*.egg-info' '*.egg-info directories'
check_not_tracked_glob '**/build' 'build directories'
check_not_tracked_glob '**/dist' 'dist directories'
check_not_tracked '.coverage' '.coverage files'
check_not_tracked '.coverage.*' '.coverage.* files'
check_not_tracked_glob '**/htmlcov' 'htmlcov directories'
check_not_tracked '.DS_Store' '.DS_Store files'
check_not_tracked '*.db' '*.db files'
check_not_tracked '*.sqlite3' '*.sqlite3 files'
check_not_tracked_glob '**/.mypy_cache' '.mypy_cache directories'
check_not_tracked_glob '**/.ruff_cache' '.ruff_cache directories'
check_not_tracked_glob '**/.pytest_cache' '.pytest_cache directories'
check_not_tracked '*.swp' '*.swp files'
check_not_tracked '*.swo' '*.swo files'
check_not_tracked '*.whl' '*.whl files'
check_not_tracked 'Thumbs.db' 'Thumbs.db files'

if [ -f README.md ] && grep -q 'docs/spec.md' README.md && [ ! -f docs/spec.md ]; then
    echo -e "${RED}FAIL${NC}: README.md references missing docs/spec.md"
    FAIL=1
else
    echo -e "${GREEN}OK${NC}: README spec links do not point at missing docs/spec.md"
fi

if [ "$FAIL" -ne 0 ]; then
    echo -e "\n${RED}Repository hygiene check FAILED${NC}"
    exit 1
fi

echo -e "\n${GREEN}Repository hygiene check PASSED${NC}"
