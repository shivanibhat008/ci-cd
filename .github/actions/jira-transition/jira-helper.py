import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request


def jira_request(method, url, auth_header, payload=None):
    headers = {
        "Authorization": f"Basic {auth_header}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"Jira API Error ({e.code}) on {url}: {error_body}", file=sys.stderr)
        sys.exit(1)


def set_github_output(name, value):
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main():
    base_url = os.environ["JIRA_BASE_URL"].rstrip("/")
    email = os.environ["JIRA_EMAIL"]
    token = os.environ["JIRA_TOKEN"]
    source_text = os.environ["SOURCE_TEXT"]
    target_status = os.environ.get("TARGET_STATUS", "").strip()

    # 1. Extract Jira Issue Key
    match = re.search(r"[A-Z][A-Z0-9]+-[0-9]+", source_text)
    if not match:
        print(f"Error: No Jira issue key found in: {source_text}", file=sys.stderr)
        sys.exit(1)

    issue_key = match.group(0)
    print(f"Found Jira issue key: {issue_key}")
    set_github_output("key", issue_key)

    # Prepare Basic Auth Header
    raw_auth = f"{email}:{token}".encode("utf-8")
    auth_header = base64.b64encode(raw_auth).decode("utf-8")

    # 2. Fetch Fix Version
    issue_url = f"{base_url}/rest/api/3/issue/{issue_key}?fields=fixVersions"
    issue_data = jira_request("GET", issue_url, auth_header)
    fix_versions = issue_data.get("fields", {}).get("fixVersions", [])

    fix_version = fix_versions[0].get("name", "") if fix_versions else ""
    if fix_version:
        print(f"Fetched Fix Version: {fix_version}")
    else:
        print(f"Warning: No Fix Version set on {issue_key}.")
    set_github_output("fix-version", fix_version)

    # 3. Transition Jira Issue (if target-status is provided)
    if not target_status:
        return

    transitions_url = f"{base_url}/rest/api/3/issue/{issue_key}/transitions"
    transitions_data = jira_request("GET", transitions_url, auth_header)
    transitions = transitions_data.get("transitions", [])

    matched_id = next(
        (
            t["id"]
            for t in transitions
            if t.get("to", {}).get("name", "").lower() == target_status.lower()
        ),
        None,
    )

    if not matched_id:
        print(
            f"Error: Target status '{target_status}' is not a valid transition for {issue_key}.",
            file=sys.stderr,
        )
        print("Available transitions:", file=sys.stderr)
        for t in transitions:
            print(f"- {t['to']['name']} (ID: {t['id']})", file=sys.stderr)
        sys.exit(1)

    jira_request(
        "POST",
        transitions_url,
        auth_header,
        payload={"transition": {"id": matched_id}},
    )
    print(f"Successfully moved {issue_key} to '{target_status}'.")


if __name__ == "__main__":
    main()
