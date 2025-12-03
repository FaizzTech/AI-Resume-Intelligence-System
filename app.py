from flask import Flask, render_template, request
from groq import Groq
from pypdf import PdfReader
from dotenv import load_dotenv
import os, json, re
import markdown2

app = Flask(__name__)

# ---------- CONFIG ----------
load_dotenv()
groq_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=groq_key)


# ---------- HELPERS ----------
def extract_text_from_pdf(file):
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        content = page.extract_text()
        if content:
            text += content + "\n"
    return text


def try_json_load(s):
    """Try json.loads safely, returning dict or None."""
    try:
        return json.loads(s)
    except Exception:
        return None


def repair_common_json_issues(s):
    """Quick fixes: smart quotes, single->double quotes, trailing commas, percent signs in numbers kept as strings for now."""
    # replace common smart quotes
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    # replace single quotes around keys/values with double quotes when safe-ish
    # careful: use a simple heuristic: when string contains {" and ' or ' and } try replace
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')
    # remove Markdown fences ```json ... ```
    s = re.sub(r"```(?:json)?\n?", "", s)
    s = s.replace("```", "")
    # remove leading/explanatory lines like "Sure, here's the JSON:"
    s = re.sub(r"^[^\{]*", "", s, flags=re.S)
    # remove trailing text after last }
    if "}" in s:
        last = s.rfind("}")
        s = s[:last+1]
    # remove trailing commas before closing braces/brackets
    s = re.sub(r",\s*(\]|})", r"\1", s)
    return s


def find_first_valid_json_block(text):
    """
    Try to locate a valid JSON object inside `text`.
    Strategy: try many start/end pairs (where start is '{' and end is '}') and attempt json.loads.
    Return dict or None.
    """
    if not text or "{" not in text:
        return None

    # Narrow down: remove code fences first
    text = text.strip()

    # Collect indexes of braces
    start_indexes = [m.start() for m in re.finditer(r'\{', text)]
    end_indexes = [m.start() for m in re.finditer(r'\}', text)]

    # If none, bail
    if not start_indexes or not end_indexes:
        return None

    # Try combinations: for each start, find an end >= start and attempt json.loads on substring
    # To keep it reasonable, prefer shorter windows first: try nearest ends
    for si in start_indexes:
        for ej in end_indexes:
            if ej <= si:
                continue
            candidate = text[si:ej+1]
            # quick repair and try
            cand1 = repair_common_json_issues(candidate)
            parsed = try_json_load(candidate)
            if parsed:
                return parsed
            parsed = try_json_load(cand1)
            if parsed:
                return parsed

    # Final attempt: try to extract the largest {...} block via greedy regex (fallback)
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        candidate = m.group(0)
        cand1 = repair_common_json_issues(candidate)
        parsed = try_json_load(candidate) or try_json_load(cand1)
        if parsed:
            return parsed

    return None


def normalize_list_field(value):
    """Ensure field returns a list of strings.
       Accepts list, string with commas or newlines, or bullet list.
    """
    if not value:
        return []
    if isinstance(value, list):
        # convert items to strings and strip
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, (int, float)):
        return [str(value)]
    text = str(value).strip()
    # if it's a JSON-like string representing list, try parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    # split by newlines or commas or bullets
    items = re.split(r'\n|,|•|\u2022|\-', text)
    cleaned = [i.strip(" \t\n\r.[]\"'") for i in items if i and i.strip()]
    return cleaned


def normalize_skills(skills_raw):
    """Return list of dicts with 'skill' and numeric 'score' (0-100)."""
    out = []
    if not skills_raw:
        return out
    # If it's a string, try to parse as JSON
    if isinstance(skills_raw, str):
        try:
            skills_raw = json.loads(skills_raw)
        except Exception:
            # try to split lines like "Python: 80%" etc.
            lines = [l.strip() for l in skills_raw.splitlines() if l.strip()]
            parsed = []
            for ln in lines:
                m = re.match(r'([^:]+)[:\-]\s*([0-9]{1,3})%?', ln)
                if m:
                    parsed.append({"skill": m.group(1).strip(), "score": int(m.group(2))})
            skills_raw = parsed

    if isinstance(skills_raw, list):
        for item in skills_raw:
            if isinstance(item, dict):
                skill = item.get("skill") or item.get("name") or ""
                score = item.get("score", 0)
                # if score is like "80%" or "80" as string -> parse
                if isinstance(score, str):
                    score = score.strip().replace("%", "")
                    try:
                        score = int(float(score))
                    except:
                        score = 0
                try:
                    score = int(score)
                except:
                    score = 0
                out.append({"skill": str(skill).strip(), "score": max(0, min(100, score))})
            else:
                # if item is string like "Python: 80%"
                if isinstance(item, str):
                    m = re.match(r'([^:]+)[:\-]\s*([0-9]{1,3})%?', item)
                    if m:
                        out.append({"skill": m.group(1).strip(), "score": int(m.group(2))})
                    else:
                        out.append({"skill": item.strip(), "score": 0})
    return out


