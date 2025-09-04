# ui/streamlit_app.py
import streamlit as st
import requests
from datetime import date
import re
import dateparser
from dateparser.search import search_dates  # better date detection

# ----------------------------
# Basic config
# ----------------------------
st.set_page_config(page_title="HR Copilot", page_icon="🤖", layout="wide")

# Hardcoded API URL (no sidebar setting)
API_URL = "http://127.0.0.1:8000"

# ----------------------------
# Session defaults
# ----------------------------
def _init_state():
    # Start on Leave Balance directly
    st.session_state.setdefault("menu", "Leave Balance")
    st.session_state.setdefault("pending_nav", None)      # defer nav target
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("pixie_greeted", False)

    # identity
    st.session_state.setdefault("emp_id_input", "")
    st.session_state.setdefault("emp_name", None)
    st.session_state.setdefault("emp_project", None)

    # apply-leave prefills
    st.session_state.setdefault("leave_type_input", "casual")
    st.session_state.setdefault("from_date_input", date.today())
    st.session_state.setdefault("to_date_input", date.today())
    st.session_state.setdefault("reason_input", "")

_init_state()

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
        return requests.post(url, timeout=8, **kwargs)
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Backend not reachable — {e}")
        return None

def request_nav(page: str, tip: str | None = None):
    """
    Defer changing the radio selection until BEFORE the widget renders
    on the next run, to avoid Streamlit's 'cannot be modified' error.
    """
    st.session_state["pending_nav"] = page
    if tip:
        st.toast(tip)
    st.rerun()

def lookup_employee(emp_id: str):
    """Call the dedicated backend endpoint to fetch one employee."""
    if not emp_id:
        return None
    res = safe_get(f"{API_URL}/employee/{emp_id}")
    if res and res.status_code == 200:
        return res.json()
    return None

# ---- light NLP parsing for Pixie ----
LEAVE_ALIASES = {
    "pl": "casual", "privilege": "casual", "privileged": "casual",
    "casual": "casual", "cl": "casual",
    "sl": "sick", "sick": "sick", "sick leave": "sick",
}
def normalize_leave_type(text: str):
    t = text.lower()
    for k, v in LEAVE_ALIASES.items():
        if re.search(rf"\b{k}\b", t):
            return v
    return None

def parse_date_piece(s: str):
    dt = dateparser.parse(s)
    return dt.date() if dt else None

def extract_dates(text: str):
    """
    Returns (d1, d2) where each is a date or None.
    Supports:
    - ISO yyyy-mm-dd
    - 'from X to Y'
    - keywords like 'tomorrow', 'next monday'
    - fallback: first one or two hits via search_dates()
    """
    t = text.lower()

    # ISO yyyy-mm-dd
    iso = re.findall(r"\d{4}-\d{2}-\d{2}", t)
    if len(iso) == 1:
        d = parse_date_piece(iso[0]);  return (d, d) if d else (None, None)
    if len(iso) >= 2:
        return parse_date_piece(iso[0]), parse_date_piece(iso[1])

    # "from X to Y"
    m = re.search(r"from (.+?) to (.+)", t)
    if m:
        return parse_date_piece(m.group(1)), parse_date_piece(m.group(2))

    # common relative keywords -> same-day range
    for kw in ["today","tomorrow","next monday","next tuesday","next wednesday",
               "next thursday","next friday","next saturday","next sunday","next week"]:
        if kw in t:
            d = parse_date_piece(kw)
            if d: return (d, d)

    # fallback: search for any dates in the text
    hits = search_dates(text, settings={"PREFER_DATES_FROM": "future"}) or []
    if len(hits) == 1:
        return hits[0][1].date(), hits[0][1].date()
    if len(hits) >= 2:
        return hits[0][1].date(), hits[1][1].date()

    return (None, None)

def extract_emp_id(text: str):
    m = re.search(r"\b(E?\d{4,6})\b", text, re.IGNORECASE)  # accept E-prefixed ids too
    if not m:
        return None
    val = m.group(1)
    return val[1:] if val.upper().startswith("E") and val[1:].isdigit() else val

def classify_intent(text: str):
    t = text.lower()
    if any(k in t for k in ["leave balance","balance","remaining leaves","how many leaves"]):
        return "check_balance"
    if any(k in t for k in ["leave history","history of leaves","past leaves"]):
        return "leave_history"
    if any(k in t for k in ["apply","take leave","request leave","book leave","i want to take","apply leave"]):
        return "apply_leave"
    if any(k in t for k in ["policy","policies","maternity policy","leave policy"]):
        return "policies"
    return "unknown"

