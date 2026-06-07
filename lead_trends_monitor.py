import streamlit as st
import pandas as pd
import random
import time
import json
import os
import re
import requests
import traceback
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="🐸 Frog Dashboard 🐸", layout="wide")

SAVE_FILE = "frog_projects.json"
RESULTS_DIR = "results"


def load_projects():
    try:
        if os.path.exists(SAVE_FILE):
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception:
        return {}


def save_projects():
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state.projects, f, indent=2)


if "projects" not in st.session_state:
    st.session_state.projects = load_projects()

if "active_project" not in st.session_state:
    st.session_state.active_project = None


def now():
    return time.strftime("%H:%M:%S")


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


def load_json_file(path, fallback=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return fallback


def project_results_path(project):
    return os.path.join(RESULTS_DIR, f"{make_safe_filename(project)}_results.json")


def project_summary_path(project):
    return os.path.join(RESULTS_DIR, f"{make_safe_filename(project)}_summary.json")


def load_project_results(project):
    return load_json_file(project_results_path(project), [])


def load_project_summary(project):
    return load_json_file(project_summary_path(project), {})


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
    }


def build_creative_bank():
    return {
        "viral": (
            ["This just spiked in {kw}", "{kw} demand is moving right now", "Massive shift happening in {kw}"],
            ["We’re seeing a sharp increase in {kw} demand with strong buyer activity."],
            ["Capture {kw} demand before competitors"],
        ),
        "high": (
            ["{kw} converting strongly", "High intent {kw} buyers active now"],
            ["{kw} shows strong conversion potential with consistent demand."],
            ["Generate {kw} enquiries today"],
        ),
        "medium": (
            ["Early {kw} demand forming", "{kw} interest is growing"],
            ["{kw} is showing early-stage demand worth testing."],
            ["Test {kw} ads now"],
        ),
        "low": (
            ["Low demand in {kw}", "Weak {kw} activity"],
            ["{kw} shows weak intent and poor ROI."],
            ["Monitor {kw} only"],
        ),
    }


CREATIVE_BANK = build_creative_bank()


def inject_keyword(hook, caption, cta, keyword):
    hook = hook.replace("{kw}", keyword)
    caption = caption.replace("{kw}", keyword)
    cta = cta.replace("{kw}", keyword)

    if keyword.lower() not in (hook + caption + cta).lower():
        caption = f"{caption} {keyword}"

    return hook, caption, cta


def ai_hook(keyword, data):
    score = data.get("Viral Score", 0)
    demand = data.get("Demand", 0)

    if score > 75 and demand >= 10:
        tier = "viral"
    elif score > 55 and demand >= 10:
        tier = "high"
    elif score > 30 and demand >= 10:
        tier = "medium"
    else:
        tier = "low"

    hooks, captions, ctas = CREATIVE_BANK[tier]

    hook = random.choice(hooks)
    caption = random.choice(captions)
    cta = random.choice(ctas)

    hook, caption, cta = inject_keyword(hook, caption, cta, keyword)

    return {"Hook": hook, "Caption": caption, "CTA": cta}


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


