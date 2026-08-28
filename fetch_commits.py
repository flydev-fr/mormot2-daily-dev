import urllib.request
import json
import datetime
import os

def fetch_commits():
    yesterday_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    yesterday = yesterday_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = f"https://api.github.com/repos/synopse/mORMot2/commits?since={yesterday}&per_page=100"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mormot2-monitor-dev"
    }

    # Use github token if available to prevent rate limiting
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
    commits = fetch_commits()
    if not commits:
        print("No commits found or error occurred.")

    # Save the raw JSON payload to a file
    with open("commits.json", "w") as f:
        json.dump(commits, f, indent=4)

    print(f"Successfully fetched {len(commits)} commits and saved to commits.json.")

if __name__ == "__main__":
    main()
