# UI/streamlit_app.py
import streamlit as st
import requests
import json
import os
import re
import dateparser
from dateparser.search import search_dates
import pandas as pd
from collections import defaultdict
from datetime import date, datetime

st.set_page_config(page_title="HR Copilot", page_icon="🤖", layout="wide")

# Optional webrtc import (wrapped)
try:
    from streamlit_webrtc import webrtc_streamer, WebRtcMode
    STREAMLIT_WEBRTC_AVAILABLE = True
except Exception:
    STREAMLIT_WEBRTC_AVAILABLE = False

# Optional frame -> wav libraries for capturing frames
try:
    import numpy as np
    import soundfile as sf
    AUDIO_CONVERSION_AVAILABLE = True
except Exception:
    AUDIO_CONVERSION_AVAILABLE = False

# preserve previous default but allow env override
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


# ----------------------------
# Bundled fallback (used only if user file not found)
# ----------------------------
HARDCODED_HOLIDAYS = {
    ("IN", 2025): [
        {"date": "2025-01-01", "name": "New Year's Day"},
        {"date": "2025-01-26", "name": "Republic Day"},
        {"date": "2025-03-14", "name": "Holi (Rangwali Holi)"},
        {"date": "2025-03-31", "name": "Idul Fitr (Eid al-Fitr) - regional/approx"},
        {"date": "2025-04-18", "name": "Good Friday"},
        {"date": "2025-05-01", "name": "Labour Day (May Day)"},
        {"date": "2025-08-15", "name": "Independence Day"},
        {"date": "2025-10-02", "name": "Gandhi Jayanti"},
        {"date": "2025-10-21", "name": "Diwali (Deepavali) - main day (approx)"},
        {"date": "2025-12-25", "name": "Christmas Day"},
    ]
}

# ----------------------------
# Session state defaults
# ----------------------------
def _init_state():
    st.session_state.setdefault("menu", "Leave Balance")
    st.session_state.setdefault("pending_nav", None)
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pixie_greeted", False)
    st.session_state.setdefault("emp_id_input", "")
    st.session_state.setdefault("emp_name", None)
    st.session_state.setdefault("emp_project", None)
    st.session_state.setdefault("leave_type_input", "casual")
    st.session_state.setdefault("from_date_input", date.today())
    st.session_state.setdefault("to_date_input", date.today())
    st.session_state.setdefault("reason_input", "")
_init_state()
if st.session_state.get("pending_nav"):
    st.session_state["menu"] = st.session_state.pop("pending_nav")

# ----------------------------
# Utilities
# ----------------------------
def safe_get(url, **kwargs):
    try:
        return requests.get(url, timeout=5, **kwargs)
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Backend not reachable — {e}")
        return None

def safe_post(url, **kwargs):
    try:
        return requests.post(url, timeout=30, **kwargs)
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Backend not reachable — {e}")
        return None

def request_nav(page: str, tip: str | None = None):
    st.session_state["pending_nav"] = page
    if tip:
        st.toast(tip)
    st.rerun()

def lookup_employee(emp_id: str):
    if not emp_id:
        return None
    res = safe_get(f"{API_URL}/employee/{emp_id}")
    if res and res.status_code == 200:
        return res.json()
    return None

# ----------------------------
# Simple NLP/date helpers (as before)
# ----------------------------
LEAVE_ALIASES = {
    "pl": "casual", "privilege": "casual", "privileged": "casual",
    "casual": "casual", "cl": "casual",
    "sl": "sick", "sick": "sick", "sick leave": "sick",
}
def normalize_leave_type(text: str):
    if not text:
        return None
    t = text.lower()
    for k, v in LEAVE_ALIASES.items():
        if re.search(rf"\b{k}\b", t):
            return v
    return None

def parse_date_piece(s: str):
    dt = dateparser.parse(s)
    return dt.date() if dt else None

