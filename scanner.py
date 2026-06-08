import pandas as pd
import random
import time
import json
import os
import re
import requests
import traceback
import subprocess
from datetime import datetime

SAVE_FILE = "frog_projects.json"
RESULTS_DIR = "results"
STATE_FILE = "scanner_state.json"
LIVE_FILE = os.path.join(RESULTS_DIR, "scanner_live.json")

MIN_DELAY_SECONDS = 25
MAX_DELAY_SECONDS = 30

MULTILINE_MIN_DELAY = 5
MULTILINE_MAX_DELAY = 10

BETWEEN_KEYWORDS_MIN = 25
BETWEEN_KEYWORDS_MAX = 30

MAX_429_RETRIES = 3

KEYWORDS_PER_PROJECT_PER_ROUND = 10

PROJECT_COOLDOWN_SECONDS = 300

REQUEST_TIMEOUT_SECONDS = 20


def ensure_dirs():
    os.makedirs(RESULTS_DIR, exist_ok=True)


def now():
    return time.strftime("%H:%M:%S")


def now_stamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_github_actions():
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def clean_keyword(k):
    k = str(k or "").strip()
    k = re.sub(r"\s+", " ", k)
    return k


def make_safe_filename(text):
    text = str(text or "project").strip()
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "project"


def make_hashtag(keyword):
    tag = re.sub(r"[^a-zA-Z0-9]", "", str(keyword).replace(" ", ""))
    return f"#{tag}" if tag else ""


def load_projects():
    if not os.path.exists(SAVE_FILE):
        print(f"{now()} | ERROR: Missing {SAVE_FILE}")
        return {}

    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"{now()} | ERROR loading projects: {e}")
        return {}


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def save_live_status(data):
    ensure_dirs()

    data["last_updated"] = now_stamp()

    with open(LIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def git_commit_live_update(message):
    if not is_github_actions():
        return

    try:
        subprocess.run(["git", "config", "user.name", "frog-scanner"], check=False)
        subprocess.run(["git", "config", "user.email", "frog-scanner@users.noreply.github.com"], check=False)

        subprocess.run(["git", "add", RESULTS_DIR], check=False)

        if os.path.exists(STATE_FILE):
            subprocess.run(["git", "add", STATE_FILE], check=False)

        commit = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True
        )

        if commit.returncode != 0:
            print(f"{now()} | Git commit skipped: {commit.stdout.strip()} {commit.stderr.strip()}")
            return

        push = subprocess.run(
            ["git", "push"],
            capture_output=True,
            text=True
        )

        print(f"{now()} | Git push: {push.stdout.strip()} {push.stderr.strip()}")

    except Exception as e:
        print(f"{now()} | Git live update failed: {repr(e)}")


def project_result_json(project):
    return os.path.join(RESULTS_DIR, f"{make_safe_filename(project)}_results.json")


def project_result_csv(project):
    return os.path.join(RESULTS_DIR, f"{make_safe_filename(project)}_results.csv")


def project_summary_json(project):
    return os.path.join(RESULTS_DIR, f"{make_safe_filename(project)}_summary.json")


def load_project_results(project):
    path = project_result_json(project)

    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_project_results(project, results):
    json_path = project_result_json(project)
    csv_path = project_result_csv(project)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    if results:
        df = pd.DataFrame(results)
        df.to_csv(csv_path, index=False, encoding="utf-8")


def get_usable_sorted(results):
    usable = [
        r for r in results
        if float(r.get("Latest", 0) or 0) > 0
        or float(r.get("Recent Avg", 0) or 0) > 0
        or float(r.get("Viral Score", 0) or 0) > 0
    ]

    return sorted(
        usable,
        key=lambda x: (
            float(x.get("Latest", 0) or 0),
            float(x.get("Recent Avg", 0) or 0),
            float(x.get("Rise %", 0) or 0),
            float(x.get("Viral Score", 0) or 0),
        ),
        reverse=True
    )


