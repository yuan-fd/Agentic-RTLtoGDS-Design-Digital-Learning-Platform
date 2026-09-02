#!/usr/bin/env bash
# Audited S6 rollback helper.  Review the target branch before invoking.
set -euo pipefail

# Keep this helper after the rollback so the operation remains documented.
# These commits are newest-to-oldest and include every earlier change that
# modifies the S6 implementation, evidence, or its governance document.
git revert --no-edit 4179977
git revert --no-edit baf7495
git revert --no-edit 298c91e
git revert --no-edit aabd838
git revert --no-edit fdcf8a9
git revert --no-edit ae28c14
