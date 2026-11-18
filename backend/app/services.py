import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageOps


SKILL_ALIASES = {
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "python": "Python",
    "java": "Java",
    "c++": "C++",
    "c#": "C#",
    "golang": "Go",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "next.js": "Next.js",
    "nextjs": "Next.js",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    "express": "Express",
    "expressjs": "Express",
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "sql": "SQL",
    "dbms": "DBMS",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "spring boot": "Spring Boot",
    "springboot": "Spring Boot",
    "hibernate": "Hibernate",
    "rest api": "REST API",
    "rest apis": "REST API",
    "restful api": "REST API",
    "graphql": "GraphQL",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "git": "Git",
    "ci/cd": "CI/CD",
    "linux": "Linux",
    "aws": "AWS",
    "azure": "Azure",
    "html": "HTML",
    "css": "CSS",
    "tailwind css": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "oop": "OOP",
    "opps": "OOP",
    "oops": "OOP",
    "object oriented programming": "OOP",
    "machine learning": "Machine Learning",
    "ai/ml": "AI/ML",
    "deep learning": "Deep Learning",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "power bi": "Power BI",
    "excel": "Excel",
    "figma": "Figma",
    "wireframing": "Wireframing",
    "prototyping": "Prototyping",
    "user research": "User Research",
    "seo": "SEO",
    "sem": "SEM",
    "google analytics": "Google Analytics",
    "social media marketing": "Social Media Marketing",
    "content marketing": "Content Marketing",
    "manual testing": "Manual Testing",
    "selenium": "Selenium",
    "api testing": "API Testing",
    "pytest": "Pytest",
    "recruitment": "Recruitment",
    "candidate screening": "Candidate Screening",
    "interview coordination": "Interview Coordination",
    "communication": "Communication",
    "leadership": "Leadership",
    "microservices": "Microservices",
    "computer fundamentals": "Computer Fundamentals",
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "its", "of", "on", "or", "our", "that", "the", "their",
    "this", "to", "we", "will", "with", "you", "your", "looking", "seeking", "role",
    "position", "candidate", "required", "preferred", "experience", "years", "year",
    "work", "working", "team", "strong", "good", "skills", "knowledge", "ability",
    "build", "building", "using", "based", "develop", "developing", "responsible",
}

PLACEHOLDER_LINE_PATTERN = re.compile(
    r"\[(?:college|school|university|degree|diploma|year|city|state|country|"
    r"percentage|cgpa|gpa|grade|name|your\s+name|email|phone|company|role|"
    r"title|project|certification|institution|start|end|month|date|address)[^\]]*\]",
    re.I,
)
GENERIC_BRACKET_PLACEHOLDER = re.compile(r"\[[A-Za-z][A-Za-z0-9\s/|,.\-]{2,60}\]")
PLACEHOLDER_EMAILS = {
    "your.email@example.com",
    "your_email@example.com",
    "youremail@example.com",
    "email@example.com",
    "user@example.com",
}

SECTION_HEADERS = {
    "education": re.compile(
        r"^\s*(education|academic background|qualifications?)\s*:?\s*$",
        re.I,
    ),
    "experience": re.compile(
        r"^\s*(work experience|professional experience|experience|employment history|internships?)\s*:?\s*$",
        re.I,
    ),
    "projects": re.compile(
        r"^\s*(projects?|academic projects?|key projects?|personal projects?)\s*:?\s*$",
        re.I,
    ),
    "certifications": re.compile(
        r"^\s*(certifications?|training\s*&?\s*certifications?|licenses?\s*(?:&|and)?\s*certifications?|courses?)\s*:?\s*$",
        re.I,
    ),
    "other": re.compile(
        r"^\s*(skills|technical skills|soft skills|awards|"
        r"professional summary|summary|profile|objective|references)\s*:?\s*$",
        re.I,
    ),
}