def save_project_summary(project, results, scanned_this_round, status):
    usable_sorted = get_usable_sorted(results)

    top_keywords = usable_sorted[:50]

    hashtags = " ".join(
        tag for tag in [make_hashtag(r.get("Keyword", "")) for r in top_keywords]
        if tag
    )

    summary = {
        "project": project,
        "last_scanned": now_stamp(),
        "status": status,
        "total_results": len(results),
        "usable_results": len(usable_sorted),
        "scanned_this_round": scanned_this_round,
        "top_10": usable_sorted[:10],
        "hashtags_top_50": hashtags,
        "results_json": project_result_json(project),
        "results_csv": project_result_csv(project),
    }

    with open(project_summary_json(project), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def no_data_result(keyword="UNKNOWN", reason="NO DATA", stage="UNKNOWN"):
    return {
        "Keyword": keyword,
        "Latest": 0,
        "Recent Avg": 0,
        "Previous Avg": 0,
        "Rise %": 0,
        "Demand": 0,
        "Viral Score": 0,
        "Min": 0,
        "Max": 0,
        "Volatility": 0,
        "Trend": "🐸➡️ NO DATA",
        "Hook": "",
        "Caption": "",
        "CTA": "",
        "Status": "NO DATA",
        "Raw Status": f"❌ {reason}",
        "Priority": "❌ IGNORE",
        "Debug Stage": stage,
        "Debug Reason": reason,
        "HTTP Explore": "",
        "HTTP Multiline": "",
        "Timeline Points": 0,
        "Value Count": 0,
        "First Values": "",
        "Last Values": "",
        "Scanned At": now_stamp(),
    }


def analyse(keyword, values):
    values = [float(v) for v in values if v is not None]

    if len(values) < 2:
        return no_data_result(keyword, "TOO FEW VALUES", "ANALYSE")

    series = pd.Series(values)

    if series.sum() <= 0:
        return no_data_result(keyword, "ZERO SEARCH DATA", "ANALYSE")

    recent = series.tail(7)
    previous = series.tail(14).head(7)

    latest = float(recent.iloc[-1]) if len(recent) else float(series.iloc[-1])
    recent_avg = float(recent.mean()) if len(recent) else 0
    previous_avg = float(previous.mean()) if len(previous) else 0

    rise = 0 if previous_avg == 0 else ((recent_avg - previous_avg) / previous_avg) * 100
    demand = (latest * 0.6) + (recent_avg * 0.4)
    viral = max(0, min(100, rise))

    if rise >= 80 and demand >= 10:
        priority = "🔥 POST NOW"
        status = "VIRAL"
        raw_status = "🐸 VIRAL"
    elif rise >= 50 and demand >= 10:
        priority = "📌 POST TODAY"
        status = "HIGH"
        raw_status = "🐸 HIGH"
    elif rise >= 20 and demand >= 10:
        priority = "🧊 POST SOMETHING"
        status = "MEDIUM"
        raw_status = "🐸 MEDIUM"
    elif demand >= 40:
        priority = "💰 STABLE HIGH DEMAND"
        status = "COMMERCIAL"
        raw_status = "🐸 COMMERCIAL"
    elif demand >= 10:
        priority = "📊 TEST"
        status = "LOW"
        raw_status = "🐸 LOW"
    else:
        priority = "❌ IGNORE"
        status = "LOW"
        raw_status = "❌ LOW VALUE"

    direction = (
        "🐸📈 RISING" if rise > 10 else
        "🐸📉 FALLING" if rise < -10 else
        "🐸➡️ STABLE"
    )

    return {
        "Keyword": keyword,
        "Latest": round(latest, 1),
        "Recent Avg": round(recent_avg, 1),
        "Previous Avg": round(previous_avg, 1),
        "Rise %": round(rise, 1),
        "Demand": round(demand, 1),
        "Viral Score": round(viral, 1),
        "Min": round(float(series.min()), 1),
        "Max": round(float(series.max()), 1),
        "Volatility": round(float(series.std()), 2),
        "Trend": direction,
        "Status": status,
        "Raw Status": raw_status,
        "Priority": priority,
        "Debug Stage": "SUCCESS",
        "Debug Reason": "OK",
        "HTTP Explore": "",
        "HTTP Multiline": "",
        "Timeline Points": 0,
        "Value Count": len(values),
        "First Values": ", ".join(str(int(x)) for x in values[:8]),
        "Last Values": ", ".join(str(int(x)) for x in values[-8:]),
        "Scanned At": now_stamp(),
    }


def ai_hook(keyword, data):
    score = data.get("Viral Score", 0)
    demand = data.get("Demand", 0)

    if score > 75 and demand >= 10:
        hook = f"This just spiked in {keyword}"
        caption = f"We’re seeing a sharp increase in {keyword} demand with strong buyer activity."
        cta = f"Capture {keyword} demand before competitors"
    elif score > 55 and demand >= 10:
        hook = f"High intent {keyword} buyers active now"
        caption = f"{keyword} shows strong conversion potential with consistent demand."
        cta = f"Generate {keyword} enquiries today"
    elif score > 30 and demand >= 10:
        hook = f"{keyword} interest is growing"
        caption = f"{keyword} is showing early-stage demand worth testing."
        cta = f"Test {keyword} ads now"
    else:
        hook = f"Low demand in {keyword}"
        caption = f"{keyword} shows weak or limited activity."
        cta = f"Monitor {keyword} only"

    return {
        "Hook": hook,
        "Caption": caption,
        "CTA": cta,
    }


def parse_google_json(text, stage):
    start = text.find("{")

    if start == -1:
        raise Exception(f"{stage}: no JSON object found. First 300 chars: {repr(text[:300])}")

    return json.loads(text[start:])


def make_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0 Safari/537.36"
        )
    }


