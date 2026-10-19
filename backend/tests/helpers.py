"""Synthetic documents and fixtures. No real personal data."""
import io

import docx
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

CV_TEXT = """Riya Sharma
riya.sharma@example.com | +91 98765 43210
EDUCATION
B.Tech in Computer Science, Example Institute of Technology, Jaipur 2022 - Expected 2027
Class XII, Sample Public School 2019 - 2021
SKILLS
Languages: Python, JavaScript, SQL
Frameworks: LangChain, React, FastAPI
EXPERIENCE
ML Intern at Acme Labs Jun 2024 - Aug 2024
• Built a RAG prototype over 500 documents using LangChain
• Reduced response time by 30%
• Wrote unit tests for the Python data pipeline
PROJECTS
Resume Ranker | Python, NLP
- Ranked resumes with TF-IDF and cosine similarity
Portfolio Site | React
- Built a personal site with React and Vite
CERTIFICATIONS
Deep Learning Specialization - Coursera 2023
"""


def make_pdf(text: str = CV_TEXT, *, pages_of_text: bool = True) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    if pages_of_text:
        y = 800
        for line in text.split("\n"):
            c.drawString(40, y, line)
            y -= 14
            if y < 40:
                c.showPage()
                y = 800
    else:  # image-only/scanned look-alike: drawing, no text layer
        c.rect(50, 50, 300, 300, fill=1)
    c.save()
    return buf.getvalue()


def make_docx(text: str = CV_TEXT) -> bytes:
    d = docx.Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def upload(client, headers, data: bytes, filename: str, ctype: str = "application/octet-stream"):
    return client.post("/api/v1/documents/upload", headers=headers, files={"file": (filename, data, ctype)})


def confirm_payload(parse: dict, **overrides) -> dict:
    """Build a confirm request from a preview, acknowledging every warning and fixing education status."""
    parsed = parse["parsed"]
    edu = []
    for e in parsed["education"]:
        status = e["status"] or e["suggested_status"] or "completed"
        edu.append({k: e[k] for k in ("degree", "institution", "start_date", "end_date")} | {"status": status})
    profile = {
        "full_name": parsed["full_name"], "phone": parsed["phone"], "education": edu,
        "experience": [{k: v for k, v in x.items() if k != "confidence"} for x in parsed["experience"]],
        "projects": [{k: v for k, v in x.items() if k != "confidence"} for x in parsed["projects"]],
        "skills": parsed["skills"], "certifications": parsed["certifications"],
    }
    body = {"parse_id": parse["parse_id"], "profile": profile,
            "acknowledged_flags": [f["id"] for f in parse["flags"]]}
    body.update(overrides)
    return body
