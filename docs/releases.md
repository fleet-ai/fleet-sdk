# Fleet Python SDK releases

Fleet SDK releases originate only from protected `main`.

1. Release Please opens or updates a release PR containing the version bump and `CHANGELOG.md`.
2. Required SDK CI tests Python 3.9–3.14 and builds, inspects, installs, and retains the wheel and sdist.
3. Merging the approved release PR makes Release Please create the immutable `fleet-python-vX.Y.Z` tag and a draft GitHub release.
4. The release workflow checks out that exact commit, proves the tag is on `origin/main`, reruns the full suite, builds once, verifies both artifact versions, and publishes those files through the protected `pypi` environment using OIDC Trusted Publishing.
5. Only after PyPI succeeds does automation attach the artifacts, publish the GitHub release, and dispatch a separate Theseus consumer-update PR.

## Required repository configuration

- Protect `main` and require all `SDK CI` jobs plus review approval.
- Admit `fleet-ai/fleet-sdk` to the WarpBuild runner group. CI and release workflows require `warp-ubuntu-latest-x64-4x` directly and intentionally do not fall back to GitHub-hosted runners.
- Configure the `pypi` GitHub environment with required reviewers and PyPI Trusted Publisher subject `fleet-ai/fleet-sdk`, workflow `.github/workflows/release.yml`, environment `pypi`.
- Set `RELEASE_PLEASE_TOKEN` to a narrowly scoped GitHub App token or fine-grained PAT that can update release PRs and contents. The bot-authored PR must trigger required CI.
- Set `FLEET_SDK_CONSUMER_TOKEN` to a narrowly scoped token allowed only to dispatch the `fleet-sdk-released` event to `fleet-ai/theseus`.

## Failure and retry policy

- A failed test, build, metadata check, environment approval, or PyPI upload leaves the GitHub release in draft. Fix forward; do not move or recreate the immutable tag.
- PyPI versions are immutable. If PyPI accepted the files but a later GitHub/consumer step failed, rerun only the failed job or finalize the existing draft release; do not republish the version.
- If failure happens before PyPI accepts the files, rerun the failed workflow job at the same tagged SHA. The retained workflow artifact is evidence; the publish job still rebuilds and verifies from the tag before uploading.
- To roll back a defective release, publish a new patch release. Never delete or retarget a published tag.
