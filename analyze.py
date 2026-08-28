import urllib.request
import json
import datetime
import os
import html

def fetch_commits():
    yesterday_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    yesterday = yesterday_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    url = f"https://api.github.com/repos/synopse/mORMot2/commits?since={yesterday}"

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "mormot2-monitor-dev"
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"Error fetching commits: {e}")
        return []

def get_analysis_from_openai(commit_messages):
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        return "<p><em>Warning: OPENAI_API_KEY environment variable not found. Semantic analysis skipped.</em></p>"

    try:
        try:
            with open("PROMPT.md", "r") as f:
                system_prompt = f.read()
        except:
            system_prompt = "Review official mORMot2 commits and summarize what changed, explain the likely impact on an existing Delphi backend."

        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here are the recent commits. Format the response in HTML fragments (e.g., <h3>, <p>, <ul>), do not wrap in a full document or markdown code block:\n\n" + "\n".join(commit_messages)}
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
            content = result['choices'][0]['message']['content']
            # Clean up markdown formatting if the model still uses it
            content = content.replace("```html", "").replace("```", "").strip()
            return content
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return f"<p><em>Error during analysis: {e}</em></p>"

def analyze_commits():
    commits = fetch_commits()
    if not commits:
        print("No commits found or error occurred.")
        return

    commit_messages = [commit['commit']['message'] for commit in commits]
    analysis_html = get_analysis_from_openai(commit_messages)

    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w") as f:
        f.write("<!DOCTYPE html>\n")
        f.write("<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n<title>mORMot2 Daily Commit Analysis Report</title>\n")
        f.write("<style>body { font-family: sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; } h1, h2, h3 { color: #333; } li { margin-bottom: 5px; } .commit-list { background: #f4f4f4; padding: 15px; border-radius: 5px; max-height: 300px; overflow-y: auto; }</style>\n")
        f.write("</head>\n<body>\n")
        f.write("<h1>mORMot2 Daily Commit Analysis Report</h1>\n")

        f.write(f"<p><strong>Generated on:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>\n")

        f.write("<h2>Summary of Impact</h2>\n")
        f.write(analysis_html + "\n")

        f.write("<h2>Raw Commits (Last 24 Hours)</h2>\n")
        f.write("<ul class=\"commit-list\">\n")
        for msg in commit_messages:
            first_line = msg.splitlines()[0]
            # Escape HTML characters in commit messages to prevent issues
            escaped_line = html.escape(first_line)
            f.write(f"<li>{escaped_line}</li>\n")
        f.write("</ul>\n")

        f.write("</body>\n</html>\n")

    print("Analysis complete. Saved to public/index.html")

if __name__ == "__main__":
    analyze_commits()