def google_trends_fetch(keyword, min_delay, max_delay, max_429_retries, debug_callback):
    keyword = clean_keyword(keyword)

    result_meta = {
        "HTTP Explore": "",
        "HTTP Multiline": "",
        "Timeline Points": 0,
        "Value Count": 0,
        "First Values": "",
        "Last Values": "",
    }

    payload = {
        "comparisonItem": [{"keyword": keyword, "geo": "GB", "time": "today 3-m"}],
        "category": 0,
        "property": ""
    }

    def log(msg):
        debug_callback(f"[{keyword}] {msg}")

    try:
        log("START")
        log("Payload ready")

        session = requests.Session()

        wait = random.uniform(min_delay, max_delay)
        log(f"Sleeping before explore {round(wait, 2)} seconds")
        time.sleep(wait)

        explore_retry = 0

        while True:
            log("Explore GET sending")

            r = session.get(
                "https://trends.google.com/trends/api/explore",
                params={"hl": "en-GB", "tz": "0", "req": json.dumps(payload)},
                headers=make_headers(),
                timeout=60
            )

            result_meta["HTTP Explore"] = str(r.status_code)

            log(f"Explore status {r.status_code}")
            log(f"Explore first 160 chars {repr(r.text[:160])}")

            if r.status_code == 429:
                explore_retry += 1
                log(f"Explore 429 retry {explore_retry}/{max_429_retries}")

                if explore_retry > max_429_retries:
                    return build_no_data_with_ai(keyword, "EXPLORE 429 RATE LIMITED", "EXPLORE", result_meta)

                cooldown = random.uniform(240, 600)
                log(f"Explore 429 hard cooldown {round(cooldown, 1)} seconds")
                time.sleep(cooldown)
                continue

            if r.status_code != 200:
                return build_no_data_with_ai(keyword, f"EXPLORE BAD STATUS {r.status_code}", "EXPLORE", result_meta)

            break

        explore = parse_google_json(r.text, "EXPLORE")
        widgets = explore.get("widgets", [])

        log(f"Widgets found {len(widgets)}")
        log(f"Widget IDs {[w.get('id') for w in widgets]}")

        timeseries_widget = next((w for w in widgets if w.get("id") == "TIMESERIES"), None)

        if not timeseries_widget:
            return build_no_data_with_ai(keyword, "NO TIMESERIES WIDGET", "EXPLORE", result_meta)

        token = timeseries_widget.get("token")
        request_obj = timeseries_widget.get("request")

        if not token or not request_obj:
            return build_no_data_with_ai(keyword, "MISSING TOKEN OR REQUEST", "EXPLORE", result_meta)

        log(f"Token preview {str(token)[:50]}")

        extra_wait = random.uniform(5, 10)
        log(f"Human pause before multiline {round(extra_wait, 2)} seconds")
        time.sleep(extra_wait)

        multiline_retry = 0

        while True:
            log("Multiline GET sending")

            r2 = session.get(
                "https://trends.google.com/trends/api/widgetdata/multiline",
                params={"hl": "en-GB", "tz": "0", "req": json.dumps(request_obj), "token": token},
                headers=make_headers(),
                timeout=60
            )

            result_meta["HTTP Multiline"] = str(r2.status_code)

            log(f"Multiline status {r2.status_code}")
            log(f"Multiline first 160 chars {repr(r2.text[:160])}")

            if r2.status_code == 429:
                multiline_retry += 1
                log(f"Multiline 429 retry {multiline_retry}/{max_429_retries}")

                if multiline_retry > max_429_retries:
                    return build_no_data_with_ai(keyword, "MULTILINE 429 RATE LIMITED", "MULTILINE", result_meta)

                cooldown = random.uniform(240, 600)
                log(f"Multiline 429 hard cooldown {round(cooldown, 1)} seconds")
                time.sleep(cooldown)
                continue

            if r2.status_code != 200:
                return build_no_data_with_ai(keyword, f"MULTILINE BAD STATUS {r2.status_code}", "MULTILINE", result_meta)

            break

        trend_data = parse_google_json(r2.text, "MULTILINE")
        timeline = trend_data.get("default", {}).get("timelineData", [])

        result_meta["Timeline Points"] = len(timeline)

        log(f"Timeline points {len(timeline)}")

        if not timeline:
            return build_no_data_with_ai(keyword, "NO SEARCH DATA EMPTY TIMELINE", "MULTILINE", result_meta)

        values = []

        for row in timeline:
            value = row.get("value")
            if isinstance(value, list) and value:
                values.append(float(value[0]))

        result_meta["Value Count"] = len(values)
        result_meta["First Values"] = ", ".join(str(int(x)) for x in values[:8])
        result_meta["Last Values"] = ", ".join(str(int(x)) for x in values[-8:])

        analysed = analyse(keyword, values)
        analysed.update(result_meta)
        analysed.update(ai_hook(keyword, analysed))

        log(f"SUCCESS Latest={analysed['Latest']} Recent={analysed['Recent Avg']} Rise={analysed['Rise %']}")

        return analysed

    except Exception as e:
        err = repr(e)
        log(f"FAILED {err}")
        log(f"TRACEBACK {traceback.format_exc()}")
        return build_no_data_with_ai(keyword, err, "EXCEPTION", result_meta)


