"""Payer Copilot web app: chat, approval buttons and a trace panel.

Run:  uv run streamlit run app/streamlit_app.py
Then open http://localhost:8501 in your browser.

Each browser session is one LangGraph thread, so follow-up questions
remember earlier turns. All model calls still go through the graph and the
adapter; this file only shows things and passes on your clicks.
"""

import streamlit as st
from langgraph.types import Command

from copilot import memory, tracing
from copilot.graph import new_question, open_graph

st.set_page_config(page_title="Payer Copilot", layout="wide")
RECOMMENDATIONS = ["approve", "deny", "needs_more_info"]
PANEL_HEIGHT = 560  # pixels; the chat and the trace each scroll inside a box this tall


@st.cache_resource
def get_graph():
    """One graph (and checkpoint connection) shared by every rerun of this page."""
    return open_graph()


def start_session() -> None:
    """A fresh session: new thread, empty chat."""
    st.session_state.session_id = tracing.new_run_id()
    st.session_state.chat = []
    st.session_state.run_id = None
    st.session_state.pending = None


if "session_id" not in st.session_state:
    start_session()
ss = st.session_state
graph = get_graph()
config = {"configurable": {"thread_id": ss.session_id}}


def show_result(state: dict) -> None:
    """After the graph returns: either it paused for approval, or it has an answer."""
    if state.get("__interrupt__"):
        ss.pending = state["__interrupt__"][0].value
        return
    ss.pending = None
    ss.chat.append({"role": "assistant", "content": state.get("answer", ""),
                    "route": state.get("route"), "review": state.get("review")})


# ---------- sidebar: session, memory ----------

with st.sidebar:
    st.header("Session")
    st.caption(f"Session ID: {ss.session_id}")
    if st.button("New session"):
        start_session()
        st.rerun()

    values = graph.get_state(config).values
    st.subheader("In focus")
    st.write(f"Member: {values.get('member_id') or '-'}  \nClaim: {values.get('claim_id') or '-'}")

    st.subheader("Notes about this member")
    notes = memory.member_notes(values.get("member_id"))
    st.write("\n".join(f"- {n}" for n in notes) if notes else "None yet.")

    st.subheader("Your preferences")
    for pref in memory.analyst_preferences():
        st.write(f"- {pref}")
    new_pref = st.text_input("Add a preference", placeholder="e.g. Keep answers to 3 sentences", key="new_pref")
    if st.button("Save preference") and new_pref.strip():
        memory.add_note("analyst", new_pref.strip())
        st.rerun()

# ---------- main area ----------

st.title("Payer Copilot")
st.warning("SYNTHETIC DATA ONLY. Acme Health Plan, its members and claims are fictional. "
           "The copilot recommends; a person decides.")
chat_col, trace_col = st.columns([3, 2])

with chat_col:
    # A fixed-height box scrolls on its own, so a long chat doesn't push the trace out of view.
    with st.container(height=PANEL_HEIGHT):
        if not ss.chat:
            st.caption("Ask a question below.")
        for message in ss.chat:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                if message["role"] == "assistant" and message.get("route"):
                    review = message.get("review") or {}
                    status = "passed" if review.get("passed") else "not passed" if review else "not run"
                    st.caption(f"Route: {message['route']} · Reviewer: {status}")

    if ss.pending:
        action = ss.pending["action"]
        args = action["arguments"]
        with st.container(border=True):
            st.subheader("Approval needed. Nothing has been written yet.")
            st.markdown(ss.pending["draft"].replace("\n", "  \n"))
            review = ss.pending.get("review") or {}
            st.caption(f"Reviewer: {'passed' if review.get('passed') else review.get('reasons')}")
            st.markdown("**Edit before approving, if needed**")
            recommendation = st.selectbox("Recommendation", RECOMMENDATIONS, key="recommendation",
                                          index=RECOMMENDATIONS.index(args["recommendation"]))
            rationale = st.text_area("Rationale", value=args["rationale"], height=150, key="rationale")
            approver = st.text_input("Your name (required)", key="approver")
            approve_col, reject_col = st.columns(2)
            clicked = None
            if approve_col.button("Approve", type="primary"):
                clicked = "approve"
            if reject_col.button("Reject"):
                clicked = "reject"
            if clicked and not approver.strip():
                st.error("Please type your name first. The decision is logged with it.")
            elif clicked:
                edited = {**args, "recommendation": recommendation, "rationale": rationale}
                decision = {"decision": clicked, "approver": approver.strip(), "arguments": edited}
                with st.spinner("Recording your decision..."):
                    show_result(graph.invoke(Command(resume=decision), config))
                st.rerun()

    question = st.chat_input("Ask about a claim, a plan's coverage, or a prior auth",
                             disabled=bool(ss.pending))
    if question:
        ss.chat.append({"role": "user", "content": question})
        ss.run_id = tracing.new_run_id()
        with st.spinner("Working. Each step calls the local model, so this can take a few minutes..."):
            show_result(graph.invoke(new_question(question, ss.run_id), config))
        st.rerun()

with trace_col:
    st.subheader("Trace of the latest question")
    steps = tracing.read_run(ss.run_id) if ss.run_id else []
    with st.container(height=PANEL_HEIGHT):  # scrolls on its own, like the chat
        if not steps:
            st.caption("Ask a question to see each step here.")
        for step in steps:
            label = (f"Step {step['step']} · {step['agent']} · {step.get('action') or 'error'} · "
                     f"{step.get('latency_s') or 0:.1f}s")
            with st.expander(label):
                if step.get("error"):
                    st.error(step["error"])
                if step.get("arguments") is not None:
                    st.markdown("**Arguments**")
                    st.json(step["arguments"])
                if "tool_result" in step:
                    st.markdown("**Tool result**")
                    st.json(step["tool_result"], expanded=False)
                if step.get("raw_output"):
                    st.markdown("**Raw model output**")
                    st.code(step["raw_output"], language="json")
                if step.get("prompt"):
                    st.markdown("**Prompt the model saw**")
                    st.json(step["prompt"], expanded=False)
                st.caption(f"Tokens in/out: {step.get('input_tokens')} / {step.get('output_tokens')}")