# ----------------------------
# Header
# ----------------------------
st.title("🤖 HR Copilot Dashboard")
st.caption("Plan time off. Keep projects flowing. ✨")

# ----------------------------
# Top: backend status + identity card
# ----------------------------
colA, colB = st.columns([1, 3])
with colA:
    health = safe_get(f"{API_URL}/")
    st.metric("Backend", "Online" if (health and health.status_code == 200) else "Offline")

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

        # Show profile (if available)
        p1, p2 = st.columns(2)
        p1.markdown(f"**Name:** {st.session_state['emp_name'] or '—'}")
        p2.markdown(f"**Project:** {st.session_state['emp_project'] or '—'}")

st.markdown("---")

# ----------------------------
# Layout: main content (left) + Pixie chat (right)
# ----------------------------
left_col, right_col = st.columns([2.2, 1])

with left_col:
    # ----- Handle deferred navigation BEFORE rendering the radio -----
    if st.session_state.get("pending_nav"):
        st.session_state["menu"] = st.session_state.pop("pending_nav")

    # ---- Menu (Explore) ----
    menu_options = ["Leave Balance", "Apply Leave", "Leave History", "Policies"]
    menu = st.radio(
        "🧭 Explore",
        menu_options,
        index=menu_options.index(st.session_state["menu"]) if st.session_state["menu"] in menu_options else 0,
        key="menu"
    )

    # ---- Leave Balance ----
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

    # ---- Apply Leave ----
    if menu == "Apply Leave":
        st.subheader("📝 Apply Leave")
        left, right = st.columns(2)

        with left:
            emp_id = st.text_input("Employee ID", st.session_state.get("emp_id_input",""), key="al_emp")
            leave_type = st.selectbox(
                "Leave Type",
                ["casual", "sick"],
                index=["casual", "sick"].index(st.session_state["leave_type_input"]),
                key="al_type"
            )
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
                payload = {
                    "emp_id": emp_id.strip(),
                    "leave_type": leave_type,
                    "from_date": str(from_date_val),
                    "to_date": str(to_date_val),
                    "reason": reason.strip() or "N/A",
                }
                res = safe_post(f"{API_URL}/apply-leave", json=payload)
                if res and res.status_code == 200:
                    # exact phrasing required
                    st.success("Leave applied successfully")
                    st.toast("Leave applied successfully", icon="✅")
                    st.balloons()
                    with st.expander("View saved leave record"):
                        st.json(res.json())
                elif res:
                    try:
                        msg = res.json().get("detail", "Error applying leave")
                    except Exception:
                        msg = "Error applying leave"
                    st.toast(f"⚠️ {msg}", icon="⚠️")
                    st.error(msg)

    # ---- Leave History ----
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
                                import pandas as pd
                                st.dataframe(pd.DataFrame(rows), use_container_width=True)
                            except Exception:
                                st.table(rows)  # simple fallback
                        else:
                            st.info("No leave records found.")
                    else:
                        st.warning("Unexpected response format from backend:")
                        st.json(payload)
                elif res:
                    st.error(res.json().get("detail", "No history or error"))

    # ---- Policies ----
    if menu == "Policies":
        st.subheader("📘 Company Policies")
        res = safe_get(f"{API_URL}/policies")
        if res and res.status_code == 200:
            payload = res.json()
            if isinstance(payload, dict) and "policies" in payload:
                st.json(payload["policies"])
            else:
                st.json(payload)
        else:
            st.markdown(
                """
- **Annual Leave:** 12 days/year  
- **Sick Leave:** 8 days/year  
- **Carry Forward:** Up to 5 days  
- **Holiday Calendar:** Refer company portal
                """
            )