def show_live_results(projects):
    st.title("📡 Live Project Results")

    if not os.path.exists(RESULTS_DIR):
        st.warning("No results folder found yet. Run scanner.py first.")
        return

    if st.button("Refresh Live Results 🔄"):
        st.rerun()

    if not projects:
        st.warning("No projects found.")
        return

    for project in projects.keys():
        summary = load_project_summary(project)
        results = load_project_results(project)

        with st.container(border=True):
            st.subheader(f"🐸 {project}")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Total scanned", summary.get("total_results", len(results)))

            with col2:
                st.metric("Usable", summary.get("usable_results", 0))

            with col3:
                st.write("Last scanned")
                st.write(summary.get("last_scanned", "Not scanned yet"))

            with col4:
                st.write("Status")
                st.write(summary.get("status", "Waiting"))

            if not results:
                st.info("No results yet for this project.")
                continue

            df = pd.DataFrame(results)

            usable_df = df[
                (pd.to_numeric(df.get("Latest", 0), errors="coerce").fillna(0) > 0)
                | (pd.to_numeric(df.get("Recent Avg", 0), errors="coerce").fillna(0) > 0)
                | (pd.to_numeric(df.get("Viral Score", 0), errors="coerce").fillna(0) > 0)
            ].copy()

            if usable_df.empty:
                st.warning("Results exist, but none have usable search activity yet.")
                st.dataframe(df, use_container_width=True)
                continue

            usable_df = usable_df.sort_values(
                by=["Latest", "Recent Avg", "Rise %", "Viral Score"],
                ascending=False
            )

            st.write("Top 10")
            st.dataframe(
                usable_df[["Keyword", "Latest", "Recent Avg", "Rise %", "Demand", "Viral Score", "Status", "Priority"]].head(10),
                use_container_width=True
            )

            hashtags = summary.get("hashtags_top_50", "")

            st.text_area(
                f"Top hashtags for {project}",
                hashtags,
                height=80,
                key=f"hashtags_{make_safe_filename(project)}"
            )

            csv = usable_df.to_csv(index=False).encode("utf-8")

            st.download_button(
                f"Download {project} CSV",
                csv,
                f"{make_safe_filename(project)}_live_results.csv",
                "text/csv",
                key=f"download_{make_safe_filename(project)}"
            )


st.sidebar.title("🐸 Frog SaaS Dashboard 🐸")

page = st.sidebar.radio(
    "Navigate",
    ["📡 Live Results", "📊 Manual Scanner", "📁 Projects", "➕ Create Project"]
)

if page == "➕ Create Project":
    st.title("🐸 Create Project")

    name = st.text_input("Project Name")

    if st.button("Create Project 🐸") and name:
        st.session_state.projects[name] = []
        save_projects()
        st.success("Saved 🐸")

elif page == "📁 Projects":
    st.title("🐸 Your Projects")

    for name in st.session_state.projects.keys():
        col1, col2 = st.columns([3, 1])

        with col1:
            st.write(f"🐸 {name}")

        with col2:
            if st.button(f"Open {name}"):
                st.session_state.active_project = name

elif page == "📡 Live Results":
    show_live_results(st.session_state.projects)