def clean_text_for_display(s):
    if not s:
        return ""
    # remove weird control characters
    s = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', s)
    return s.strip()


# ---------- ROUTES ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    uploaded_file = request.files.get("resume")
    if not uploaded_file:
        return "No file uploaded", 400

    job_role = request.form.get("job_role", "Not Provided")

    resume_text = extract_text_from_pdf(uploaded_file)

    # STRONGER prompt to reduce commentary and force pure JSON
    prompt = f"""
You are an ATS resume evaluation expert. Analyze the resume strictly based on the job role.

IMPORTANT:
- RETURN ONLY VALID JSON. DO NOT include extra text, explanation, or markdown outside the JSON.
- Do not wrap JSON in code fences or quotes.
- Arrays must be real JSON arrays.
- For scores use integers (0-100) or numbers only.

Return JSON in this format:
{{
  "ats_score": 0,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "missing_keywords": ["..."],
  "recommended_roles": ["..."],
  "skills_analysis": [
    {{ "skill": "Python", "score": 80 }},
    {{ "skill": "SQL", "score": 70 }}
  ],
  "summary": "2-3 sentence professional summary."
}}

Resume:
{resume_text}

Job Role:
{job_role}
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
    )

    raw_output = response.choices[0].message.content or ""

    # Try to find valid JSON inside the raw output:
    parsed = find_first_valid_json_block(raw_output)

    if parsed is None:
        # attempt to repair the whole raw string (single->double quotes etc.) and parse
        repaired = repair_common_json_issues(raw_output)
        parsed = try_json_load(repaired)

    # If still None, fallback to passing raw output into summary_html and keep others empty
    if not parsed:
        summary_text = clean_text_for_display(raw_output)
        summary_html = markdown2.markdown(summary_text)
        # empty lists and zero scores
        return render_template(
            "result.html",
            summary_html=summary_html,
            ats_score=0,
            strengths=[],
            weaknesses=[],
            missing_keywords=[],
            recommendations=[],
            skills_json=json.dumps({"labels": [], "datasets": [{"label": "Skill Strength", "data": []}]}, ensure_ascii=False),
            job_role=job_role
        )

    # Normalize expected fields
    ats_raw = parsed.get("ats_score", parsed.get("score", 0))
    # ats may be string "72" or "72/100" etc.
    ats_num = 0
    try:
        if isinstance(ats_raw, str):
            ats_num = int(re.findall(r'\d+', ats_raw)[0]) if re.findall(r'\d+', ats_raw) else 0
        else:
            ats_num = int(ats_raw)
    except:
        ats_num = 0
    ats_num = max(0, min(100, ats_num))

    strengths = normalize_list_field(parsed.get("strengths", []))
    weaknesses = normalize_list_field(parsed.get("weaknesses", []))
    missing_keywords = normalize_list_field(parsed.get("missing_keywords", []))
    recommendations = normalize_list_field(parsed.get("recommended_roles", parsed.get("recommended", [])))

    skills_raw = parsed.get("skills_analysis", [])
    skills_norm = normalize_skills(skills_raw)
    skill_labels = [s["skill"] for s in skills_norm]
    skill_values = [s["score"] for s in skills_norm]

    skills_chart = {
        "labels": skill_labels,
        "datasets": [{
            "label": "Skill Strength",
            "data": skill_values
        }]
    }

    summary_text = parsed.get("summary", "")
    summary_text = clean_text_for_display(summary_text)
    summary_html = markdown2.markdown(summary_text)

    return render_template(
        "result.html",
        summary_html=summary_html,
        ats_score=ats_num,
        strengths=strengths,
        weaknesses=weaknesses,
        missing_keywords=missing_keywords,
        recommendations=recommendations,
        skills_json=json.dumps(skills_chart, ensure_ascii=False),
        job_role=job_role
    )


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=5000)
