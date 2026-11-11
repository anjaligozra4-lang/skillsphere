
import json
import re
from pathlib import Path

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageOps


SKILL_ALIASES = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "java": "Java",
    "react": "React",
    "reactjs": "React",
    "node.js": "Node.js",
    "express": "Express",
    "mysql": "MySQL",
    "sql": "SQL",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "git": "Git",
    "aws": "AWS",
    "azure": "Azure",
    "html": "HTML",
    "css": "CSS",
    "machine learning": "Machine Learning",
    "excel": "Excel",
    "communication": "Communication",
    "leadership": "Leadership",
}


SECTION_HEADERS = {
    "education": re.compile(
        r"^\s*(education|academic background|qualifications?)\b.*$",
        re.I,
    ),
    "experience": re.compile(
        r"^\s*(work experience|professional experience|experience|employment history)\s*:?\s*$",
        re.I,
    ),
    "other": re.compile(
        r"^\s*(skills|technical skills|soft skills|projects|"
        r"certifications?|licenses?|awards|professional summary|"
        r"summary|profile|references)\s*:?\s*$",
        re.I,
    ),
}


def _preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.grayscale(image)
    image = ImageOps.autocontrast(image)

    if max(image.size) < 1800:
        scale = min(2, 1800 / max(image.size))
        image = image.resize(
            (
                round(image.width * scale),
                round(image.height * scale),
            )
        )

    return ImageEnhance.Sharpness(image).enhance(1.5)


def _ocr(image: Image.Image) -> str:
    return pytesseract.image_to_string(_preprocess_image(image))


def extract_resume_pages(path: Path, mime_type: str) -> list[str]:
    if mime_type == "application/pdf":
        with fitz.open(path) as document:
            pages = []

            for page in document:
                text = page.get_text().strip()

                if not text:
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(2, 2),
                        alpha=False,
                    )

                    image = Image.frombytes(
                        "RGB",
                        (pixmap.width, pixmap.height),
                        pixmap.samples,
                    )

                    text = _ocr(image).strip()

                pages.append(text)

            return pages

    with Image.open(path) as image:
        image.verify()

    with Image.open(path) as image:
        return [_ocr(image).strip()]


def extract_resume_text(path: Path, mime_type: str) -> str:
    return "\n".join(extract_resume_pages(path, mime_type))


def _extract_section(
    lines: list[str],
    pattern: re.Pattern,
) -> str | None:

    for index, line in enumerate(lines):
        if pattern.fullmatch(line.strip()):
            section = []

            for following in lines[index + 1:]:
                if any(
                    header.fullmatch(following.strip())
                    for header in SECTION_HEADERS.values()
                ):
                    break

                section.append(following)

            value = "\n".join(section).strip()
            return value or None

    return None


def _extract_education(lines: list[str]) -> str | None:
    education_lines = []

    education_pattern = re.compile(
        r"^\s*(education|academic background|qualifications?)\b",
        re.I,
    )

    education_keywords = re.compile(
        r"\b(university|college|school|b\.?\s*tech|"
        r"bachelor|master|degree|class\s*(xii|12|x|10)|"
        r"cgpa|gpa|semester|sem|current|diploma|"
        r"computer science|engineering)\b|%",
        re.I,
    )

    stop_pattern = re.compile(
        r"^\s*(experience|work experience|professional experience|"
        r"technical skills|soft skills|projects|certifications?|"
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

        # Remove text from other columns when OCR mixes columns.
        line = re.split(
            r"\b(SOFT SKILLS|TECHNICAL SKILLS|"
            r"TRAINING\s*&?\s*CERTIFICATIONS)\b",
            line,
            flags=re.I,
        )[0].strip()

        if education_keywords.search(line):
            education_lines.append(line)

    result = "\n".join(education_lines).strip()

    return result or None


def extract_resume_fields(text: str) -> dict:
    email_match = re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        text,
    )

    phone_match = re.search(
        r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?"
        r"(?:\(?\d{3,5}\)?[\s.-]?)?"
        r"\d{5,8}(?!\d)",
        text,
    )

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    labeled_name = next(
        (
            match.group(1).strip()
            for line in lines[:12]
            if (
                match := re.match(
                    r"^name\s*[:\-]\s*(.{2,150})$",
                    line,
                    re.I,
                )
            )
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
            if re.fullmatch(
                r"[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){1,3}",
                line,
            )
            and not role_terms.search(line)
        ),
        None,
    )

    return {
        "full_name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "education": _extract_education(lines),
        "experience": _extract_section(
            lines,
            SECTION_HEADERS["experience"],
        ),
        "skills": extract_skills(text),
    }


def extract_skills(text: str) -> list[str]:
    lower_text = text.lower()

    skills = {
        canonical
        for alias, canonical in SKILL_ALIASES.items()
        if re.search(
            rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
            lower_text,
        )
    }

    return sorted(skills)


def normalize_skill(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())


def calculate_match(
    candidate_skills: set[str],
    required_skills: set[str],
) -> dict:

    candidate_skills = {
        normalize_skill(skill)
        for skill in candidate_skills
        if skill.strip()
    }

    required_skills = {
        normalize_skill(skill)
        for skill in required_skills
        if skill.strip()
    }

    matched = sorted(candidate_skills & required_skills)
    missing = sorted(required_skills - candidate_skills)

    percentage = (
        round(len(matched) / len(required_skills) * 100, 2)
        if required_skills
        else 100.0
    )

    return {
        "match_percentage": percentage,
        "matched_skills": json.dumps(matched),
        "missing_skills": json.dumps(missing),
        "recommendations": json.dumps(missing),
    }