elif page == "📊 Manual Scanner":
    st.title("🐸 Manual Frog Scanner 🐸")

    if not st.session_state.projects:
        st.warning("Create a project first 🐸")
        st.stop()

    project = st.selectbox(
        "Select Project",
        list(st.session_state.projects.keys())
    )

    keywords = st.text_area(
        "Keywords one per line",
        "\n".join(st.session_state.projects.get(project, [])),
        height=280
    )

    if st.button("Save Keywords 🐸"):
        st.session_state.projects[project] = [
            k.strip() for k in keywords.split("\n") if k.strip()
        ]
        save_projects()
        st.success("Saved 🐸")

    st.subheader("Scan Settings")

    col_a, col_b, col_c, col_d = st.columns(4)

    with col_a:
        st.number_input("Safe workers", min_value=1, max_value=1, value=1, step=1)

    with col_b:
        delay_min = st.number_input("Min delay seconds", min_value=10.0, max_value=1000.0, value=25.0, step=1.0)

    with col_c:
        delay_max = st.number_input("Max delay seconds", min_value=15.0, max_value=2000.0, value=30.0, step=1.0)

    with col_d:
        limit_keywords = st.number_input("Limit this run", min_value=1, max_value=5000, value=10, step=5)

    max_429_retries = st.number_input(
        "429 retry attempts per request",
        min_value=0,
        max_value=3,
        value=3,
        step=1
    )

    start_scan = st.button("Run Manual Frog Scan 🚀🐸")

    st.subheader("Debug Box")
    debug_box = st.empty()

    if start_scan:
        if delay_max <= delay_min:
            st.error("Max delay must be higher than min delay.")
            st.stop()

        saved_keywords = st.session_state.projects.get(project, [])

        if not saved_keywords:
            st.warning("No saved keywords. Click Save Keywords first.")
            st.stop()

        kws = saved_keywords[:int(limit_keywords)]

        debug_lines = []
        results = []

        def add_debug(message):
            debug_lines.append(f"{now()} | {message}")
            debug_box.code("\n".join(debug_lines[-260:]))

        add_debug("MANUAL SCAN STARTED")
        add_debug(f"Project: {project}")
        add_debug(f"Keywords saved: {len(saved_keywords)}")
        add_debug(f"Keywords in this run: {len(kws)}")
        add_debug(f"Delay min/max: {delay_min}/{delay_max}")
        add_debug(f"429 retries: {max_429_retries}")

        progress = st.progress(0)
        status_box = st.empty()
        live_log = st.empty()

        live_lines = []

        for i, keyword in enumerate(kws):
            add_debug(f"[{keyword}] QUEUED {i + 1}/{len(kws)}")

            result = google_trends_fetch(
                keyword,
                float(delay_min),
                float(delay_max),
                int(max_429_retries),
                add_debug
            )

            results.append(result)

            status_box.info(
                f"[{i + 1}/{len(kws)}] {keyword} | {result['Status']} | {result['Raw Status']}"
            )

            live_lines.append(
                f"""🐸 {keyword}
Latest: {result['Latest']}
Recent Avg: {result['Recent Avg']}
Rise: {result['Rise %']}
Demand: {result['Demand']}
Raw: {result['Raw Status']}
Stage: {result['Debug Stage']}
Reason: {result['Debug Reason']}
"""
            )

            live_log.code("\n".join(live_lines[-10:]))
            progress.progress((i + 1) / len(kws))

            between_keyword_wait = random.uniform(25, 30)

            if i < len(kws) - 1:
                add_debug(f"Between keyword safety sleep {round(between_keyword_wait, 1)} seconds")
                time.sleep(between_keyword_wait)

        add_debug("MANUAL SCAN FINISHED")

        df = pd.DataFrame(results)

        if df.empty:
            st.error("No rows returned at all.")
            st.stop()

        safe_project = make_safe_filename(project)

        st.subheader("Raw Debug Results")
        st.dataframe(df, use_container_width=True)

        raw_csv = df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download FULL Raw Debug Report 🐸",
            raw_csv,
            f"{safe_project}_full_raw_debug_report.csv",
            "text/csv"
        )

        usable_df = df[
            (df["Latest"] > 0)
            | (df["Recent Avg"] > 0)
            | (df["Viral Score"] > 0)
        ].copy()

        if usable_df.empty:
            st.error("No usable Google Trends rows found. Check Raw Debug Results.")
            st.stop()

        usable_df = usable_df.sort_values(
            by=["Latest", "Recent Avg", "Rise %", "Viral Score"],
            ascending=False
        )

        st.success("🐸 Usable rows found 🐸")

        fig = px.bar(
            usable_df.head(10),
            x="Keyword",
            y="Latest",
            title="🐸 Top Current Search Interest 🐸"
        )

        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Best → Worst")
        st.dataframe(usable_df, use_container_width=True)

        csv = usable_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Frog Report 🐸",
            csv,
            f"{safe_project}_frog_report.csv",
            "text/csv"
        )
