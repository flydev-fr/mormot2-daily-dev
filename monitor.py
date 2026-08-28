import urllib.request
import json
import datetime
import os
import sys

def fetch_commits():
    # Fetch commits from yesterday to today
    yesterday_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    # properly format for GitHub API (ISO 8601 YYYY-MM-DDTHH:MM:SSZ)
    yesterday = yesterday_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = f"https://api.github.com/repos/synopse/mORMot2/commits?since={yesterday}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mormot2-monitor-dev"
    }

    # Use github token if available
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error fetching commits: {e}")
        return []

def main():
    print("Fetching commits...")
    commits = fetch_commits()
    if not commits:
        print("No commits found or error occurred.")
        return

    commit_messages = [commit['commit']['message'] for commit in commits]

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        print("Warning: OPENAI_API_KEY environment variable not found.")
        print("Outputting raw commit messages:")
        for msg in commit_messages:
            print(f"- {msg.splitlines()[0]}")
        return

    print("OPENAI_API_KEY found, analyzing commits...")
    try:
        # We will use PROMPT.md content
        with open("PROMPT.md", "r") as f:
            system_prompt = f.read()
    except Exception as e:
        print(f"Warning: Could not read PROMPT.md ({e}). Using default prompt.")
        system_prompt = "Review official mORMot2 commits and summarize what changed, explain the likely impact on an existing Delphi backend."

    # Call OpenAI API
    try:
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here are the recent commits:\n\n" + "\n".join(commit_messages)}
            ]
        }

        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(data).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_key}"
            }
        )

        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            print("\nAnalysis Result:")
            print(result['choices'][0]['message']['content'])

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")

if __name__ == "__main__":
    main()