def sanitize_profile_text(value: str | None) -> str | None:
    """Remove raw resume template placeholders such as [College Name] or [Year]."""
    if not value or not isinstance(value, str):
        return None
    cleaned_lines: list[str] = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if PLACEHOLDER_LINE_PATTERN.search(line):
            continue
        bracket_matches = GENERIC_BRACKET_PLACEHOLDER.findall(line)
        if bracket_matches:
            stripped_without_brackets = GENERIC_BRACKET_PLACEHOLDER.sub("", line)
            alpha_remaining = re.sub(r"[^A-Za-z0-9]+", "", stripped_without_brackets)
            if len(alpha_remaining) < 4:
                continue
        if line.lower() in {"not provided", "n/a", "na", "none", "-", "--"}:
            continue
        cleaned_lines.append(line)
    result = "\n".join(cleaned_lines).strip()
    return result or None


def sanitize_contact_email(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER_EMAILS:
        return None
    if PLACEHOLDER_LINE_PATTERN.search(cleaned):
        return None
    return cleaned


def _preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)
    if max(image.size) < 1800:
        scale = min(2, 1800 / max(image.size))
        image = image.resize((round(image.width * scale), round(image.height * scale)))
    return ImageEnhance.Sharpness(image).enhance(1.5)


def _ocr(image: Image.Image) -> str:
    return pytesseract.image_to_string(_preprocess_image(image))


