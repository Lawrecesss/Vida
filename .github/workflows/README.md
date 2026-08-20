# Release workflow

`publish.yml` builds and uploads to PyPI when a `v*` tag is pushed. It uses
**Trusted Publishing**, so no API token exists in this repo, in GitHub secrets,
or on anyone's laptop — PyPI mints a short-lived credential from the workflow's
OIDC identity at upload time.

## One-time PyPI setup

This has to be done once, by hand, by someone with owner rights on the project.
Until it is, the workflow will run and fail at the publish step.

1. Go to <https://pypi.org/manage/project/vida-sdk/settings/publishing/>
2. Add a **GitHub** publisher with exactly these values:

   | Field | Value |
   |---|---|
   | Owner | `Lawrecesss` |
   | Repository name | `Vida` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

The environment name is optional to PyPI but this workflow sets it, so it must
be filled in or the OIDC claim will not match.

## One-time GitHub setup

Create the environment the publish job references, so the deployment is gated
rather than firing on any tag anyone can push:

1. Repository → Settings → Environments → **New environment** → name it `pypi`
2. Optionally add yourself as a required reviewer. With that on, a tag push
   builds and tests immediately but waits for an approval click before the
   upload actually happens.

## Cutting a release

```bash
# 1. Bump the version in BOTH places
#    pyproject.toml  ->  version = "0.1.2"
#    vida/__init__.py ->  __version__ = "0.1.2"

# 2. Commit, then tag with a matching v-prefixed tag
git commit -am "Release 0.1.2"
git tag -a v0.1.2 -m "vida-sdk 0.1.2"
git push origin main
git push origin v0.1.2
```

The tag push is what triggers everything. The build job refuses to continue if
the tag and `pyproject.toml` disagree, so a forgotten bump fails in about a
minute rather than at upload with an opaque 400.

## What the workflow will not catch

Worth being honest about, given that 0.1.1 existed to fix a release that passed
every check:

- **Tests stub the network.** A default model slug being withdrawn from
  OpenRouter — which is exactly what broke 0.1.0 — is invisible to `pytest`.
  Nothing here substitutes for calling the real API before a release.
- **Sample media is not fetched.** The `vids/` files live in Git LFS and are not
  pulled, so the ffmpeg tests that need them skip. Those paths are only truly
  exercised locally.