def build_no_data_with_ai(keyword, reason, stage, result_meta):
    result = no_data_result(keyword, reason, stage)
    result.update(result_meta)
    result.update(ai_hook(keyword, result))
    return result


def google_trends_fetch(keyword, live_update=None):
    keyword = clean_keyword(keyword)

    def heartbeat(stage):
        print(f"{now()} | [{keyword}] HEARTBEAT: {stage}")
        if live_update:
            live_update(stage)

    result_meta = {
        "HTTP Explore": "",
        "HTTP Multiline": "",
        "Timeline Points": 0,
        "Value Count": 0,
        "First Values": "",
        "Last Values": "",
    }

    payload = {
        "comparisonItem": [
            {
                "keyword": keyword,
                "geo": "GB",
                "time": "today 3-m"
            }
        ],
        "category": 0,
        "property": ""
    }

    print(f"{now()} | [{keyword}] START")

    try:
        wait = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        heartbeat(f"sleeping before explore for {round(wait, 1)}s")
        time.sleep(wait)

        explore_retry = 0

        while True:
            heartbeat("sending explore request")

            try:
                r = requests.get(
                    "https://trends.google.com/trends/api/explore",
                    params={
                        "hl": "en-GB",
                        "tz": "0",
                        "req": json.dumps(payload)
                    },
                    headers=make_headers(),
                    timeout=REQUEST_TIMEOUT_SECONDS
                )
            except requests.exceptions.Timeout as e:
                heartbeat(f"explore request timed out after {REQUEST_TIMEOUT_SECONDS}s")
                return build_no_data_with_ai(
                    keyword,
                    f"EXPLORE TIMEOUT {repr(e)}",
                    "EXPLORE_TIMEOUT",
                    result_meta
                )
            except requests.exceptions.RequestException as e:
                heartbeat(f"explore request failed {repr(e)}")
                return build_no_data_with_ai(
                    keyword,
                    f"EXPLORE REQUEST FAILED {repr(e)}",
                    "EXPLORE_REQUEST",
                    result_meta
                )

            result_meta["HTTP Explore"] = str(r.status_code)

            print(f"{now()} | [{keyword}] Explore status {r.status_code}")

            if r.status_code == 429:
                explore_retry += 1
                heartbeat(f"explore 429 retry {explore_retry}/{MAX_429_RETRIES}")

                if explore_retry > MAX_429_RETRIES:
                    heartbeat("explore 429 retries exhausted")
                    return build_no_data_with_ai(
                        keyword,
                        "EXPLORE 429 RATE LIMITED",
                        "EXPLORE",
                        result_meta
                    )

                cooldown = random.uniform(240, 600)
                heartbeat(f"explore 429 cooldown for {round(cooldown, 1)}s")
                time.sleep(cooldown)
                continue

            if r.status_code != 200:
                heartbeat(f"explore bad status {r.status_code}")
                return build_no_data_with_ai(
                    keyword,
                    f"EXPLORE BAD STATUS {r.status_code}",
                    "EXPLORE",
                    result_meta
                )

            break

        heartbeat("parsing explore response")

        explore = parse_google_json(r.text, "EXPLORE")

        widgets = explore.get("widgets", [])

        timeseries_widget = next(
            (w for w in widgets if w.get("id") == "TIMESERIES"),
            None
        )

        if not timeseries_widget:
            heartbeat("no timeseries widget")
            return build_no_data_with_ai(
                keyword,
                "NO TIMESERIES WIDGET",
                "EXPLORE",
                result_meta
            )

        token = timeseries_widget.get("token")
        request_obj = timeseries_widget.get("request")

        if not token or not request_obj:
            heartbeat("missing token or request")
            return build_no_data_with_ai(
                keyword,
                "MISSING TOKEN OR REQUEST",
                "EXPLORE",
                result_meta
            )

        extra_wait = random.uniform(MULTILINE_MIN_DELAY, MULTILINE_MAX_DELAY)
        heartbeat(f"sleeping before multiline for {round(extra_wait, 1)}s")
        time.sleep(extra_wait)

        multiline_retry = 0

        while True:
            heartbeat("sending multiline request")

            try:
                r2 = requests.get(
                    "https://trends.google.com/trends/api/widgetdata/multiline",
                    params={
                        "hl": "en-GB",
                        "tz": "0",
                        "req": json.dumps(request_obj),
                        "token": token
                    },
                    headers=make_headers(),
                    timeout=REQUEST_TIMEOUT_SECONDS
                )
            except requests.exceptions.Timeout as e:
                heartbeat(f"multiline request timed out after {REQUEST_TIMEOUT_SECONDS}s")
                return build_no_data_with_ai(
                    keyword,
                    f"MULTILINE TIMEOUT {repr(e)}",
                    "MULTILINE_TIMEOUT",
                    result_meta
                )
            except requests.exceptions.RequestException as e:
                heartbeat(f"multiline request failed {repr(e)}")
                return build_no_data_with_ai(
                    keyword,
                    f"MULTILINE REQUEST FAILED {repr(e)}",
                    "MULTILINE_REQUEST",
                    result_meta
                )

            result_meta["HTTP Multiline"] = str(r2.status_code)

            print(f"{now()} | [{keyword}] Multiline status {r2.status_code}")

            if r2.status_code == 429:
                multiline_retry += 1
                heartbeat(f"multiline 429 retry {multiline_retry}/{MAX_429_RETRIES}")

                if multiline_retry > MAX_429_RETRIES:
                    heartbeat("multiline 429 retries exhausted")
                    return build_no_data_with_ai(
                        keyword,
                        "MULTILINE 429 RATE LIMITED",
                        "MULTILINE",
                        result_meta
                    )

                cooldown = random.uniform(240, 600)
                heartbeat(f"multiline 429 cooldown for {round(cooldown, 1)}s")
                time.sleep(cooldown)
                continue

            if r2.status_code != 200:
                heartbeat(f"multiline bad status {r2.status_code}")
                return build_no_data_with_ai(
                    keyword,
                    f"MULTILINE BAD STATUS {r2.status_code}",
                    "MULTILINE",
                    result_meta
                )

            break

        heartbeat("parsing multiline response")

        trend_data = parse_google_json(r2.text, "MULTILINE")

        timeline = trend_data.get("default", {}).get("timelineData", [])

        result_meta["Timeline Points"] = len(timeline)

        if not timeline:
            heartbeat("empty timeline no search data")
            return build_no_data_with_ai(
                keyword,
                "NO SEARCH DATA EMPTY TIMELINE",
                "MULTILINE",
                result_meta
            )

        values = []

        for row in timeline:
            value = row.get("value")
            if isinstance(value, list) and value:
                values.append(float(value[0]))

        result_meta["Value Count"] = len(values)
        result_meta["First Values"] = ", ".join(str(int(x)) for x in values[:8])
        result_meta["Last Values"] = ", ".join(str(int(x)) for x in values[-8:])

        heartbeat("analysing values")

        analysed = analyse(keyword, values)
        analysed.update(result_meta)
        analysed.update(ai_hook(keyword, analysed))

        print(
            f"{now()} | [{keyword}] SUCCESS Latest={analysed['Latest']} Recent={analysed['Recent Avg']} Rise={analysed['Rise %']}"
        )

        heartbeat("keyword completed successfully")

        return analysed

    except Exception as e:
        print(f"{now()} | [{keyword}] ERROR {repr(e)}")
        print(traceback.format_exc())

        heartbeat(f"request failed / timed out: {repr(e)}")

        return build_no_data_with_ai(
            keyword,
            repr(e),
            "EXCEPTION",
            result_meta
        )


