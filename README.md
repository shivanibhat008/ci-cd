# Deployment Repository (`ci-cd`)

This repository is intentionally decoupled from the application source code (`my-app-code`). It stores Kubernetes manifests managed via Kustomize and hosts the reusable GitHub Actions CD workflow responsible for deploying, verifying, and rolling back workloads in the **Dev** environment.

*Note: This repository currently runs only for `dev` environment configuration (`deploy-dev.yaml`) for rapid integration testing and demonstration.*

---

## Architecture & Role

This repository acts as the **single source of truth** for cluster state:

1. **Decoupled Delivery:** Application builds live in `my-app-code`, while Kubernetes deployment logic and environment manifests live here.
2. **Reusable CD Workflow:** Exposes `deploy-dev.yaml` via `workflow_call`, allowing `my-app-code` to trigger deployments without duplicating Kubernetes or Kustomize logic.
3. **1:1 Git-to-Cluster Sync:** Changes to `kustomization.yaml` are only committed and pushed back to `main` *after* the Kubernetes cluster confirms a healthy deployment/rollout.

---

## Repository Structure

```text
├── .github/workflows/
│   └── deploy-dev.yaml        # Reusable CD workflow triggered by my-app-code
└── k8s/
    ├── base/                     # Shared Kubernetes manifests (Deployments, Services, Jobs)
    └── overlays/
        └── dev/
            └── kustomization.yaml # Dev overlay dynamically updated via 'kustomize edit'
```

---

##  Reusable Workflow Contract (`deploy-dev.yaml`)

The workflow is triggered via `workflow_call` from `my-app-code` after a successful Docker image build and push.

### Inputs & Secrets

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `base_version` | Input (`string`) | Yes | Semantic version extracted from the commit message (e.g., `v1.3.0`). |
| `component` | Input (`string`) | Yes | Target component to deploy (`backend`, `frontend`, or `db-migrations`). |
| `DOCKERHUB_USERNAME` | Secret | Yes | Registry username used to construct the full immutable image reference. |
| `CI_APP_ID` | Secret | Yes | GitHub App ID for generating short-lived cross-repo access tokens. |
| `CI_APP_PRIVATE_KEY` | Secret | Yes | Private key for the GitHub App (replaces static PATs). |

### Example Caller Snippet (from `my-app-code`)

```yaml
uses: <org-or-user>/platform-ci-cd/.github/workflows/deploy-to-dev.yaml@main
with:
  base_version: ${{ needs.detect-changes.outputs.version }}
  component: "backend"
secrets:
  DOCKERHUB_USERNAME: ${{ secrets.DOCKERHUB_USERNAME }}
  CI_APP_ID: ${{ secrets.CI_APP_ID }}
  CI_APP_PRIVATE_KEY: ${{ secrets.CI_APP_PRIVATE_KEY }}
```

---

## Deployment Execution Flow

When invoked, `deploy-to-dev.yaml` executes the following automated sequence:

1. **Short-Lived Authentication:** Uses `actions/create-github-app-token` to mint a temporary, repository-scoped token and checks out `ci-cd`.
2. **Immutable Manifest Injection:** Computes the full image tag (`<base_version>-sha-<short_sha>`) and updates `k8s/overlays/dev/kustomization.yaml`:
   * Updates the image tag using `kustomize edit set image`.
   * Removes the previous ConfigMap entry via `yq` and regenerates `<component>-config` with the live `APP_VERSION`.
3. **Workload-Aware Cluster Apply:** Runs `kubectl apply -k k8s/overlays/dev` and verifies health based on workload type:
   * **Database Migrations (`db-migrations`):** Deletes the previous immutable Kubernetes `Job` before applying the new manifest, then waits for `condition=complete` (120s timeout).
   * **Applications (`backend` / `frontend`):** Applies the rolling update and monitors `kubectl rollout status` (90s timeout).
4. **GitOps Commit (On Success):** Commits and pushes the updated `k8s/overlays/dev/kustomization.yaml` back to `main` as `github-actions[bot]`.
5. **Diagnostics & Recovery (On Failure):** Captures live cluster diagnostics before executing rollback logic and discarding uncommitted manifest changes.

---

## Reliability & Failure Handling

### 1. Automated Failure Diagnostics (`$GITHUB_STEP_SUMMARY`)
If a rollout or migration job fails or times out, a diagnostic step runs **before** any rollback so pod state and logs are preserved. It writes a formatted Markdown report directly to the GitHub Actions run summary containing:
* Current Pod status (`kubectl get pods`)
* Last 25 namespace events (`kubectl get events`)
* Last 100 lines of container or job logs (`kubectl logs`)
* Full workload description for probe and mount inspection (`kubectl describe`)

### 2. Application Rollbacks vs. Database Fix-Forward
* **Stateless Apps (`backend`, `frontend`):** Automatically reverts the cluster rollback and verifies rollback stability
* **Stateful Migrations (`db-migrations`):** Enforces a strict **fix-forward** policy. Automated database rollbacks are disabled to prevent destructive schema drops or live data loss; failed jobs halt the pipeline and surface SQL errors in the step summary for manual remediation.

---

## Prerequisites

To run this workflow successfully against a Dev Kubernetes cluster, ensure the following are configured:
* A `dev` GitHub Environment configured in the calling repository (`my-app-code`).
* A GitHub App installed with **Contents (Read & Write)** permission scoped strictly to `platform-ci-cd`.
* Cluster access configured for `kubectl` targeting the `dev` namespace.
* `k8s/overlays/dev/kustomization.yaml` referencing all managed base resources (`backend`, `frontend`, `db-migrations`).