def _extract_docx_pages(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError("The DOCX archive does not contain a valid Word document.")
            xml_bytes = archive.read("word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError("The DOCX file is corrupted or invalid.") from exc

    root = ET.fromstring(xml_bytes)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    lines: list[str] = []
    for paragraph in root.iter(f"{ns}p"):
        texts = [node.text for node in paragraph.iter(f"{ns}t") if node.text]
        line = "".join(texts).strip()
        if line:
            lines.append(line)
    joined = "\n".join(lines).strip()
    return [joined]


def _extract_doc_pages(path: Path) -> list[str]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", str(path.parent), str(path)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            txt_path = path.with_suffix(".txt")
            if proc.returncode == 0 and txt_path.exists():
                content = txt_path.read_text(encoding="utf-8", errors="ignore").strip()
                txt_path.unlink(missing_ok=True)
                if content:
                    return [content]
        except OSError:
            pass

    raw = path.read_bytes()
    utf16_runs = re.findall(rb"(?:[A-Za-z0-9@.,:/+\-_() \t\r\n]\x00){6,}", raw)
    chunks: list[str] = []
    for run in utf16_runs:
        decoded = run.decode("utf-16-le", errors="ignore").strip()
        if decoded and any(ch.isalpha() for ch in decoded):
            chunks.append(decoded)
    if not chunks:
        ascii_runs = re.findall(rb"[A-Za-z0-9@.,:/+\-_() \t\r\n]{6,}", raw)
        for run in ascii_runs:
            decoded = run.decode("latin-1", errors="ignore").strip()
            if decoded and sum(c.isalpha() for c in decoded) >= 4:
                chunks.append(decoded)
    text = "\n".join(chunks).strip()
    if not text:
        raise ValueError(
            "Unable to extract readable text from this legacy .doc file. Please upload a PDF or DOCX resume."
        )
    return [text]


def extract_resume_pages(path: Path, mime_type: str) -> list[str]:
    if mime_type == "application/pdf":
        with fitz.open(path) as document:
            pages = []
            for page in document:
                text = page.get_text().strip()
                if not text:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    text = _ocr(image).strip()
                pages.append(text)
            return pages

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx_pages(path)

    if mime_type == "application/msword":
        return _extract_doc_pages(path)

    with Image.open(path) as image:
        image.verify()

    with Image.open(path) as image:
        return [_ocr(image).strip()]


def extract_resume_text(path: Path, mime_type: str) -> str:
    return "\n".join(extract_resume_pages(path, mime_type))


def _extract_section(lines: list[str], pattern: re.Pattern) -> str | None:
    for index, line in enumerate(lines):
        if pattern.fullmatch(line.strip()):
            section = []
            for following in lines[index + 1:]:
                if any(header.fullmatch(following.strip()) for header in SECTION_HEADERS.values()):
                    break
                section.append(following)
            value = sanitize_profile_text("\n".join(section).strip())
            return value
    return None


def _extract_education(lines: list[str]) -> str | None:
    education_lines = []
    education_pattern = re.compile(r"^\s*(education|academic background|qualifications?)\b", re.I)
    education_keywords = re.compile(
        r"\b(university|college|school|institute|b\.?\s*tech|m\.?\s*tech|bca|mca|bsc|msc|"
        r"bachelor|master|degree|class\s*(xii|12|x|10)|cgpa|gpa|semester|sem|current|diploma|"
        r"computer science|engineering|information technology|b\.?\s*e)\b|%",
        re.I,
    )
    stop_pattern = re.compile(
        r"^\s*(experience|work experience|professional experience|"
        r"technical skills|soft skills|projects?|certifications?|"
        r"training|skills)\s*:?\s*$",
        re.I,
    )
    start_index = None
    for index, line in enumerate(lines):
        if education_pattern.search(line):
            start_index = index
            break
    if start_index is None:
        return None
    for line in lines[start_index + 1:]:
        line = line.strip()
        if stop_pattern.fullmatch(line):
            break
        line = re.split(
            r"\b(SOFT SKILLS|TECHNICAL SKILLS|TRAINING\s*&?\s*CERTIFICATIONS)\b",
            line,
            flags=re.I,
        )[0].strip()
        if education_keywords.search(line):
            education_lines.append(line)
    return sanitize_profile_text("\n".join(education_lines).strip())


def extract_resume_fields(text: str) -> dict:
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
    phone_match = re.search(
        r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3,5}\)?[\s.-]?)?\d{5,8}(?!\d)",
        text,
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    labeled_name = next(
        (
            match.group(1).strip()
            for line in lines[:12]
            if (match := re.match(r"^name\s*[:\-]\s*(.{2,150})$", line, re.I))
        ),
        None,
    )
    role_terms = re.compile(
        r"\b(engineer|developer|manager|designer|analyst|"
        r"consultant|professional|specialist|architect|"
        r"intern|resume|curriculum vitae|cv)\b",
        re.I,
    )
    name = labeled_name or next(
        (
            line
            for line in lines[:8]
            if re.fullmatch(r"[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){1,3}", line)
            and not role_terms.search(line)
        ),
        None,
    )
    raw_email = email_match.group(0) if email_match else None
    return {
        "full_name": sanitize_profile_text(name),
        "email": sanitize_contact_email(raw_email),
        "phone": phone_match.group(0) if phone_match else None,
        "education": _extract_education(lines),
        "experience": _extract_section(lines, SECTION_HEADERS["experience"]),
        "projects": _extract_section(lines, SECTION_HEADERS["projects"]),
        "certifications": _extract_section(lines, SECTION_HEADERS["certifications"]),
        "skills": extract_skills(text),
    }


def extract_skills(text: str) -> list[str]:
    if not text:
        return []
    lower_text = text.lower()
    skills = {
        canonical
        for alias, canonical in SKILL_ALIASES.items()
        if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", lower_text)
    }
    return sorted(skills)


def normalize_skill(value: str) -> str:
    norm = re.sub(r"\W+", "", value.lower())
    if norm in {"opps", "oops"}:
        return "oop"
    if norm == "reactjs":
        return "react"
    if norm == "nodejs":
        return "nodejs"
    if norm == "restapis":
        return "restapi"
    return norm


