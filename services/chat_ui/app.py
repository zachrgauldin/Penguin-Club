"""Streamlit internal UI in front of the three Wave-1 agents.

Run with: streamlit run services/chat_ui/app.py

Tabs:
- Reimbursement: structuring proposals, classify-next-batch, packet drafts, registry
- Contracts: deal calendar, takedown forecast, weekly miss-audit
- Lavon-watch: latest signals, daily digest, ad-hoc Q&A over signals corpus
"""
from __future__ import annotations

import streamlit as st

from services.common.config import pilot_config


def main() -> None:
    cfg = pilot_config()
    st.set_page_config(page_title="Penguin-Club", layout="wide")
    st.title("Penguin-Club")
    st.caption(f"Pilot: {cfg['deal']['name']} ({cfg['deal']['jurisdiction']}, {cfg['deal']['county']} County, {cfg['deal']['state']})")

    tabs = st.tabs(["Reimbursement", "Contracts", "Lavon-watch"])

    with tabs[0]:
        st.subheader("Reimbursement")
        st.info("Structuring / classify / package / registry — wire to services.reimbursement_api.")

    with tabs[1]:
        st.subheader("Contracts")
        st.info("Deal calendar, takedown forecast, weekly miss-audit — wire to services.sharepoint_watcher.")

    with tabs[2]:
        st.subheader("Lavon-watch")
        st.info("Latest signals, daily/weekly digest, /lavon ask — wire to services.signal_collectors.")


if __name__ == "__main__":
    main()