def extract_dates(text: str):
    if not text:
        return (None, None)
    t = text.lower()
    iso = re.findall(r"\d{4}-\d{2}-\d{2}", t)
    if len(iso) == 1:
        d = parse_date_piece(iso[0]);  return (d, d) if d else (None, None)
    if len(iso) >= 2:
        return parse_date_piece(iso[0]), parse_date_piece(iso[1])

    m = re.search(r"from (.+?) to (.+)", t)
    if m:
        return parse_date_piece(m.group(1)), parse_date_piece(m.group(2))

    for kw in ["today","tomorrow","next monday","next tuesday","next wednesday",
               "next thursday","next friday","next saturday","next sunday","next week"]:
        if kw in t:
            d = parse_date_piece(kw)
            if d: return (d, d)

    hits = search_dates(text, settings={"PREFER_DATES_FROM": "future"}) or []
    if len(hits) == 1:
        return hits[0][1].date(), hits[0][1].date()
    if len(hits) >= 2:
        return hits[0][1].date(), hits[1][1].date()
    return (None, None)

def extract_emp_id(text: str):
    if not text:
        return None
    m = re.search(r"\b(E?\d{4,6})\b", text, re.IGNORECASE)
    if not m:
        return None
    val = m.group(1)
    core = val[1:] if val.upper().startswith("E") and val[1:].isdigit() else val
    if core.isdigit() and 2020 <= int(core) <= 2035:
        return None
    return core