def pick_keywords_for_project(project, keywords, existing_results, state):
    done_keywords = {
        clean_keyword(r.get("Keyword", ""))
        for r in existing_results
        if clean_keyword(r.get("Keyword", ""))
    }

    clean_keywords = [
        clean_keyword(k)
        for k in keywords
        if clean_keyword(k)
    ]

    remaining = [
        k for k in clean_keywords
        if k not in done_keywords
    ]

    if not remaining:
        print(f"{now()} | [{project}] All keywords already scanned. Restarting project cycle.")
        existing_results.clear()
        remaining = clean_keywords

    return remaining[:KEYWORDS_PER_PROJECT_PER_ROUND]


def scan_project(project, keywords, state, global_counter):
    print("=" * 90)
    print(f"{now()} | PROJECT START: {project}")

    results = load_project_results(project)
    to_scan = pick_keywords_for_project(project, keywords, results, state)

    print(f"{now()} | [{project}] Existing results: {len(results)}")
    print(f"{now()} | [{project}] Scanning this round: {len(to_scan)}")

    scanned_this_round = 0
    status = "OK"

    save_live_status({
        "status": "running",
        "current_project": project,
        "current_keyword": "",
        "last_completed_project": "",
        "last_completed_keyword": "",
        "project_existing_results": len(results),
        "project_scanning_this_round": len(to_scan),
        "project_scanned_this_round": 0,
        "total_scanned_this_run": global_counter["total"],
        "message": f"Starting project {project}",
    })

    git_commit_live_update(f"live start {make_safe_filename(project)}")

    for index, keyword in enumerate(to_scan, start=1):
        print(f"{now()} | [{project}] Keyword {index}/{len(to_scan)}: {keyword}")

        def live_update(stage):
            save_live_status({
                "status": "running",
                "current_project": project,
                "current_keyword": keyword,
                "last_completed_project": "",
                "last_completed_keyword": "",
                "project_existing_results": len(results),
                "project_scanning_this_round": len(to_scan),
                "project_scanned_this_round": scanned_this_round,
                "total_scanned_this_run": global_counter["total"],
                "message": f"{stage}: {keyword}",
            })

            git_commit_live_update(
                f"heartbeat {make_safe_filename(project)} {make_safe_filename(keyword)}"
            )

        save_live_status({
            "status": "running",
            "current_project": project,
            "current_keyword": keyword,
            "last_completed_project": "",
            "last_completed_keyword": "",
            "project_existing_results": len(results),
            "project_scanning_this_round": len(to_scan),
            "project_scanned_this_round": scanned_this_round,
            "total_scanned_this_run": global_counter["total"],
            "message": f"Queued {keyword}",
        })

        git_commit_live_update(f"live queued {make_safe_filename(project)} {make_safe_filename(keyword)}")

        result = google_trends_fetch(keyword, live_update=live_update)

        results = [
            r for r in results
            if clean_keyword(r.get("Keyword", "")) != clean_keyword(keyword)
        ]

        results.append(result)

        save_project_results(project, results)

        scanned_this_round += 1
        global_counter["total"] += 1

        save_project_summary(project, results, scanned_this_round, status)

        usable_sorted = get_usable_sorted(results)

        save_live_status({
            "status": "running",
            "current_project": project,
            "current_keyword": "",
            "last_completed_project": project,
            "last_completed_keyword": keyword,
            "last_completed_status": result.get("Status", ""),
            "last_completed_latest": result.get("Latest", 0),
            "last_completed_rise": result.get("Rise %", 0),
            "project_existing_results": len(results),
            "project_scanning_this_round": len(to_scan),
            "project_scanned_this_round": scanned_this_round,
            "total_scanned_this_run": global_counter["total"],
            "top_5_this_project": usable_sorted[:5],
            "message": f"Completed {keyword}",
        })

        git_commit_live_update(f"live completed {make_safe_filename(project)} {make_safe_filename(keyword)}")

        if result.get("HTTP Explore") == "429" or result.get("HTTP Multiline") == "429":
            status = "429 COOLDOWN"
            print(f"{now()} | [{project}] 429 hit. Ending project round early.")
            break

        if index < len(to_scan):
            wait = random.uniform(BETWEEN_KEYWORDS_MIN, BETWEEN_KEYWORDS_MAX)

            save_live_status({
                "status": "running",
                "current_project": project,
                "current_keyword": "",
                "last_completed_project": project,
                "last_completed_keyword": keyword,
                "project_existing_results": len(results),
                "project_scanning_this_round": len(to_scan),
                "project_scanned_this_round": scanned_this_round,
                "total_scanned_this_run": global_counter["total"],
                "message": f"Between keyword sleep {round(wait, 1)}s",
            })

            git_commit_live_update(f"live between keywords {make_safe_filename(project)}")

            print(f"{now()} | [{project}] Between keyword sleep {round(wait, 1)}s")
            time.sleep(wait)

    save_project_results(project, results)
    save_project_summary(project, results, scanned_this_round, status)

    state[project] = {
        "last_scanned": now_stamp(),
        "status": status,
        "results": len(results),
        "scanned_this_round": scanned_this_round,
    }

    save_state(state)

    save_live_status({
        "status": status,
        "current_project": "",
        "current_keyword": "",
        "last_completed_project": project,
        "last_completed_keyword": "",
        "project_existing_results": len(results),
        "project_scanning_this_round": len(to_scan),
        "project_scanned_this_round": scanned_this_round,
        "total_scanned_this_run": global_counter["total"],
        "message": f"Finished project {project}",
    })

    git_commit_live_update(f"live finished {make_safe_filename(project)}")

    print(f"{now()} | PROJECT END: {project} | {status}")