def _canonicalize_skill_map(names: set[str] | list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in names:
        if not isinstance(name, str):
            continue
        cleaned = name.strip()
        norm = normalize_skill(cleaned)
        if not norm:
            continue
        canonical = SKILL_ALIASES.get(cleaned.lower(), cleaned)
        mapping.setdefault(norm, canonical)
    return mapping


def calculate_match(candidate_skills: set[str], required_skills: set[str]) -> dict:
    candidate_norm = {normalize_skill(skill) for skill in candidate_skills if skill.strip()}
    required_norm = {normalize_skill(skill) for skill in required_skills if skill.strip()}
    matched = sorted(candidate_norm & required_norm)
    missing = sorted(required_norm - candidate_norm)
    percentage = round(len(matched) / len(required_norm) * 100, 2) if required_norm else 100.0
    return {
        "match_percentage": percentage,
        "matched_skills": json.dumps(matched),
        "missing_skills": json.dumps(missing),
        "recommendations": json.dumps(missing),
    }


def _tokenize_keywords(text: str | None) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r"[a-z0-9+#.]{2,}", text.lower())
    return {t for t in tokens if t not in STOP_WORDS and not t.isdigit()}


def _parse_years_experience(text: str | None) -> float | None:
    if not text:
        return None
    lower = text.lower()
    if "fresher" in lower or "entry level" in lower or "0 year" in lower:
        return 0.0
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", lower)
    if matches:
        return max(float(m) for m in matches)
    month_matches = re.findall(r"(\d+)\s*(?:months?|mos?)", lower)
    if month_matches:
        return round(max(int(m) for m in month_matches) / 12.0, 2)
    return None


def _evaluate_experience(candidate_exp: str | None, resume_text: str | None, job) -> tuple[float, str]:
    combined_exp = "\n".join(part for part in [candidate_exp, resume_text] if part)
    years = _parse_years_experience(candidate_exp)
    if years is None:
        years = _parse_years_experience(resume_text)

    job_min = job.experience_min
    job_max = job.experience_max
    job_tokens = _tokenize_keywords(f"{job.title} {job.description}")
    exp_tokens = _tokenize_keywords(candidate_exp or "")
    domain_overlap = len(job_tokens & exp_tokens)

    if not sanitize_profile_text(candidate_exp) and years is None:
        if job_min in (None, 0):
            return 25.0, "No explicit work experience provided; job allows entry-level candidates."
        return 0.0, f"No experience provided against {job_min}+ years requirement."

    if years is not None:
        if job_min is not None and years < job_min:
            ratio = years / job_min if job_min > 0 else 0
            score = max(15.0, min(68.0, round(ratio * 70.0 + min(15.0, domain_overlap * 5.0), 2)))
            return score, f"Candidate has ~{years:g} yrs experience (role expects {job_min}+ yrs)."
        if job_max is not None and years > job_max + 2:
            score = 85.0
            return score, f"Candidate has ~{years:g} yrs experience (exceeds {job_min or 0}-{job_max} yrs target)."
        bonus = min(20.0, domain_overlap * 5.0)
        score = min(100.0, 80.0 + bonus)
        range_label = f"{job_min or 0}-{job_max} yrs" if job_max is not None else (f"{job_min}+ yrs" if job_min else "all levels")
        return score, f"Experience (~{years:g} yrs) aligns well with role expectations ({range_label})."

    # Qualitative experience text without explicit numeric years
    if domain_overlap >= 2:
        return 75.0, "Candidate experience text aligns with job responsibilities."
    return 50.0, "Experience listed, though duration in years is not explicitly stated."