def classify_intent(text: str):
    if not text:
        return "unknown"
    t0 = text.lower()
    t = re.sub(r"\btale\b", "take", t0)
    if any(k in t for k in ["leave balance","balance","remaining leaves","how many leaves"]):
        return "check_balance"
    if any(k in t for k in ["leave history","history of leaves","past leaves"]):
        return "leave_history"
    if any(k in t for k in ["apply leave","book leave","request leave", "take leave", "i want to take", "i want to apply", "i want to book"]):
        return "apply_leave"
    if re.search(r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b.*\b(day|days|leave)\b", t):
        return "apply_leave"
    if any(k in t for k in ["apply","take","book"]) and "leave" in t:
        return "apply_leave"
    if any(k in t for k in ["policy","policies","maternity policy","leave policy","holiday","holidays"]):
        return "policies"
    return "unknown"

# ----------------------------
# Holidays normalization and grouped view
# (unchanged from your original file)
# ----------------------------
def _normalize_holidays_input(raw_holidays):
    if raw_holidays is None:
        return None
    if isinstance(raw_holidays, str):
        try:
            parsed = json.loads(raw_holidays)
            return _normalize_holidays_input(parsed)
        except Exception:
            return [{"date":"", "name": raw_holidays}]
    if isinstance(raw_holidays, dict):
        out = []
        for k, v in raw_holidays.items():
            out.append({"date": str(k), "name": str(v)})
        return out
    if isinstance(raw_holidays, list):
        out = []
        for item in raw_holidays:
            if isinstance(item, dict):
                date_val = item.get("date") or item.get("day") or item.get("holiday") or ""
                name_val = item.get("name") or item.get("localName") or item.get("holiday") or str(item)
                out.append({"date": str(date_val), "name": str(name_val)})
            elif isinstance(item, str):
                out.append({"date": "", "name": item})
            else:
                out.append({"date":"", "name": str(item)})
        return out
    return [{"date":"", "name": str(raw_holidays)}]

def show_holidays_grouped(holidays):
    normalized = _normalize_holidays_input(holidays)
    if not normalized:
        st.info("No holidays to show.")
        return
    by_month = defaultdict(list)
    for h in normalized:
        raw = h.get("date","") if isinstance(h, dict) else ""
        name = h.get("name","") if isinstance(h, dict) else str(h)
        d = None
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            try:
                parsed = dateparser.parse(raw)
                d = parsed.date() if parsed else None
            except Exception:
                d = None
        if not d:
            by_month["Unknown"].append({"date": raw, "name": name})
        else:
            month_label = d.strftime("%Y - %B")
            by_month[month_label].append({"date": d.isoformat(), "name": name})
    months = sorted([m for m in by_month.keys() if m != "Unknown"])
    if "Unknown" in by_month:
        months.append("Unknown")
    for m in months:
        with st.expander(m, expanded=False):
            rows = by_month[m]
            try:
                df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
                st.table(df)
            except Exception:
                for r in sorted(rows, key=lambda x: x.get("date") or ""):
                    st.markdown(f"- **{r.get('date','—')}** — {r.get('name','')}")

# ----------------------------
# UI Header
# ----------------------------
st.title("🤖 HR Copilot Dashboard")
st.caption("Plan time off. Keep projects flowing. ✨")

colA, colB = st.columns([1, 3])
with colA:
    pass
with colB:
    with st.container():
        st.subheader("🪪 Who are you?")
        i1, i2 = st.columns([1.2, 1])
        with i1:
            new_emp_id = st.text_input("Employee ID", value=st.session_state["emp_id_input"], placeholder="e.g., 10001", key="who_emp")
        with i2:
            if st.button("Fetch Profile", use_container_width=True):
                st.session_state["emp_id_input"] = new_emp_id.strip()
                emp = lookup_employee(st.session_state["emp_id_input"])
                if emp:
                    st.session_state["emp_name"] = emp.get("name")
                    st.session_state["emp_project"] = emp.get("project")
                    st.toast("✅ Profile loaded", icon="✅")
                else:
                    st.session_state["emp_name"] = None
                    st.session_state["emp_project"] = None
                    st.toast("⚠️ Employee not found", icon="⚠️")
        p1, p2 = st.columns(2)
        p1.markdown(f"**Name:** {st.session_state['emp_name'] or '—'}")
        p2.markdown(f"**Project:** {st.session_state['emp_project'] or '—'}")

st.markdown("---")
left_col, right_col = st.columns([2.2, 1])

with left_col:
    menu_options = ["Leave Balance", "Apply Leave", "Leave History", "Policies"]
    current_menu = st.session_state.get("menu", menu_options[0])
    if current_menu not in menu_options:
        current_menu = menu_options[0]
    menu_index = menu_options.index(current_menu)

    # Render radio WITHOUT a conflicting key; store selection back to session_state
    menu = st.radio("🧭 Explore", menu_options, index=menu_index)
    st.session_state["menu"] = menu

    # Leave Balance
    if menu == "Leave Balance":
        st.subheader("📊 Check Leave Balance")
        emp_id = st.text_input("Employee ID", st.session_state.get("emp_id_input", ""), key="lb_emp")
        if st.button("Check Balance"):
            if not emp_id.strip():
                st.error("Please enter an Employee ID.")
            else:
                res = safe_get(f"{API_URL}/leave-balance/{emp_id.strip()}")
                if res and res.status_code == 200:
                    data = res.json(); lb = data.get("leave_balance", {})
                    c1, c2 = st.columns(2)
                    c1.metric("Casual", lb.get("casual", 0))
                    c2.metric("Sick", lb.get("sick", 0))
                    st.success(data)
                elif res:
                    st.error(res.json().get("detail", "Error fetching balance"))

    # Apply Leave
    if menu == "Apply Leave":
        st.subheader("📝 Apply Leave")
        left, right = st.columns(2)
        with left:
            emp_id = st.text_input("Employee ID", st.session_state.get("emp_id_input",""), key="al_emp")
            leave_type = st.selectbox("Leave Type", ["casual", "sick"], index=["casual", "sick"].index(st.session_state["leave_type_input"]), key="al_type")
            reason = st.text_area("Reason", value=st.session_state["reason_input"], placeholder="Short reason for leave", key="al_reason")
        with right:
            from_date_val = st.date_input("From Date", value=st.session_state["from_date_input"], key="al_from")
            to_date_val = st.date_input("To Date", value=st.session_state["to_date_input"], key="al_to")
        submit = st.button("Submit Leave Application", type="primary")
        if submit:
            if not emp_id.strip():
                st.error("Please enter a valid Employee ID.")
            elif from_date_val > to_date_val:
                st.error("From Date cannot be after To Date.")
            else:
                payload = {"emp_id": emp_id.strip(), "leave_type": leave_type, "from_date": str(from_date_val), "to_date": str(to_date_val), "reason": reason.strip() or "N/A"}
                res = safe_post(f"{API_URL}/apply-leave", json=payload)
                if res and res.status_code == 200:
                    data = res.json()
                    st.success("Leave applied successfully ✅")
                    st.write("### Updated Leave Balance")
                    st.json(data.get("leave_balance", {}))
                    st.write("### Leave Record")
                    st.json(data.get("leave", {}))
                elif res:
                    try:
                        msg = res.json().get("detail", "Error applying leave")
                    except Exception:
                        msg = "Error applying leave"
                    st.toast(f"⚠️ {msg}", icon="⚠️")
                    st.error(msg)

    # Leave History
    if menu == "Leave History":
        st.subheader("📜 Leave History")
        emp_id_h = st.text_input("Employee ID for history", st.session_state.get("emp_id_input",""), key="hist_emp")
        if st.button("Get Leave History"):
            if not emp_id_h.strip():
                st.error("Please enter an Employee ID.")
            else:
                res = safe_get(f"{API_URL}/leave-history/{emp_id_h.strip()}")
                if res and res.status_code == 200:
                    payload = res.json()
                    rows = payload.get("history", [])
                    if isinstance(rows, list):
                        if rows:
                            try:
                                st.dataframe(pd.DataFrame(rows), use_container_width=True)
                            except Exception:
                                st.table(rows)
                        else:
                            st.info("No leave records found.")
                    else:
                        st.warning("Unexpected response format from backend:")
                        st.json(payload)
                elif res:
                    st.error(res.json().get("detail", "No history or error"))

    # Policies: load local holidays.json (no upload) if present, else fallback to hardcoded
    if menu == "Policies":
        st.subheader("📘 Company Policies")
        st.markdown("""- **Annual Leave:** 12 days/year  \n- **Sick Leave:** 8 days/year  \n- **Carry Forward:** Up to 5 days""")
        year = date.today().year
        col1, col2, col3 = st.columns([1,1,1])
        with col1:
            selected_year = st.number_input("Year", value=year, min_value=2000, max_value=2100, step=1, key="hol_year")
        with col2:
            country_code = st.text_input("Country Code (ISO 2-letter)", value="IN", max_chars=2, key="hol_cc").upper()
        with col3:
            file_path_input = st.text_input("Local holidays.json path (optional)", value="UI/holidays.json", help="Enter a path to your holidays.json (relative or absolute). Leave as default to check UI/holidays.json", key="hol_path")

        st.write("### 📅 Holiday Calendar — yearly view (grouped by month)")

        holidays = None
        hol_error = None

        candidate_paths = [file_path_input, os.path.join("UI","holidays.json"), os.path.join("/mnt/data","UI","holidays.json")]
        tried = []
        for p in candidate_paths:
            if not p:
                continue
            tried.append(p)
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as fh:
                        raw_loaded = json.load(fh)
                        holidays = _normalize_holidays_input(raw_loaded)
                        hol_error = None
                        st.info(f"Loaded holidays from: {p}")
                        break
            except Exception as e:
                hol_error = (hol_error + " | " if hol_error else "") + f"{p} read error: {e}"

        if holidays is None:
            holidays = HARDCODED_HOLIDAYS.get((country_code, int(selected_year)), None)
            if holidays is not None:
                st.info("Using bundled hardcoded holidays.")
            else:
                st.info(f"No local holidays file found (tried: {tried}). No hardcoded entry for {country_code}/{selected_year}.")
                if hol_error:
                    st.info(f"Details: {hol_error}")

        if holidays:
            show_holidays_grouped(holidays)
        else:
            st.info("No holidays available for display. Add a file at the path above or add entries to HARDCODED_HOLIDAYS.")
            example = [{"date": f"{selected_year}-01-01", "name":"New Year's Day"}, {"date": f"{selected_year}-01-26", "name":"Republic Day"}]
            st.dataframe(pd.DataFrame(example))

with right_col:
    st.subheader("💬 Chat with Pixie")
    if not st.session_state["pixie_greeted"]:
        greet = ("👋 Hi, I’m **Pixie** – your HR helper.\n\nSay things like:\n• *I want to know my leave balance 10001*\n• *I want to take 1 PL from 2025-09-10 to 2025-09-10*\n• *Show my leave history for 10001*\n")
        st.session_state["chat_history"].append(("assistant", greet))
        st.session_state["pixie_greeted"] = True

    for role, content in st.session_state["chat_history"]:
        with st.chat_message(role):
            st.markdown(content)

    # ---------- typed prompt ----------
    prompt = st.chat_input("Ask Pixie about leaves...")
    if prompt:
        st.session_state["chat_history"].append(("user", prompt))
        with st.chat_message("user"):
            st.markdown(prompt)

        prompt_clean = re.sub(r"\btale\b", "take", prompt, flags=re.IGNORECASE)
        intent = classify_intent(prompt_clean)
        maybe_emp = extract_emp_id(prompt_clean)
        if maybe_emp:
            st.session_state["emp_id_input"] = maybe_emp
            emp = lookup_employee(maybe_emp)
            st.session_state["emp_name"] = emp.get("name") if emp else None
            st.session_state["emp_project"] = emp.get("project") if emp else None

        # Intent handlers (same as before)...
        if intent == "check_balance":
            emp_id_for_balance = maybe_emp or st.session_state.get("emp_id_input", "").strip()
            if not emp_id_for_balance:
                need_id_msg = "Please share your **Employee ID** (e.g., `10001`) so I can fetch your leave balance."
                st.session_state["chat_history"].append(("assistant", need_id_msg))
                with st.chat_message("assistant"):
                    st.markdown(need_id_msg)
            else:
                st.session_state["emp_id_input"] = emp_id_for_balance
                nav_msg = f"Opening **Leave Balance** for Employee ID **{emp_id_for_balance}** — navigating to the Leave Balance tab."
                st.session_state["chat_history"].append(("assistant", nav_msg))
                with st.chat_message("assistant"):
                    st.markdown(nav_msg)
                request_nav("Leave Balance")
        elif intent == "apply_leave":
            lt = normalize_leave_type(prompt_clean) or st.session_state.get("leave_type_input", "casual")
            d1, d2 = extract_dates(prompt_clean)
            if (re.search(r"\b(1|one)\b\s*(day|days)?\b", prompt_clean.lower()) and d1 and not d2):
                d2 = d1
            if not d1 and not d2:
                d1 = d2 = date.today()
            reason_guess = re.search(r"(?:because|as|for|due to|reason)\s+(.+)", prompt_clean, re.IGNORECASE)
            if reason_guess:
                reason_text = reason_guess.group(1).strip()[:200]
            else:
                reason_text = st.session_state.get("reason_input", "")
            st.session_state["leave_type_input"] = lt
            st.session_state["from_date_input"] = d1
            st.session_state["to_date_input"] = d2
            if reason_text:
                st.session_state["reason_input"] = reason_text
            emp_display = st.session_state.get("emp_id_input", "") or "—"
            pref_msg = (
                "Opening **Apply Leave** with these details prefilled:\n\n"
                f"• Employee ID: **{emp_display}**\n"
                f"• Leave type: **{lt}**\n"
                f"• From: **{st.session_state['from_date_input']}**\n"
                f"• To: **{st.session_state['to_date_input']}**\n"
            )
            if reason_text:
                pref_msg += f"• Reason: *{reason_text}*\n\n"
            pref_msg += "Review and click **Submit Leave Application** to apply."
            st.session_state["chat_history"].append(("assistant", pref_msg))
            with st.chat_message("assistant"):
                st.markdown(pref_msg)
            request_nav("Apply Leave")
        elif intent == "policies":
            inline = (
                "Here are key policies:\n"
                "- **Annual Leave:** 12 days/year\n"
                "- **Sick Leave:** 8 days/year\n"
                "- **Carry Forward:** up to 5 days/year\n"
                "- **Maternity:** typically 26 weeks (see company handbook)\n\n"
                "Opening **Policies** tab for details."
            )
            st.session_state["chat_history"].append(("assistant", inline))
            with st.chat_message("assistant"):
                st.markdown(inline)
            request_nav("Policies")
        else:
            msg = (
                "I can help with:\n"
                "• **Leave Balance** — *'I want to know my leave balance 10001'*.\n"
                "• **Apply Leave** — *'I want to take 1 PL tomorrow'*.\n"
                "• **Leave History** — *'Show my leave history for 10001'*.\n"
                "• **Policies** — *'maternity policy please'*.\n"
                "Tip: include your **Employee ID**."
            )
            st.session_state["chat_history"].append(("assistant", msg))
            with st.chat_message("assistant"):
                st.markdown(msg)

    # ---------- microphone (webrtc) + capture & transcribe ----------
    st.markdown("---")
    st.markdown("**🎤 Record from your microphone (experimental)**")

    if not STREAMLIT_WEBRTC_AVAILABLE:
        st.info("Microphone widget unavailable: install a compatible 'streamlit-webrtc' package to enable microphone recording in-browser.")
        st.caption("You can still upload an audio file below.")
    else:
        st.caption("Click Start in the widget below, allow microphone access, speak, then click Capture & Transcribe.")
        rtc_configuration = {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
        ctx = webrtc_streamer(
            key="mic",
            mode=WebRtcMode.SENDONLY,
            rtc_configuration=rtc_configuration,
            media_stream_constraints={"audio": True, "video": False},
        )

        # "Capture & Transcribe" button: grab frames from ctx.audio_receiver, convert to WAV, POST to backend.
        if st.button("Capture & Transcribe (webrtc)"):
            if ctx is None:
                st.warning("Audio context not available. Start the mic widget first.")
            elif ctx.audio_receiver is None:
                st.warning("Audio receiver not yet available. Try starting the widget and speaking for a few seconds.")
            else:
                try:
                    frames = ctx.audio_receiver.get_frames(timeout=2)  # list of av.AudioFrame
                except Exception as e:
                    frames = []
                    st.warning(f"No frames received yet: {e}")

                if not frames:
                    st.warning("No audio frames captured. Make sure the mic widget is started, you spoke for a moment, then click this button.")
                else:
                    if not AUDIO_CONVERSION_AVAILABLE:
                        st.error("Server missing numpy/soundfile. Install 'numpy' and 'soundfile' in the Streamlit environment to convert frames.")
                    else:
                        try:
                            # Convert frames (list of av.AudioFrame) -> numpy array -> write WAV bytes
                            arrays = [f.to_ndarray() for f in frames]  # each: shape (channels, samples)
                            # concatenate along time axis
                            data = np.concatenate(arrays, axis=1)  # shape (channels, total_samples)
                            sample_rate = frames[0].sample_rate
                            # write to bytes buffer (WAV)
                            import io
                            wav_buf = io.BytesIO()
                            # soundfile expects shape (samples, channels)
                            sf.write(wav_buf, data.T, sample_rate, format="WAV", subtype="PCM_16")
                            wav_buf.seek(0)

                            # POST to backend transcribe endpoint (same as file upload flow)
                            files = {"file": ("mic_capture.wav", wav_buf, "audio/wav")}
                            res = safe_post(f"{API_URL}/transcribe", files=files)
                            if not res:
                                st.error("Transcription failed: backend not reachable.")
                            elif res.status_code != 200:
                                try:
                                    st.error(f"Transcription error: {res.json().get('detail', res.text)}")
                                except Exception:
                                    st.error(f"Transcription error: {res.text}")
                            else:
                                transcribed = res.json().get("text", "")
                                if not transcribed:
                                    st.warning("No speech recognized in the capture. Try again with clearer audio.")
                                else:
                                    st.success("Transcription complete:")
                                    st.markdown(f"> {transcribed}")

                                    # append to chat history and process same as typed prompt
                                    st.session_state["chat_history"].append(("user", transcribed))
                                    with st.chat_message("user"):
                                        st.markdown(transcribed)

                                    # reuse the same processing logic as typed prompt
                                    prompt_clean = re.sub(r"\btale\b", "take", transcribed, flags=re.IGNORECASE)
                                    intent = classify_intent(prompt_clean)
                                    maybe_emp = extract_emp_id(prompt_clean)
                                    if maybe_emp:
                                        st.session_state["emp_id_input"] = maybe_emp
                                        emp = lookup_employee(maybe_emp)
                                        st.session_state["emp_name"] = emp.get("name") if emp else None
                                        st.session_state["emp_project"] = emp.get("project") if emp else None

                                    # handle intents (same as above: navigate/prefill)
                                    if intent == "check_balance":
                                        emp_id_for_balance = maybe_emp or st.session_state.get("emp_id_input", "").strip()
                                        if not emp_id_for_balance:
                                            need_id_msg = "Please share your **Employee ID** (e.g., `10001`) so I can fetch your leave balance."
                                            st.session_state["chat_history"].append(("assistant", need_id_msg))
                                            with st.chat_message("assistant"):
                                                st.markdown(need_id_msg)
                                        else:
                                            st.session_state["emp_id_input"] = emp_id_for_balance
                                            nav_msg = f"Opening **Leave Balance** for Employee ID **{emp_id_for_balance}** — navigating to the Leave Balance tab."
                                            st.session_state["chat_history"].append(("assistant", nav_msg))
                                            with st.chat_message("assistant"):
                                                st.markdown(nav_msg)
                                            request_nav("Leave Balance")
                                    elif intent == "apply_leave":
                                        lt = normalize_leave_type(prompt_clean) or st.session_state.get("leave_type_input", "casual")
                                        d1, d2 = extract_dates(prompt_clean)
                                        if (re.search(r"\b(1|one)\b\s*(day|days)?\b", prompt_clean.lower()) and d1 and not d2):
                                            d2 = d1
                                        if not d1 and not d2:
                                            d1 = d2 = date.today()
                                        reason_guess = re.search(r"(?:because|as|for|due to|reason)\s+(.+)", prompt_clean, re.IGNORECASE)
                                        if reason_guess:
                                            reason_text = reason_guess.group(1).strip()[:200]
                                        else:
                                            reason_text = st.session_state.get("reason_input", "")
                                        st.session_state["leave_type_input"] = lt
                                        st.session_state["from_date_input"] = d1
                                        st.session_state["to_date_input"] = d2
                                        if reason_text:
                                            st.session_state["reason_input"] = reason_text
                                        emp_display = st.session_state.get("emp_id_input", "") or "—"
                                        pref_msg = (
                                            "Opening **Apply Leave** with these details prefilled:\n\n"
                                            f"• Employee ID: **{emp_display}**\n"
                                            f"• Leave type: **{lt}**\n"
                                            f"• From: **{st.session_state['from_date_input']}**\n"
                                            f"• To: **{st.session_state['to_date_input']}**\n"
                                        )
                                        if reason_text:
                                            pref_msg += f"• Reason: *{reason_text}*\n\n"
                                        pref_msg += "Review and click **Submit Leave Application** to apply."
                                        st.session_state["chat_history"].append(("assistant", pref_msg))
                                        with st.chat_message("assistant"):
                                            st.markdown(pref_msg)
                                        request_nav("Apply Leave")
                                    elif intent == "policies":
                                        inline = (
                                            "Here are key policies:\n"
                                            "- **Annual Leave:** 12 days/year\n"
                                            "- **Sick Leave:** 8 days/year\n"
                                            "- **Carry Forward:** up to 5 days/year\n"
                                            "- **Maternity:** typically 26 weeks (see company handbook)\n\n"
                                            "Opening **Policies** tab for details."
                                        )
                                        st.session_state["chat_history"].append(("assistant", inline))
                                        with st.chat_message("assistant"):
                                            st.markdown(inline)
                                        request_nav("Policies")
                                    else:
                                        msg = (
                                            "I can help with:\n"
                                            "• **Leave Balance** — *'I want to know my leave balance 10001'*.\n"
                                            "• **Apply Leave** — *'I want to take 1 PL tomorrow'*.\n"
                                            "• **Leave History** — *'Show my leave history for 10001'*.\n"
                                            "• **Policies** — *'maternity policy please'*.\n"
                                            "Tip: include your **Employee ID**."
                                        )
                                        st.session_state["chat_history"].append(("assistant", msg))
                                        with st.chat_message("assistant"):
                                            st.markdown(msg)

                        except Exception as e:
                            st.error(f"Failed to convert/send captured audio: {e}")

    # ---------- audio upload & transcribe (fallback) ----------
    st.markdown("---")
    st.markdown("**🎙 Or upload an audio message (wav/mp3/ogg/m4a)**")
    audio_file = st.file_uploader("Upload voice (optional) and click 'Transcribe & Send'", type=["wav", "mp3", "ogg", "m4a"])

    if audio_file:
        col_t1, col_t2 = st.columns([1, 3])
        with col_t1:
            if st.button("Transcribe & Send"):
                with st.spinner("Transcribing audio..."):
                    try:
                        audio_bytes = audio_file.read()
                        files = {"file": (audio_file.name, audio_bytes, audio_file.type or "audio/mpeg")}
                        res = safe_post(f"{API_URL}/transcribe", files=files)
                        if not res:
                            st.error("Transcription failed: backend not reachable.")
                        elif res.status_code != 200:
                            try:
                                st.error(f"Transcription error: {res.json().get('detail', res.text)}")
                            except Exception:
                                st.error(f"Transcription error: {res.text}")
                        else:
                            transcribed = res.json().get("text", "")
                            if not transcribed:
                                st.warning("No speech recognized. Try clearer audio or a different file.")
                            else:
                                st.success("Transcription complete:")
                                st.markdown(f"> {transcribed}")
                                st.session_state["chat_history"].append(("user", transcribed))
                                with st.chat_message("user"):
                                    st.markdown(transcribed)

                                # reuse the same processing logic as for typed prompt
                                prompt_clean = re.sub(r"\btale\b", "take", transcribed, flags=re.IGNORECASE)
                                intent = classify_intent(prompt_clean)
                                maybe_emp = extract_emp_id(prompt_clean)
                                if maybe_emp:
                                    st.session_state["emp_id_input"] = maybe_emp
                                    emp = lookup_employee(maybe_emp)
                                    st.session_state["emp_name"] = emp.get("name") if emp else None
                                    st.session_state["emp_project"] = emp.get("project") if emp else None

                                # handle intents (same as typed)
                                if intent == "check_balance":
                                    emp_id_for_balance = maybe_emp or st.session_state.get("emp_id_input", "").strip()
                                    if not emp_id_for_balance:
                                        need_id_msg = "Please share your **Employee ID** (e.g., `10001`) so I can fetch your leave balance."
                                        st.session_state["chat_history"].append(("assistant", need_id_msg))
                                        with st.chat_message("assistant"):
                                            st.markdown(need_id_msg)
                                    else:
                                        st.session_state["emp_id_input"] = emp_id_for_balance
                                        nav_msg = f"Opening **Leave Balance** for Employee ID **{emp_id_for_balance}** — navigating to the Leave Balance tab."
                                        st.session_state["chat_history"].append(("assistant", nav_msg))
                                        with st.chat_message("assistant"):
                                            st.markdown(nav_msg)
                                        request_nav("Leave Balance")
                                elif intent == "apply_leave":
                                    lt = normalize_leave_type(prompt_clean) or st.session_state.get("leave_type_input", "casual")
                                    d1, d2 = extract_dates(prompt_clean)
                                    if (re.search(r"\b(1|one)\b\s*(day|days)?\b", prompt_clean.lower()) and d1 and not d2):
                                        d2 = d1
                                    if not d1 and not d2:
                                        d1 = d2 = date.today()
                                    reason_guess = re.search(r"(?:because|as|for|due to|reason)\s+(.+)", prompt_clean, re.IGNORECASE)
                                    if reason_guess:
                                        reason_text = reason_guess.group(1).strip()[:200]
                                    else:
                                        reason_text = st.session_state.get("reason_input", "")
                                    st.session_state["leave_type_input"] = lt
                                    st.session_state["from_date_input"] = d1
                                    st.session_state["to_date_input"] = d2
                                    if reason_text:
                                        st.session_state["reason_input"] = reason_text
                                    emp_display = st.session_state.get("emp_id_input", "") or "—"
                                    pref_msg = (
                                        "Opening **Apply Leave** with these details prefilled:\n\n"
                                        f"• Employee ID: **{emp_display}**\n"
                                        f"• Leave type: **{lt}**\n"
                                        f"• From: **{st.session_state['from_date_input']}**\n"
                                        f"• To: **{st.session_state['to_date_input']}**\n"
                                    )
                                    if reason_text:
                                        pref_msg += f"• Reason: *{reason_text}*\n\n"
                                    pref_msg += "Review and click **Submit Leave Application** to apply."
                                    st.session_state["chat_history"].append(("assistant", pref_msg))
                                    with st.chat_message("assistant"):
                                        st.markdown(pref_msg)
                                    request_nav("Apply Leave")
                                elif intent == "policies":
                                    inline = (
                                        "Here are key policies:\n"
                                        "- **Annual Leave:** 12 days/year\n"
                                        "- **Sick Leave:** 8 days/year\n"
                                        "- **Carry Forward:** up to 5 days/year\n"
                                        "- **Maternity:** typically 26 weeks (see company handbook)\n\n"
                                        "Opening **Policies** tab for details."
                                    )
                                    st.session_state["chat_history"].append(("assistant", inline))
                                    with st.chat_message("assistant"):
                                        st.markdown(inline)
                                    request_nav("Policies")
                                else:
                                    msg = (
                                        "I can help with:\n"
                                        "• **Leave Balance** — *'I want to know my leave balance 10001'*.\n"
                                        "• **Apply Leave** — *'I want to take 1 PL tomorrow'*.\n"
                                        "• **Leave History** — *'Show my leave history for 10001'*.\n"
                                        "• **Policies** — *'maternity policy please'*.\n"
                                        "Tip: include your **Employee ID**."
                                    )
                                    st.session_state["chat_history"].append(("assistant", msg))
                                    with st.chat_message("assistant"):
                                        st.markdown(msg)
                    except Exception as e:
                        st.error(f"Transcription failed: {e}")

# small CSS
st.markdown("""<style>.stMetric { border-radius: 12px; padding: 8px; }.block-container { padding-top: 1.2rem; }</style>""", unsafe_allow_html=True)
