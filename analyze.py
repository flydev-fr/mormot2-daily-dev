import urllib.request
import json
import datetime
import os
import html
import re

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

def analyze_commit_heuristics(commit_messages):
    categories = {
        "Core/System": [],
        "Network/SOA": [],
        "ORM/Database": [],
        "Cryptography": [],
        "Tests/Misc": []
    }

    impacts = []

    for msg in commit_messages:
        first_line = msg.splitlines()[0].lower()
        full_msg = msg.lower()

        # Categorization
        if first_line.startswith("core:") or first_line.startswith("lib:") or first_line.startswith("all:"):
            categories["Core/System"].append(msg.splitlines()[0])
        elif first_line.startswith("net:") or first_line.startswith("soa:") or "http" in first_line:
            categories["Network/SOA"].append(msg.splitlines()[0])
        elif first_line.startswith("orm:") or first_line.startswith("sql:") or first_line.startswith("db:"):
            categories["ORM/Database"].append(msg.splitlines()[0])
        elif first_line.startswith("crypt:") or "random" in first_line:
            categories["Cryptography"].append(msg.splitlines()[0])
        else:
            categories["Tests/Misc"].append(msg.splitlines()[0])

        # Impact detection
        if re.search(r'\b(break|breaking|remove|removed|invalid|misleading)\b', full_msg):
            impacts.append(f"<strong>Potential Breaking Change / Removal:</strong> {html.escape(msg.splitlines()[0])}")

        if re.search(r'\b(leak|memory leak|corruption|race condition)\b', full_msg):
            impacts.append(f"<strong>Stability / Memory Fix:</strong> {html.escape(msg.splitlines()[0])}")

        if re.search(r'\b(lock|lockless|thread|synchronization)\b', full_msg):
            impacts.append(f"<strong>Concurrency / Threading Update:</strong> {html.escape(msg.splitlines()[0])}")

    html_output = ""

    if impacts:
        html_output += "<h3>High-Impact Changes Detected</h3><ul>"
        for impact in impacts:
            html_output += f"<li>{impact}</li>"
        html_output += "</ul>"
    else:
        html_output += "<p>No high-impact or breaking changes were automatically detected in today's commits.</p>"

    html_output += "<h3>Changes by Category</h3>"
    for cat, msgs in categories.items():
        if msgs:
            html_output += f"<h4>{cat}</h4><ul>"
            for m in msgs:
                html_output += f"<li>{html.escape(m)}</li>"
            html_output += "</ul>"

    return html_output

def generate_empty_report():
    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w") as f:
        f.write("<!DOCTYPE html>\n")
        f.write("<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n<title>mORMot2 Daily Commit Analysis Report</title>\n")
        f.write("<style>body { font-family: sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #333;} h1, h2, h3, h4 { color: #2c3e50; } li { margin-bottom: 5px; } .commit-list { background: #f4f4f4; padding: 15px; border-radius: 5px; max-height: 300px; overflow-y: auto; }</style>\n")
        f.write("</head>\n<body>\n")
        f.write("<h1>mORMot2 Daily Commit Analysis Report</h1>\n")
        f.write(f"<p><strong>Generated on:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>\n")
        f.write("<h2>No Commits Found</h2>\n")
        f.write("<p>There were no commits found in the last 24 hours.</p>\n")
        f.write("</body>\n</html>\n")

def analyze_commits():
    commits = fetch_commits()
    if not commits:
        print("No commits found or error occurred. Generating empty report.")
        generate_empty_report()
        return

    commit_messages = [commit['commit']['message'] for commit in commits]
    analysis_html = analyze_commit_heuristics(commit_messages)

    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w") as f:
        f.write("<!DOCTYPE html>\n")
        f.write("<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n<title>mORMot2 Daily Commit Analysis Report</title>\n")
        f.write("<style>body { font-family: sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #333;} h1, h2, h3, h4 { color: #2c3e50; } li { margin-bottom: 5px; } .commit-list { background: #f4f4f4; padding: 15px; border-radius: 5px; max-height: 300px; overflow-y: auto; }</style>\n")
        f.write("</head>\n<body>\n")
        f.write("<h1>mORMot2 Daily Commit Analysis Report</h1>\n")

        f.write(f"<p><strong>Generated on:</strong> {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>\n")

        f.write("<h2>Summary of Impact (Heuristic Analysis)</h2>\n")
        f.write(analysis_html + "\n")

        f.write("<h2>Raw Commits (Last 24 Hours)</h2>\n")
        f.write("<ul class=\"commit-list\">\n")
        for msg in commit_messages:
            first_line = msg.splitlines()[0]
            escaped_line = html.escape(first_line)
            f.write(f"<li>{escaped_line}</li>\n")
        f.write("</ul>\n")

        f.write("</body>\n</html>\n")

    print("Analysis complete. Saved to public/index.html")

if __name__ == "__main__":
    analyze_commits()