def _evaluate_supporting_sections(
    education: str | None,
    projects: str | None,
    certifications: str | None,
    resume_text: str | None,
    job,
) -> tuple[float, dict[str, bool]]:
    edu = sanitize_profile_text(education)
    proj = sanitize_profile_text(projects)
    cert = sanitize_profile_text(certifications)
    job_tokens = _tokenize_keywords(f"{job.title} {job.description}")

    # Education (0-100)
    edu_score = 0.0
    if edu:
        edu_lower = edu.lower()
        edu_tokens = _tokenize_keywords(edu)
        tech_deg = any(
            kw in edu_lower
            for kw in ("computer", "software", "engineering", "b.tech", "btech", "bca", "mca", "bsc", "msc", "it", "data", "design", "mba", "hr")
        )
        if tech_deg or (job_tokens & edu_tokens):
            edu_score = 100.0
        else:
            edu_score = 70.0

    # Projects (0-100)
    proj_source = proj or ""
    proj_score = 0.0
    if proj_source:
        proj_overlap = len(job_tokens & _tokenize_keywords(proj_source))
        proj_score = 100.0 if proj_overlap >= 1 else 70.0
    elif resume_text and re.search(r"\bprojects?\b", resume_text, re.I):
        proj_score = 65.0

    # Certifications (0-100)
    cert_source = cert or ""
    cert_score = 0.0
    if cert_source:
        cert_overlap = len(job_tokens & _tokenize_keywords(cert_source))
        cert_score = 100.0 if cert_overlap >= 1 else 70.0
    elif resume_text and re.search(r"\bcertifications?\b", resume_text, re.I):
        cert_score = 65.0

    combined = round((edu_score + proj_score + cert_score) / 3.0, 2)
    flags = {"has_education": bool(edu), "has_projects": bool(proj), "has_certifications": bool(cert)}
    return combined, flags