def main():
    ensure_dirs()

    print("=" * 90)
    print(f"{now()} | FROG SCANNER STARTED")
    print(f"{now()} | ONE PROJECT ONLY MODE")
    print(f"{now()} | Reading projects from {SAVE_FILE}")
    print(f"{now()} | Saving results into {RESULTS_DIR}/")
    print("=" * 90)

    projects = load_projects()
    state = load_state()

    global_counter = {"total": 0}

    save_live_status({
        "status": "starting",
        "current_project": "",
        "current_keyword": "",
        "last_completed_project": "",
        "last_completed_keyword": "",
        "total_scanned_this_run": 0,
        "message": "Scanner starting in ONE PROJECT ONLY mode",
    })

    git_commit_live_update("live scanner starting")

    if not projects:
        print(f"{now()} | No projects found. Exiting.")
        save_live_status({
            "status": "no_projects",
            "current_project": "",
            "current_keyword": "",
            "last_completed_project": "",
            "last_completed_keyword": "",
            "total_scanned_this_run": 0,
            "message": "No projects found",
        })
        git_commit_live_update("live no projects")
        return

    first_project = list(projects.keys())[0]
    keywords = projects[first_project]

    print(f"{now()} | FIRST PROJECT SELECTED: {first_project}")

    if not isinstance(keywords, list):
        print(f"{now()} | First project keywords not a list. Exiting.")
        save_live_status({
            "status": "error",
            "current_project": first_project,
            "current_keyword": "",
            "last_completed_project": "",
            "last_completed_keyword": "",
            "total_scanned_this_run": 0,
            "message": f"First project {first_project} keywords are not a list",
        })
        git_commit_live_update("live first project error")
        return

    try:
        scan_project(first_project, keywords, state, global_counter)
    except Exception as e:
        print(f"{now()} | PROJECT ERROR {first_project}: {repr(e)}")
        print(traceback.format_exc())

        state[first_project] = {
            "last_scanned": now_stamp(),
            "status": f"ERROR {repr(e)}",
        }

        save_state(state)

        save_live_status({
            "status": "error",
            "current_project": first_project,
            "current_keyword": "",
            "last_completed_project": "",
            "last_completed_keyword": "",
            "total_scanned_this_run": global_counter["total"],
            "message": f"Project error {first_project}: {repr(e)}",
        })

        git_commit_live_update(f"live error {make_safe_filename(first_project)}")
        return

    save_live_status({
        "status": "finished",
        "current_project": "",
        "current_keyword": "",
        "last_completed_project": first_project,
        "last_completed_keyword": "",
        "total_scanned_this_run": global_counter["total"],
        "message": f"Finished first project only: {first_project}",
    })

    git_commit_live_update("live scanner finished first project only")

    print(f"{now()} | Finished first project only: {first_project}")


if __name__ == "__main__":
    main()