# ----------------------------
# Pixie chat
# ----------------------------
with right_col:
    st.subheader("💬 Chat with Pixie")
    if not st.session_state["pixie_greeted"]:
        greet = (
            "👋 Hi, I’m **Pixie** – your HR helper.\n\n"
            "Say things like:\n"
            "• *I want to know my leave balance 10001*\n"
            "• *I want to take 1 PL from 2025-09-10 to 2025-09-10*\n"
            "• *Show my leave history for 10001*\n"
        )
        st.session_state["chat_history"].append(("assistant", greet))
        st.session_state["pixie_greeted"] = True

    for role, content in st.session_state["chat_history"]:
        with st.chat_message(role):
            st.markdown(content)

    prompt = st.chat_input("Ask Pixie about leaves...")
    if prompt:
        st.session_state["chat_history"].append(("user", prompt))
        with st.chat_message("user"):
            st.markdown(prompt)

        intent = classify_intent(prompt)
        maybe_emp = extract_emp_id(prompt)
        if maybe_emp:
            st.session_state["emp_id_input"] = maybe_emp
            # refresh identity card too
            emp = lookup_employee(maybe_emp)
            st.session_state["emp_name"] = emp.get("name") if emp else None
            st.session_state["emp_project"] = emp.get("project") if emp else None

        # ======== INTENT: CHECK BALANCE (DIRECT REPLY IN CHAT) ========
        if intent == "check_balance":
            emp_id_for_balance = maybe_emp or st.session_state.get("emp_id_input", "").strip()

            if not emp_id_for_balance:
                need_id_msg = "Please share your **Employee ID** (e.g., `10001`) so I can fetch your leave balance."
                st.session_state["chat_history"].append(("assistant", need_id_msg))
                with st.chat_message("assistant"):
                    st.markdown(need_id_msg)
            else:
                res = safe_get(f"{API_URL}/leave-balance/{emp_id_for_balance}")
                if res and res.status_code == 200:
                    data = res.json()
                    lb = data.get("leave_balance", {})
                    casual = lb.get("casual", 0)
                    sick = lb.get("sick", 0)

                    reply = (
                        f"**Leave Balance for {emp_id_for_balance}**\n\n"
                        f"- Casual: **{casual}**\n"
                        f"- Sick: **{sick}**"
                    )
                    st.session_state["chat_history"].append(("assistant", reply))
                    with st.chat_message("assistant"):
                        st.markdown(reply)
                elif res:
                    err = res.json().get("detail", "Could not fetch leave balance.")
                    st.session_state["chat_history"].append(("assistant", f"⚠️ {err}"))
                    with st.chat_message("assistant"):
                        st.markdown(f"⚠️ {err}")

        # ======== INTENT: APPLY LEAVE (PREFILL + NAV, NO DIRECT STATE MUTATION) ========
        elif intent == "apply_leave":
            # set defaults first
            lt = normalize_leave_type(prompt) or st.session_state["leave_type_input"] or "casual"
            d1, d2 = extract_dates(prompt)

            # if "one day" mentioned and one date found, force same-day range
            if (" one day" in prompt.lower() or "1 day" in prompt.lower()) and d1 and not d2:
                d2 = d1

            # fallback if no date parsed
            if not d1 and not d2:
                d1 = d2 = date.today()

            # update prefills
            st.session_state["leave_type_input"] = lt
            st.session_state["from_date_input"] = d1
            st.session_state["to_date_input"] = d2
            # light auto-reason if user gave one
            reason_guess = re.search(r"(?:because|as|for|due to)\s+(.+)", prompt, re.IGNORECASE)
            if reason_guess:
                st.session_state["reason_input"] = reason_guess.group(1).strip()[:200]
            # Persist emp id if present
            if maybe_emp:
                st.session_state["emp_id_input"] = maybe_emp

            # friendly chat summary
            pref_msg = (
                "Opening **Apply Leave** with these details prefilled:\n"
                f"• Leave type: **{lt}**\n"
                f"• From: **{st.session_state['from_date_input']}**\n"
                f"• To: **{st.session_state['to_date_input']}**\n"
                "Review and click **Submit Leave Application**."
            )
            st.session_state["chat_history"].append(("assistant", pref_msg))
            with st.chat_message("assistant"):
                st.markdown(pref_msg)

            # Defer navigation to avoid Streamlit key mutation error
            request_nav("Apply Leave")

        # ======== INTENT: POLICIES (OPEN TAB OR RESPOND INLINE) ========
        elif intent == "policies":
            # quick inline reply AND open Policies tab
            inline = (
                "Here are key policies:\n"
                "- **Annual Leave:** 12 days/year\n"
                "- **Sick Leave:** 8 days/year\n"
                "- **Carry Forward:** up to 5 days\n"
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

# ----------------------------
# Small CSS
# ----------------------------
st.markdown(
    """
    <style>
    .stMetric { border-radius: 12px; padding: 8px; }
    .block-container { padding-top: 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True
)
