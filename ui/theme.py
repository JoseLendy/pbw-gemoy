"""UI-only readability theme, appended after static/phone.css.

The demo is shown at 1920×1080 on a projector; the default Gradio light theme left body text,
card reasons and the phone screen with very little contrast. These rules keep the content readable
without changing any backend or generated copy.
"""

EXTRA_CSS = """
/* ---------------------------------------------------------------- page shell */
html, body, gradio-app, .gradio-container {
  background: #f3f6fa !important;
  color: #172033 !important;
}
.gradio-container {
  font-size: 15px;
  line-height: 1.55;
}
.gradio-container .prose,
.gradio-container .prose p,
.gradio-container .prose li,
.gradio-container .prose td,
.gradio-container .prose th {
  color: #172033;
}
.gradio-container h1, .gradio-container h2,
.gradio-container h3, .gradio-container h4 {
  color: #0f172a !important;
  letter-spacing: .01em;
}
.gradio-container .prose h3 { font-size: 20px; font-weight: 700; }
.gradio-container .prose h4 { font-size: 16px; font-weight: 700; }
.gradio-container button { font-weight: 600; }
.gradio-container .wrap, .gradio-container .block { border-radius: 10px; }

/* ---------------------------------------------------------------- status strip */
.hw-status {
  background: #ffffff !important;
  border: 1px solid #dce3ec;
  border-radius: 12px;
  padding: 10px 14px !important;
  color: #334155 !important;
  font-size: 14px !important;
  gap: 18px !important;
  box-shadow: 0 2px 8px rgba(15, 23, 42, .05);
}
.hw-status span { color: #334155 !important; }
.hw-status .dot { width: 9px; height: 9px; }

/* ---------------------------------------------------------------- recommendation card + workflow */
.hw-card {
  background: #ffffff;
  border: 1px solid #dce3ec;
  border-radius: 16px;
  padding: 18px 20px;
  color: #172033;
  font-size: 15px;
  line-height: 1.65;
  box-shadow: 0 8px 22px rgba(15, 23, 42, .07);
}
.hw-card h3 {
  margin: 0 0 4px;
  font-size: 21px;
  line-height: 1.35;
  color: #0f172a;
}
.hw-card p { margin: 4px 0 10px; font-size: 15px; color: #1e293b; }
.hw-card ul { margin: 6px 0 0 20px; padding: 0; }
.hw-card li { margin: 4px 0; font-size: 15px; line-height: 1.6; color: #1e293b; }
.hw-card b { color: #0f172a; }
.hw-workflow {
  background: #eaf2ff;
  border: 1px solid #b9d0f0;
  border-radius: 14px;
  padding: 14px 16px;
  color: #17365d;
  font-size: 14px;
  line-height: 1.7;
  margin-bottom: 10px;
}
.hw-workflow b { color: #0d2b4e; }

/* ---------------------------------------------------------------- phone mock */
.hw-phone {
  border: 1px solid #252b33;
  box-shadow: 0 20px 46px rgba(15, 23, 42, .30), 0 2px 8px rgba(15, 23, 42, .25);
  margin-top: 10px;
  margin-bottom: 14px;
}
.hw-phone:not(.skin-douyin):not(.skin-poster) .screen {
  color: #172033 !important;
  font-size: 15px;
  line-height: 1.7;
}
.hw-phone:not(.skin-douyin):not(.skin-poster) .p {
  color: #172033 !important;
  font-size: 15.5px;
  font-weight: 500;
  line-height: 1.72;
}
.hw-phone .topbar {
  background: #f8fafc;
  color: #334155 !important;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
}
.hw-phone:not(.skin-douyin):not(.skin-poster) .cap {
  color: #475569 !important;
  font-size: 12px;
}
.hw-phone:not(.skin-douyin):not(.skin-poster) .src {
  color: #334155 !important;
  background: #f1f5f9;
  border-left-color: #94a3b8;
}
.hw-phone h2 { color: #0f172a; }
.hw-phone .cta { font-weight: 600; }
.hw-phone .screen::-webkit-scrollbar { width: 8px; }
.hw-phone .screen::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 8px; }

/* ---------------------------------------------------------------- compare / baseline surfaces */
.hw-compare-card {
  background: #ffffff !important;
  border: 1px solid #dce3ec !important;
  border-radius: 16px !important;
  padding: 14px 12px 8px !important;
  box-shadow: 0 8px 22px rgba(15, 23, 42, .07);
}
.hw-compare-card .hw-phone { margin-left: auto; margin-right: auto; }
.hw-baseline-card {
  background: #fffaf3 !important;
  border: 1px solid #e7c9a4 !important;
  border-radius: 16px !important;
  padding: 16px !important;
  color: #2f2115 !important;
}
.hw-verified-card {
  background: #f4fbf4 !important;
  border: 1px solid #b9d9b9 !important;
  border-radius: 16px !important;
  padding: 16px !important;
  color: #14351b !important;
}

/* ---------------------------------------------------------------- data tables (HQ / compare) */
.gradio-container .prose table,
.hw-card table,
.hw-compare-card table {
  font-size: 14px;
  color: #172033;
}
.gradio-container .prose th,
.hw-card th,
.hw-compare-card th {
  color: #0f172a;
  font-weight: 700;
}
.gradio-container .prose td,
.hw-card td,
.hw-compare-card td {
  color: #1e293b;
}

/* ---------------------------------------------------------------- small print */
.hw-progress { color: #334155 !important; }
.hw-talk { box-shadow: 0 2px 8px rgba(15, 23, 42, .05); }
.hw-banner { box-shadow: 0 1px 4px rgba(15, 23, 42, .05); }
.hw-banner.note, .hw-banner.warn { border-width: 1px; }
"""