def evaluate_candidate_job_match(candidate, job, resume=None) -> dict:
    """Compute real multi-factor match score (0-100) across skills, experience, education, projects, and certifications."""
    resume_data = {}
    if resume and resume.extracted_data:
        try:
            resume_data = json.loads(resume.extracted_data)
        except json.JSONDecodeError:
            resume_data = {}

    resume_text = resume.extracted_text if resume else None
    edu = sanitize_profile_text(candidate.education) or sanitize_profile_text(resume_data.get("education"))
    exp = sanitize_profile_text(candidate.experience) or sanitize_profile_text(resume_data.get("experience"))
    proj = sanitize_profile_text(candidate.projects) or sanitize_profile_text(resume_data.get("projects"))
    cert = sanitize_profile_text(candidate.certifications) or sanitize_profile_text(resume_data.get("certifications"))
    summary = sanitize_profile_text(candidate.summary)
    headline = sanitize_profile_text(candidate.headline)

    candidate_skill_pool: set[str] = {item.skill.name for item in candidate.skills}
    if isinstance(resume_data.get("skills"), list):
        candidate_skill_pool.update(s for s in resume_data["skills"] if isinstance(s, str))
    for text_block in (resume_text, exp, proj, cert, summary, headline):
        if text_block:
            candidate_skill_pool.update(extract_skills(text_block))

    candidate_skills = _canonicalize_skill_map(candidate_skill_pool)

    required_skill_pool: set[str] = {
        item.skill.name for item in job.skills if item.is_required
    }
    required_skill_pool.update(extract_skills(job.description))
    required_skill_pool.update(extract_skills(job.title))
    required_skills = _canonicalize_skill_map(required_skill_pool)

    preferred_skill_pool: set[str] = {
        item.skill.name for item in job.skills if not item.is_required
    }
    preferred_skills = _canonicalize_skill_map(preferred_skill_pool)

    matched_norm = sorted(set(candidate_skills) & set(required_skills))
    missing_norm = sorted(set(required_skills) - set(candidate_skills))
    matched = [candidate_skills.get(k, required_skills[k]) for k in matched_norm]
    missing = [required_skills[k] for k in missing_norm]

    pref_matched_norm = sorted(set(candidate_skills) & set(preferred_skills))
    pref_missing_norm = sorted(set(preferred_skills) - set(candidate_skills))
    pref_matched = [candidate_skills.get(k, preferred_skills[k]) for k in pref_matched_norm]
    pref_missing = [preferred_skills[k] for k in pref_missing_norm]

    # 1. Required skills score (55%)
    if required_skills:
        req_score = (len(matched) / len(required_skills)) * 100.0
    else:
        req_score = 70.0

    # 2. Preferred skills + Job Title/Description Semantic Keyword Alignment (15%)
    job_tokens = _tokenize_keywords(f"{job.title} {job.description}")
    cand_text = " ".join(filter(None, [headline, summary, exp, proj, cert, resume_text, " ".join(candidate_skills.values())]))
    cand_tokens = _tokenize_keywords(cand_text)
    keyword_overlap_score = (
        min(100.0, (len(job_tokens & cand_tokens) / max(1, min(len(job_tokens), 12))) * 100.0)
        if job_tokens else 50.0
    )
    if preferred_skills:
        pref_ratio = (len(pref_matched) / len(preferred_skills)) * 100.0
        relevance_score = round(0.5 * pref_ratio + 0.5 * keyword_overlap_score, 2)
    else:
        relevance_score = round(keyword_overlap_score, 2)

    # 3. Experience score (15%)
    exp_score, exp_summary = _evaluate_experience(exp, resume_text, job)

    # 4. Education, Projects & Certifications score (15%)
    supporting_score, section_flags = _evaluate_supporting_sections(edu, proj, cert, resume_text, job)

    total_percentage = round(
        0.55 * req_score + 0.15 * relevance_score + 0.15 * exp_score + 0.15 * supporting_score,
        2,
    )
    total_percentage = max(0.0, min(100.0, total_percentage))

    strengths: list[str] = []
    if matched:
        strengths.append(f"Matched {len(matched)} of {len(required_skills)} required skills: {', '.join(matched)}.")
    if pref_matched:
        strengths.append(f"Matches preferred skills: {', '.join(pref_matched)}.")
    if exp_score >= 70:
        strengths.append(exp_summary)
    if section_flags["has_education"]:
        strengths.append("Relevant educational background provided.")
    if section_flags["has_projects"]:
        strengths.append("Includes practical project experience.")
    if section_flags["has_certifications"]:
        strengths.append("Lists verified certifications/training.")
    if not strengths:
        strengths.append("Profile submitted for recruiter review.")

    weaknesses: list[str] = []
    if missing:
        weaknesses.append(f"Missing required skills: {', '.join(missing)}.")
    if pref_missing:
        weaknesses.append(f"Missing preferred skills: {', '.join(pref_missing)}.")
    if exp_score < 60:
        weaknesses.append(exp_summary)
    if not section_flags["has_projects"]:
        weaknesses.append("No projects listed in profile or resume.")
    if not section_flags["has_certifications"]:
        weaknesses.append("No certifications listed.")
    if not weaknesses:
        weaknesses.append("No major gaps identified against job requirements.")

    recommendations = (
        [f"Add evidence or project work demonstrating {skill}." for skill in missing]
        if missing
        else ["Candidate meets all listed core skill requirements for this role."]
    )

    explanation = (
        f"Overall match of {total_percentage:.2f}% for {job.title}: "
        f"Required skills {req_score:.0f}% (55% weight, {len(matched)}/{len(required_skills) or 0}), "
        f"Role & keyword alignment {relevance_score:.0f}% (15% weight), "
        f"Experience fit {exp_score:.0f}% (15% weight), "
        f"Education/Projects/Certifications {supporting_score:.0f}% (15% weight)."
    )

    fingerprint_payload = json.dumps(
        {
            "job_id": job.id,
            "job_updated": str(job.updated_at),
            "job_skills": sorted(required_skills.keys()),
            "pref_skills": sorted(preferred_skills.keys()),
            "cand_skills": sorted(candidate_skills.keys()),
            "edu": edu or "",
            "exp": exp or "",
            "proj": proj or "",
            "cert": cert or "",
            "resume_id": resume.id if resume else None,
            "resume_updated": str(resume.updated_at) if resume else "",
        },
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()

    return {
        "match_percentage": total_percentage,
        "matched_skills": matched,
        "missing_skills": missing,
        "preferred_matched_skills": pref_matched,
        "preferred_missing_skills": pref_missing,
        "relevant_experience": exp_summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "matching_explanation": explanation,
        "recommendations": recommendations,
        "score_breakdown": {
            "required_skills_score": round(req_score, 2),
            "relevance_score": round(relevance_score, 2),
            "experience_score": round(exp_score, 2),
            "education_projects_certs_score": round(supporting_score, 2),
        },
        "input_fingerprint": fingerprint,
    }
