# ForgePulse Activity Archive

This service snapshots and organizes GitHub user, organization, and repository activity data to support discovery and inspection workflows.

## Datastore

### `github.json` — single document
Holds a single aggregated document containing the authenticated user profile plus cached lists of GitHub users, repositories, branches, files, issues, issue comments, and pull requests so the service can present GitHub data without refetching it for every operation.

- `me` — object
  each record in `me` has:
  - `login` — string
  - `id` — integer
  - `node_id` — string
  - `type` — string
  - `name` — string
  - `company` — string
  - `email` — string
  - `bio` — string
  - `public_repos` — integer
  - `followers` — integer
  - `following` — integer
  - `html_url` — string
  - `site_admin` — boolean
- `users` — array
  each record in `users` has:
  - `login` — string
  - `id` — integer
  - `node_id` — string
  - `type` — string — one of Bot, User
  - `name` — string
  - `company` — string
  - `email` — string — nullable
  - `bio` — string
  - `public_repos` — integer
  - `followers` — integer
  - `following` — integer
  - `html_url` — string
  - `site_admin` — boolean
- `repos` — array
  each record in `repos` has:
  - `id` — integer
  - `node_id` — string — one of R_kgDOAA1001, R_kgDOAA1002, R_kgDOAA1003, R_kgDOAA1004, R_kgDOAA1005
  - `name` — string — one of ci-pipeline, data-warehouse, hello-world, payments-svc, storefront
  - `full_name` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `private` — boolean
  - `owner` — object
    each record in `owner` has:
    - `login` — string
    - `id` — integer
    - `type` — string
  - `html_url` — string
  - `description` — string
  - `fork` — boolean
  - `default_branch` — string
  - `language` — string — one of Go, Python, SQL, TypeScript, YAML
  - `stargazers_count` — integer
  - `forks_count` — integer
  - `open_issues_count` — integer
  - `watchers_count` — integer
  - `created_at` — string
  - `updated_at` — string
  - `topics` — array
- `branches` — array
  each record in `branches` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `name` — string
  - `protected` — boolean
  - `commit` — object
    each record in `commit` has:
    - `sha` — string
    - `url` — string
- `files` — array
  each record in `files` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `path` — string
  - `ref` — string
  - `type` — string
  - `sha` — string
  - `size` — integer
  - `encoding` — string
  - `content_text` — string
  - `html_url` — string
  - `download_url` — string
- `issues` — array
  each record in `issues` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `number` — integer
  - `id` — integer
  - `node_id` — string — one of I_kwDOAA1, I_kwDOAA2, I_kwDOAA3, I_kwDOAA4, I_kwDOAA5
  - `title` — string
  - `state` — string — one of closed, open
  - `locked` — boolean
  - `body` — string
  - `user` — object
    each record in `user` has:
    - `login` — string
    - `id` — integer
  - `labels` — array
    each record in `labels` has:
    - `id` — integer
    - `name` — string
    - `color` — string
  - `assignees` — array
    each record in `assignees` has:
    - `login` — string — one of alice, bob, carol, david, eva, frank, henry, jake
    - `id` — integer
  - `comments` — integer
  - `milestone` — null — nullable
  - `created_at` — string
  - `updated_at` — string
  - `closed_at` — string — nullable
  - `html_url` — string
  - `state_reason` — string — nullable
- `issue_comments` — array
  each record in `issue_comments` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `issue_number` — integer
  - `id` — integer
  - `user` — object
    each record in `user` has:
    - `login` — string — one of alice, bob, carol, frank, iris, octocat
    - `id` — integer
  - `body` — string
  - `created_at` — string
  - `updated_at` — string
  - `html_url` — string
- `pulls` — array
  each record in `pulls` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `number` — integer
  - `id` — integer
  - `node_id` — string — one of PR_kwDOAA4, PR_kwDOAA5, PR_kwDOAA6, PR_kwDOAA7, PR_kwDOAA8
  - `title` — string
  - `state` — string — one of closed, open
  - `draft` — boolean
  - `merged` — boolean
  - `body` — string
  - `user` — object
    each record in `user` has:
    - `login` — string — one of alice, bob, carol, david, frank, jake, octocat
    - `id` — integer
  - `head` — object
    each record in `head` has:
    - `full_name` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `base` — object
    each record in `base` has:
    - `full_name` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `mergeable` — boolean
  - `merged_at` — string — nullable
  - `created_at` — string
  - `updated_at` — string
  - `closed_at` — string — nullable
  - `html_url` — string
- `pr_files` — array
  each record in `pr_files` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `pull_number` — integer
  - `filename` — string
  - `status` — string — one of added, modified
  - `additions` — integer
  - `deletions` — integer
  - `changes` — integer
  - `sha` — string
  - `patch` — string
- `commits` — array
  each record in `commits` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `sha` — string
  - `commit` — object
    each record in `commit` has:
    - `name` — string — one of Alice Johnson, Bob Smith, Carol Lee, David Kim, Frank Mueller, Henry Chen, Jake Thompson, The Octocat
    - `email` — string
    - `date` — string
  - `author` — object
    each record in `author` has:
    - `login` — string — one of alice, bob, carol, david, frank, henry, jake, octocat
    - `id` — integer
  - `committer` — object
    each record in `committer` has:
    - `login` — string — one of alice, bob, carol, david, frank, henry, jake, octocat
    - `id` — integer
  - `html_url` — string
  - `stats` — object
    each record in `stats` has:
    - `additions` — integer
    - `deletions` — integer
    - `total` — integer
  - `files` — array
    each record in `files` has:
    - `filename` — string
    - `status` — string — one of added, modified
    - `additions` — integer
    - `deletions` — integer
    - `changes` — integer
- `tags` — array
  each record in `tags` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `name` — string
  - `commit` — object
    each record in `commit` has:
    - `sha` — string
    - `url` — string
- `releases` — array
  each record in `releases` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `id` — integer
  - `tag_name` — string
  - `name` — string
  - `body` — string
  - `draft` — boolean
  - `prerelease` — boolean
  - `author` — object
    each record in `author` has:
    - `login` — string — one of alice, carol, david, frank, octocat
    - `id` — integer
    - `type` — string
  - `published_at` — string
  - `created_at` — string
  - `html_url` — string
  - `target_commitish` — string
- `labels` — array
  each record in `labels` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `id` — integer
  - `name` — string
  - `color` — string
  - `default` — boolean
  - `description` — string
- `teams` — array
  each record in `teams` has:
  - `slug` — string — one of data, payments, platform, storefront
  - `org` — string
  - `name` — string — one of Data, Payments, Platform, Storefront
  - `description` — string
  - `members` — array
    each record in `members` has:
    - `login` — string
    - `id` — integer
- `issue_types` — array
  each record in `issue_types` has:
  - `name` — string — one of Bug, Feature, Incident, Task
  - `description` — string
  - `enabled` — boolean
- `reviews` — array
  each record in `reviews` has:
  - `repo` — string — one of octocat/ci-pipeline, octocat/data-warehouse, octocat/hello-world, octocat/payments-svc, octocat/storefront
  - `pull_number` — integer
  - `id` — integer
  - `user` — object
    each record in `user` has:
    - `login` — string — one of alice, bob, frank, grace, iris, octocat
    - `id` — integer
  - `state` — string — one of APPROVED, CHANGES_REQUESTED, COMMENTED
  - `body` — string
  - `submitted_at` — string
