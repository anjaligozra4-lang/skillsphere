import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../api";
import { parseApiError } from "../utils/profileUtils";

export function normalizeSkill(value) {
  if (!value) return "";
  const norm = String(value).toLowerCase().replace(/[^a-z0-9]/g, "");
  if (norm === "opps" || norm === "oops") return "oop";
  if (norm === "reactjs") return "react";
  if (norm === "nodejs") return "nodejs";
  if (norm === "restapis") return "restapi";
  return norm;
}

const DEFAULT_INSTRUCTIONS =
  "1. Read each multiple-choice question carefully and choose the single best answer.\n" +
  "2. You can navigate between questions and change answers anytime before submitting.\n" +
  "3. The test submits automatically when the countdown timer expires. Only one attempt is allowed.";

export default function RecruiterAssessments({ jobs = [], onAssessmentsChanged, onFeedback }) {
  const eligibleJobs = jobs.filter((job) => ["published", "open"].includes(job.status));
  const [assessments, setAssessments] = useState([]);
  const [bankQuestions, setBankQuestions] = useState([]);
  const [bankSkills, setBankSkills] = useState([]);
  const [bankCategories, setBankCategories] = useState([]);
  const [jobSkills, setJobSkills] = useState([]);
  const [aiSkills, setAiSkills] = useState([]);
  const [aiDifficulty, setAiDifficulty] = useState("Medium");
  const [aiQuestionCount, setAiQuestionCount] = useState(5);
  const [aiMarks, setAiMarks] = useState(1);
  const [aiGenerating, setAiGenerating] = useState(false);

  const [qbSearch, setQbSearch] = useState("");
  const [qbSkill, setQbSkill] = useState("");
  const [qbCategory, setQbCategory] = useState("");
  const [qbDifficulty, setQbDifficulty] = useState("");
  const [matchJobSkills, setMatchJobSkills] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [showBuilder, setShowBuilder] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [saving, setSaving] = useState(false);

  const [showVideoBuilder, setShowVideoBuilder] = useState(false);
  const [savingVideo, setSavingVideo] = useState(false);
  const [videoForm, setVideoForm] = useState({
    job_id: "",
    title: "",
    description: "",
    prep_time_seconds: 30,
    response_time_seconds: 120,
    allow_review: true,
    max_recordings_per_question: 2,
    questions: [
      { question_text: "", instructions: "Speak clearly and state your approach.", prep_time_seconds: 30, response_time_seconds: 120 }
    ],
  });

  const [form, setForm] = useState({
    job_id: "",
    title: "",
    description: "",
    instructions: DEFAULT_INSTRUCTIONS,
    duration_minutes: 30,
    passing_marks: 1,
    expires_at: "",
  });
  const [selectedQuestions, setSelectedQuestions] = useState([]);
  const [editingQuestion, setEditingQuestion] = useState(null);
  const [savingQuestion, setSavingQuestion] = useState(false);

  useEffect(() => {
    setAiSkills((current) => current.filter((skill) => jobSkills.includes(skill)).length
      ? current.filter((skill) => jobSkills.includes(skill))
      : jobSkills);
  }, [jobSkills]);

  const loadAssessments = useCallback(async () => {
    try {
      const res = await api.get("/api/recruiter/assessments");
      const list = Array.isArray(res?.data) ? res.data : [];
      setAssessments(list);
      onAssessmentsChanged?.(list);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load assessments."), true);
    }
  }, [onAssessmentsChanged, onFeedback]);

  const loadQuestionBank = useCallback(async () => {
    try {
      const res = await api.get("/api/recruiter/question-bank", {
        params: {
          q: qbSearch || undefined,
          skill: qbSkill || undefined,
          category: qbCategory || undefined,
          difficulty: qbDifficulty || undefined,
          job_id: form.job_id ? Number(form.job_id) : undefined,
          match_job_skills: matchJobSkills && Boolean(form.job_id),
        },
      });
      setBankQuestions(res?.data?.items || []);
      setBankSkills(res?.data?.skills || []);
      setBankCategories(res?.data?.categories || []);
      setJobSkills(res?.data?.job_skills || []);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load Question Bank."), true);
    }
  }, [qbSearch, qbSkill, qbCategory, qbDifficulty, form.job_id, matchJobSkills, onFeedback]);

  const generateAiQuestions = async () => {
    if (!form.job_id || !aiSkills.length) {
      onFeedback?.("Choose a job and at least one job skill before generating questions.", true);
      return;
    }
    setAiGenerating(true);
    try {
      const response = await api.post("/api/recruiter/question-bank/generate", {
        job_id: Number(form.job_id),
        skills: aiSkills,
        difficulty: aiDifficulty,
        question_count: Number(aiQuestionCount),
        marks: Number(aiMarks),
      });
      const generated = response?.data?.items || [];
      setBankQuestions((current) => [...generated, ...current.filter((question) => !generated.some((item) => item.id === question.id))]);
      setQbSearch("");
      setQbSkill("");
      setQbCategory("");
      setQbDifficulty("");
      onFeedback?.(`${generated.length} AI questions generated. Review them below and add the ones you want to the assessment.`, false);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to generate assessment questions."), true);
    } finally {
      setAiGenerating(false);
    }
  };

  useEffect(() => {
    loadAssessments();
  }, [loadAssessments]);

  useEffect(() => {
    if (showBuilder) {
      loadQuestionBank();
    }
  }, [showBuilder, loadQuestionBank]);

  const totalQuestions = selectedQuestions.length;
  const totalMarks = selectedQuestions.reduce((acc, q) => acc + (Number(q.marks) || 1), 0);
  const selectedIds = new Set(selectedQuestions.map((q) => q.id));

  const { coveredJobSkills, missingJobSkills } = useMemo(() => {
    const covered = [];
    const missing = [];
    jobSkills.forEach((skill) => {
      const norm = normalizeSkill(skill);
      const matchingQuestions = selectedQuestions.filter(
        (q) => normalizeSkill(q.skill) === norm
      );
      if (matchingQuestions.length > 0) {
        covered.push({
          name: skill,
          count: matchingQuestions.length,
          marks: matchingQuestions.reduce((sum, q) => sum + (Number(q.marks) || 1), 0),
        });
      } else {
        missing.push(skill);
      }
    });
    return { coveredJobSkills: covered, missingJobSkills: missing };
  }, [jobSkills, selectedQuestions]);

  const startNewAssessment = () => {
    const defaultJobId = eligibleJobs[0]?.id ? String(eligibleJobs[0].id) : "";
    setEditingId(null);
    setForm({
      job_id: defaultJobId,
      title: "",
      description: "",
      instructions: DEFAULT_INSTRUCTIONS,
      duration_minutes: 30,
      passing_marks: 1,
      expires_at: "",
    });
    setSelectedQuestions([]);
    setShowPreview(false);
    setShowVideoBuilder(false);
    setShowBuilder(true);
  };

  const startNewVideoAssessment = () => {
    const defaultJobId = eligibleJobs[0]?.id ? String(eligibleJobs[0].id) : "";
    setVideoForm({
      job_id: defaultJobId,
      title: "",
      description: "",
      prep_time_seconds: 30,
      response_time_seconds: 120,
      allow_review: true,
      max_recordings_per_question: 2,
      questions: [
        { question_text: "", instructions: "Speak clearly and present your structured response.", prep_time_seconds: 30, response_time_seconds: 120 }
      ],
    });
    setShowBuilder(false);
    setShowVideoBuilder(true);
  };

  const addVideoQuestion = () => {
    setVideoForm((prev) => ({
      ...prev,
      questions: [
        ...prev.questions,
        {
          question_text: "",
          instructions: "Speak clearly and present your structured response.",
          prep_time_seconds: prev.prep_time_seconds || 30,
          response_time_seconds: prev.response_time_seconds || 120,
        },
      ],
    }));
  };

  const removeVideoQuestion = (index) => {
    setVideoForm((prev) => ({
      ...prev,
      questions: prev.questions.filter((_, i) => i !== index),
    }));
  };

  const updateVideoQuestion = (index, field, value) => {
    setVideoForm((prev) => ({
      ...prev,
      questions: prev.questions.map((q, i) => (i === index ? { ...q, [field]: value } : q)),
    }));
  };

  const saveVideoAssessment = async (targetStatus = "published") => {
    if (!videoForm.job_id) {
      onFeedback?.("Please select a job for this video assessment.", true);
      return;
    }
    if (!videoForm.title.trim()) {
      onFeedback?.("Please provide a title for the video assessment.", true);
      return;
    }
    const validQuestions = videoForm.questions.filter((q) => q.question_text.trim());
    if (!validQuestions.length) {
      onFeedback?.("Please add at least one interview question.", true);
      return;
    }
    setSavingVideo(true);
    try {
      await api.post("/api/recruiter/video-assessments", {
        job_id: Number(videoForm.job_id),
        title: videoForm.title.trim(),
        description: videoForm.description.trim() || null,
        prep_time_seconds: Number(videoForm.prep_time_seconds) || 30,
        response_time_seconds: Number(videoForm.response_time_seconds) || 120,
        allow_review: Boolean(videoForm.allow_review),
        max_recordings_per_question: Number(videoForm.max_recordings_per_question) || 2,
        status: targetStatus,
        questions: validQuestions.map((q, idx) => ({
          question_text: q.question_text.trim(),
          instructions: q.instructions?.trim() || null,
          prep_time_seconds: Number(q.prep_time_seconds) || 30,
          response_time_seconds: Number(q.response_time_seconds) || 120,
          order_index: idx,
        })),
      });
      onFeedback?.(
        `Video assessment "${videoForm.title}" ${targetStatus === "published" ? "published" : "saved as draft"}.`,
        false
      );
      setShowVideoBuilder(false);
      await loadAssessments();
    } catch (err) {
      onFeedback?.(await parseApiError(err, "Failed to save video assessment."), true);
    } finally {
      setSavingVideo(false);
    }
  };

  const updateGeneratedQuestion = async () => {
    if (!editingQuestion) return;
    setSavingQuestion(true);
    try {
      const payload = {
        question_type: "mcq",
        skill: editingQuestion.skill,
        category: editingQuestion.category,
        difficulty: editingQuestion.difficulty,
        question_text: editingQuestion.question_text,
        options: editingQuestion.options,
        correct_option_index: Number(editingQuestion.correct_option_index),
        marks: Number(editingQuestion.marks),
        explanation: editingQuestion.explanation || null,
        is_active: true,
      };
      const response = await api.put(
        `/api/recruiter/question-bank/${editingQuestion.id}`,
        payload,
      );
      const updated = response.data;
      setBankQuestions((current) => current.map((question) => question.id === updated.id ? updated : question));
      setSelectedQuestions((current) => current.map((question) => question.id === updated.id ? {
        ...question,
        ...updated,
      } : question));
      setEditingQuestion(null);
      onFeedback?.("Question edits saved to your Question Bank.", false);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to save question edits."), true);
    } finally {
      setSavingQuestion(false);
    }
  };

  const editAssessment = async (item) => {
    try {
      const res = await api.get(`/api/recruiter/assessments/${item.id}`);
      const detail = res.data;
      setEditingId(detail.id);
      const isPastExpiry = detail.expires_at && new Date(detail.expires_at) <= new Date();
      setForm({
        job_id: String(detail.job_id),
        title: detail.title || "",
        description: detail.description || "",
        instructions: detail.instructions || DEFAULT_INSTRUCTIONS,
        duration_minutes: detail.duration_minutes || 30,
        passing_marks: detail.passing_marks ?? 0,
        expires_at: isPastExpiry ? "" : (detail.expires_at ? detail.expires_at.slice(0, 16) : ""),
      });
      setSelectedQuestions(
        (detail.questions || []).map((q) => ({
          id: q.question_bank_id || q.id,
          skill: q.skill,
          category: q.category,
          difficulty: q.difficulty,
          question_text: q.question_text,
          options: q.options,
          marks: q.marks,
        }))
      );
      setShowPreview(false);
      setShowBuilder(true);
      if (isPastExpiry) {
        onFeedback?.(
          "Notice: The draft's previous expiry date was in the past and has been reset. Please set a future expiry date or leave blank.",
          false
        );
      }
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to open assessment for editing."), true);
    }
  };

  const addQuestion = (q) => {
    if (selectedIds.has(q.id)) return;
    setSelectedQuestions((prev) => [...prev, q]);
  };

  const removeQuestion = (qid) => {
    setSelectedQuestions((prev) => prev.filter((q) => q.id !== qid));
  };

  const moveQuestion = (index, direction) => {
    const target = index + direction;
    if (target < 0 || target >= selectedQuestions.length) return;
    setSelectedQuestions((prev) => {
      const copy = [...prev];
      const temp = copy[index];
      copy[index] = copy[target];
      copy[target] = temp;
      return copy;
    });
  };

  const saveAssessment = async (targetStatus) => {
    if (!form.job_id) {
      onFeedback?.("Select a job posting for this assessment.", true);
      return;
    }
    if (!form.title.trim()) {
      onFeedback?.("Enter an assessment title.", true);
      return;
    }
    const dur = Number(form.duration_minutes);
    if (isNaN(dur) || dur < 1 || dur > 240) {
      onFeedback?.("Assessment duration must be between 1 and 240 minutes.", true);
      return;
    }
    const passMarks = Number(form.passing_marks);
    if (isNaN(passMarks) || passMarks < 0) {
      onFeedback?.("Passing marks cannot be negative.", true);
      return;
    }
    if (form.expires_at) {
      const expDate = new Date(form.expires_at);
      if (isNaN(expDate.getTime()) || expDate <= new Date()) {
        onFeedback?.("Assessment expiry date must be in the future.", true);
        return;
      }
    }
    if (targetStatus === "published") {
      if (selectedQuestions.length < 1) {
        onFeedback?.("Select at least 1 MCQ question from the Question Bank before publishing.", true);
        return;
      }
      if (passMarks >= totalMarks) {
        onFeedback?.(
          `Passing marks (${passMarks}) must be strictly less than total marks (${totalMarks}) because candidates must score strictly greater than passing marks to qualify.`,
          true
        );
        return;
      }
      if (missingJobSkills.length > 0) {
        const proceed = window.confirm(
          `This assessment does not cover ${missingJobSkills.length} required skill(s): ${missingJobSkills.join(", ")}. Do you want to publish anyway?`
        );
        if (!proceed) return;
      }
    }

    setSaving(true);
    try {
      const payload = {
        job_id: Number(form.job_id),
        title: form.title.trim(),
        description: form.description.trim() || null,
        instructions: form.instructions.trim() || DEFAULT_INSTRUCTIONS,
        duration_minutes: dur,
        passing_marks: passMarks,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
        question_ids: selectedQuestions.map((q) => q.id),
        status: targetStatus,
      };
      if (editingId) {
        await api.put(`/api/recruiter/assessments/${editingId}`, payload);
      } else {
        await api.post("/api/recruiter/assessments", payload);
      }
      onFeedback?.(
        targetStatus === "published"
          ? "Assessment published! You can now assign it to shortlisted candidates."
          : "Assessment saved as draft.",
        false
      );
      setShowBuilder(false);
      setEditingId(null);
      await loadAssessments();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to save assessment."), true);
    } finally {
      setSaving(false);
    }
  };

  const publishExisting = async (item) => {
    if (item.total_questions < 1) {
      onFeedback?.("Select at least 1 MCQ question from the Question Bank before publishing.", true);
      return;
    }
    try {
      await api.post(`/api/recruiter/assessments/${item.id}/publish`);
      onFeedback?.(`"${item.title}" is now published and ready for candidate assignment.`, false);
      await loadAssessments();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to publish assessment."), true);
    }
  };

  const deleteExisting = async (item) => {
    if (!window.confirm(`Delete assessment "${item.title}"?`)) return;
    try {
      await api.delete(`/api/recruiter/assessments/${item.id}`);
      onFeedback?.("Assessment deleted.", false);
      await loadAssessments();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to delete assessment."), true);
    }
  };

  return (
    <section className="panel" id="recruiter-assessments">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Assessment Management · Published Assessments</span>
          <h2>Assessments / Manage Tests</h2>
        </div>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button type="button" className="button button-small" disabled={!eligibleJobs.length} onClick={startNewAssessment}>
            + Create Assessment
          </button>
          <button type="button" className="button button-small button-secondary" disabled={!eligibleJobs.length} onClick={startNewVideoAssessment} style={{ border: "1px solid #3b82f6", color: "#2563eb", fontWeight: "600" }}>
            🎥 + Video Assessment
          </button>
        </div>
      </div>

      {!eligibleJobs.length && (
        <p className="small-meta">
          {jobs.length
            ? "An approved, published job is required before creating an assessment. "
            : "Post a job first before creating an assessment. "}{" "}
          <a href="#recruiter-post-job">Go to Post a Job</a>
        </p>
      )}

      {showBuilder && (
        <div className="assessment-builder subpanel" style={{ marginBottom: "20px" }}>
          <div className="section-heading">
            <h3>{editingId ? "Edit Assessment" : "Build Assessment from Centralized Question Bank"}</h3>
            <div className="card-actions">
              <button type="button" className="button button-secondary button-small" onClick={() => setShowPreview((p) => !p)}>
                {showPreview ? "Back to Builder" : `Preview Assessment (${totalQuestions})`}
              </button>
              <button type="button" className="button button-secondary button-small" onClick={() => setShowBuilder(false)}>
                Close
              </button>
            </div>
          </div>

          {showPreview ? (
            <div className="subpanel" style={{ background: "var(--surface)" }}>
              <h4>{form.title || "Untitled Assessment"}</h4>
              <p className="small-meta">
                Duration: {form.duration_minutes} mins · Total Questions: {totalQuestions} · Total Marks: {totalMarks} · Passing Marks: &gt; {form.passing_marks}
              </p>
              <p className="multiline-text">{form.instructions}</p>
              <div className="qb-list" style={{ marginTop: "12px" }}>
                {selectedQuestions.map((q, idx) => (
                  <div className="qb-card" key={q.id}>
                    <strong>Q{idx + 1}. ({q.skill} · {q.difficulty} · {q.marks}m)</strong>
                    <p className="qb-question-text">{q.question_text}</p>
                    <div className="qb-options-grid">
                      {(q.options || []).map((opt, optIdx) => (
                        <div className="qb-option" key={optIdx}><strong>{String.fromCharCode(65 + optIdx)}.</strong> {opt}</div>
                      ))}
                    </div>
                  </div>
                ))}
                {!selectedQuestions.length && <p>No questions selected yet.</p>}
              </div>
            </div>
          ) : (
            <>
              <div className="profile-form" style={{ marginBottom: "16px" }}>
                <select aria-label="Assessment job posting" value={form.job_id} onChange={(e) => setForm({ ...form, job_id: e.target.value })}>
                  <option value="">Select Job Posting</option>
                  {eligibleJobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
                </select>
                <input required placeholder="Assessment Title (e.g., Round 1 Python Technical Test)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                <input type="number" min="1" max="240" placeholder="Duration (minutes)" value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })} />
                <div>
                  <input type="number" min="0" placeholder="Passing Marks" value={form.passing_marks} onChange={(e) => setForm({ ...form, passing_marks: e.target.value })} />
                  <small className="small-meta">Candidate must score strictly &gt; {form.passing_marks || 0} marks to pass.</small>
                </div>
                <input type="datetime-local" aria-label="Assessment Expiry Date" value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
                <input placeholder="Short description (optional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                <textarea className="full-width" placeholder="Candidate test instructions" value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
              </div>

              {jobSkills.length > 0 && (
                <div className="subpanel" style={{ marginBottom: "16px", background: "var(--surface)" }}>
                  <div className="section-heading" style={{ marginBottom: "8px" }}>
                    <div>
                      <strong>Job Required Skills Coverage</strong>
                      <p className="small-meta">
                        {coveredJobSkills.length} of {jobSkills.length} required skills covered ({jobSkills.length ? Math.round((coveredJobSkills.length / jobSkills.length) * 100) : 0}%)
                      </p>
                    </div>
                    {missingJobSkills.length > 0 && (
                      <button
                        type="button"
                        className="button button-secondary button-small"
                        onClick={() => {
                          setQbSkill(missingJobSkills[0]);
                          setQbSearch("");
                        }}
                      >
                        Find Questions: {missingJobSkills[0]}
                      </button>
                    )}
                  </div>
                  <div className="badge-row" style={{ flexWrap: "wrap", gap: "8px" }}>
                    {coveredJobSkills.map((item) => (
                      <span key={item.name} className="role-pill status-badge-success" title={`${item.count} question(s) cover ${item.name}`}>
                        ✓ {item.name} ({item.count} {item.count === 1 ? "question" : "questions"})
                      </span>
                    ))}
                    {missingJobSkills.map((skill) => (
                      <span key={skill} className="role-pill status-badge-danger" title={`No questions currently test ${skill}`}>
                        ⚠ {skill} (Not covered)
                      </span>
                    ))}
                  </div>
                  {missingJobSkills.length > 0 && (
                    <div className="proctoring-candidate-warning" style={{ marginTop: "10px", fontSize: "13px" }}>
                      <strong>Skill Gap Warning:</strong> This assessment does not cover required job skill(s): <strong>{missingJobSkills.join(", ")}</strong>. Add questions for these skills from the Question Bank before publishing.
                    </div>
                  )}
                </div>
              )}

              <div className="builder-split-grid">
                {/* Left: Centralized Question Bank (Read-only selector) */}
                <div className="subpanel" style={{ background: "var(--surface)" }}>
                  <div className="section-heading">
                    <h4>Centralized Question Bank ({bankQuestions.length})</h4>
                    {jobSkills.length > 0 && (
                      <label className="small-meta" style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <input type="checkbox" checked={matchJobSkills} onChange={(e) => setMatchJobSkills(e.target.checked)} />
                        Match job skills ({jobSkills.join(", ")})
                      </label>
                    )}
                  </div>
                  <div className="subpanel" style={{ marginBottom: "14px" }}>
                    <div className="section-heading"><strong>Generate AI Questions</strong></div>
                    <div className="admin-filters">
                      <select aria-label="AI question skills" multiple value={aiSkills} onChange={(event) => setAiSkills(Array.from(event.target.selectedOptions, (option) => option.value))}>
                        {jobSkills.map((skill) => <option key={skill} value={skill}>{skill}</option>)}
                      </select>
                      <select aria-label="AI question difficulty" value={aiDifficulty} onChange={(event) => setAiDifficulty(event.target.value)}>
                        <option value="Easy">Easy</option><option value="Medium">Medium</option><option value="Hard">Hard</option>
                      </select>
                      <input aria-label="AI question count" type="number" min="1" max="20" value={aiQuestionCount} onChange={(event) => setAiQuestionCount(event.target.value)} />
                      <input aria-label="AI question marks" type="number" min="1" max="100" value={aiMarks} onChange={(event) => setAiMarks(event.target.value)} />
                      <button type="button" className="button button-small" disabled={aiGenerating || !jobSkills.length || !aiSkills.length} onClick={generateAiQuestions}>
                        {aiGenerating ? "Generating..." : "Generate Questions"}
                      </button>
                    </div>
                    <p className="small-meta">Select job skills, difficulty, question count, and marks. Generated questions are saved to the bank for review before use.</p>
                  </div>
                  <div className="admin-filters">
                    <input placeholder="Search questions or skill" value={qbSearch} onChange={(e) => setQbSearch(e.target.value)} />
                    <select value={qbSkill} onChange={(e) => setQbSkill(e.target.value)}>
                      <option value="">All skills</option>
                      {bankSkills.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <select value={qbCategory} onChange={(e) => setQbCategory(e.target.value)}>
                      <option value="">All categories</option>
                      {bankCategories.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select value={qbDifficulty} onChange={(e) => setQbDifficulty(e.target.value)}>
                      <option value="">All levels</option>
                      <option value="Easy">Easy</option>
                      <option value="Medium">Medium</option>
                      <option value="Hard">Hard</option>
                    </select>
                  </div>
                  <div className="qb-scroll-list">
                    {bankQuestions.map((q) => {
                      const added = selectedIds.has(q.id);
                      return (
                        <div className="qb-select-row" key={q.id}>
                          <div>
                            <div className="badge-row">
                              <span className="role-pill">{q.skill}</span>
                              <span className="role-pill">{q.difficulty}</span>
                              <span className="small-meta">{q.marks}m</span>
                            </div>
                            <p style={{ margin: "6px 0 0", fontSize: "13px" }}>{q.question_text}</p>
                          </div>
                          <div className="card-actions">
                            {q.is_editable && (
                              <button
                                type="button"
                                className="button button-secondary button-small"
                                onClick={() => setEditingQuestion({ ...q, options: [...q.options] })}
                              >Edit</button>
                            )}
                            <button
                              type="button"
                              className={`button button-small ${added ? "button-secondary" : ""}`}
                              disabled={added}
                              onClick={() => addQuestion(q)}
                            >
                              {added ? "Added" : "+ Add"}
                            </button>
                          </div>
                          {editingQuestion?.id === q.id && (
                            <div className="subpanel full-width" aria-label="Edit generated question">
                              <textarea
                                aria-label="Question text"
                                value={editingQuestion.question_text}
                                onChange={(event) => setEditingQuestion({ ...editingQuestion, question_text: event.target.value })}
                              />
                              {editingQuestion.options.map((option, optionIndex) => (
                                <input
                                  key={optionIndex}
                                  aria-label={`Option ${optionIndex + 1}`}
                                  value={option}
                                  onChange={(event) => {
                                    const options = [...editingQuestion.options];
                                    options[optionIndex] = event.target.value;
                                    setEditingQuestion({ ...editingQuestion, options });
                                  }}
                                />
                              ))}
                              <select
                                aria-label="Correct option"
                                value={editingQuestion.correct_option_index}
                                onChange={(event) => setEditingQuestion({ ...editingQuestion, correct_option_index: Number(event.target.value) })}
                              >
                                {editingQuestion.options.map((_, optionIndex) => (
                                  <option key={optionIndex} value={optionIndex}>Correct answer: {String.fromCharCode(65 + optionIndex)}</option>
                                ))}
                              </select>
                              <input
                                aria-label="Question marks"
                                type="number"
                                min="1"
                                max="100"
                                value={editingQuestion.marks}
                                onChange={(event) => setEditingQuestion({ ...editingQuestion, marks: event.target.value })}
                              />
                              <textarea
                                aria-label="Answer explanation"
                                value={editingQuestion.explanation || ""}
                                onChange={(event) => setEditingQuestion({ ...editingQuestion, explanation: event.target.value })}
                                placeholder="Explanation"
                              />
                              <div className="card-actions">
                                <button type="button" className="button button-small" disabled={savingQuestion} onClick={updateGeneratedQuestion}>
                                  {savingQuestion ? "Saving..." : "Save Question Edits"}
                                </button>
                                <button type="button" className="button button-secondary button-small" disabled={savingQuestion} onClick={() => setEditingQuestion(null)}>
                                  Cancel
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {!bankQuestions.length && <p className="small-meta">No Question Bank items match these filters.</p>}
                  </div>
                </div>

                {/* Right: Selected Assessment Questions */}
                <div className="subpanel" style={{ background: "var(--surface)" }}>
                  <div className="section-heading">
                    <h4>Selected Questions ({totalQuestions})</h4>
                    <strong>Total Marks: {totalMarks}</strong>
                  </div>
                  <div className="qb-scroll-list">
                    {selectedQuestions.map((q, idx) => (
                      <div className="qb-select-row" key={q.id}>
                        <div>
                          <strong>#{idx + 1} · {q.skill} ({q.difficulty}, {q.marks}m)</strong>
                          <p style={{ margin: "4px 0 0", fontSize: "13px" }}>{q.question_text}</p>
                        </div>
                        <div className="card-actions">
                          <button type="button" className="button button-secondary button-small" disabled={idx === 0} onClick={() => moveQuestion(idx, -1)} aria-label="Move up">↑</button>
                          <button type="button" className="button button-secondary button-small" disabled={idx === selectedQuestions.length - 1} onClick={() => moveQuestion(idx, 1)} aria-label="Move down">↓</button>
                          <button type="button" className="button button-danger button-small" onClick={() => removeQuestion(q.id)} aria-label="Remove question">✕</button>
                        </div>
                      </div>
                    ))}
                    {!selectedQuestions.length && <p className="small-meta">Select MCQ questions from the Question Bank on the left.</p>}
                  </div>
                  <div className="card-actions" style={{ marginTop: "14px" }}>
                    <button type="button" className="button button-secondary" disabled={saving} onClick={() => saveAssessment("draft")}>
                      Save as Draft
                    </button>
                    <button type="button" className="button" disabled={saving} onClick={() => saveAssessment("published")}>
                      Publish Assessment
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {showVideoBuilder && (
        <div className="assessment-builder subpanel" style={{ marginBottom: "20px", border: "2px solid #3b82f6", borderRadius: "12px", padding: "16px", background: "#f8fafc" }}>
          <div className="section-heading">
            <div>
              <span className="eyebrow" style={{ color: "#2563eb" }}>Asynchronous Video Interview</span>
              <h3>Create Video Assessment</h3>
            </div>
            <button type="button" className="button button-secondary button-small" onClick={() => setShowVideoBuilder(false)}>
              Close ✕
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "12px", marginTop: "12px" }}>
            <label className="resume-selector">
              Associated Job *
              <select
                value={videoForm.job_id}
                onChange={(e) => setVideoForm((p) => ({ ...p, job_id: e.target.value }))}
              >
                <option value="">Select a published job</option>
                {eligibleJobs.map((j) => (
                  <option key={j.id} value={j.id}>{j.title}</option>
                ))}
              </select>
            </label>

            <label className="resume-selector">
              Assessment Title *
              <input
                required
                placeholder="e.g., Senior Full-Stack Technical Video Screen"
                value={videoForm.title}
                onChange={(e) => setVideoForm((p) => ({ ...p, title: e.target.value }))}
              />
            </label>

            <label className="resume-selector">
              Prep Time Per Question (seconds)
              <input
                type="number"
                min="5"
                max="300"
                value={videoForm.prep_time_seconds}
                onChange={(e) => setVideoForm((p) => ({ ...p, prep_time_seconds: e.target.value }))}
              />
            </label>

            <label className="resume-selector">
              Response Time Limit (seconds)
              <input
                type="number"
                min="15"
                max="600"
                value={videoForm.response_time_seconds}
                onChange={(e) => setVideoForm((p) => ({ ...p, response_time_seconds: e.target.value }))}
              />
            </label>

            <label className="resume-selector">
              Max Retakes / Recordings
              <input
                type="number"
                min="1"
                max="5"
                value={videoForm.max_recordings_per_question}
                onChange={(e) => setVideoForm((p) => ({ ...p, max_recordings_per_question: e.target.value }))}
              />
            </label>

            <label style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "24px", cursor: "pointer", fontSize: "14px", fontWeight: "600" }}>
              <input
                type="checkbox"
                checked={videoForm.allow_review}
                onChange={(e) => setVideoForm((p) => ({ ...p, allow_review: e.target.checked }))}
              />
              <span>Allow Candidate to Review Recording Before Submit</span>
            </label>
          </div>

          <label className="resume-selector full-width" style={{ marginTop: "12px" }}>
            Candidate Instructions &amp; Overview
            <textarea
              rows="2"
              placeholder="Provide general instructions for the candidate..."
              value={videoForm.description}
              onChange={(e) => setVideoForm((p) => ({ ...p, description: e.target.value }))}
            />
          </label>

          <div style={{ marginTop: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
              <h4>Interview Questions ({videoForm.questions.length})</h4>
              <button type="button" className="button button-small" onClick={addVideoQuestion}>
                + Add Question
              </button>
            </div>

            {videoForm.questions.map((q, idx) => (
              <div key={idx} style={{ background: "#ffffff", border: "1px solid #cbd5e1", borderRadius: "8px", padding: "12px", marginBottom: "10px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <strong>Question {idx + 1}</strong>
                  {videoForm.questions.length > 1 && (
                    <button type="button" className="button button-danger button-small" onClick={() => removeVideoQuestion(idx)}>
                      Remove ✕
                    </button>
                  )}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "8px" }}>
                  <input
                    required
                    placeholder="Interview prompt / question (e.g. Describe your architecture approach for a high-traffic API)"
                    value={q.question_text}
                    onChange={(e) => updateVideoQuestion(idx, "question_text", e.target.value)}
                  />
                  <input
                    placeholder="Specific question instructions (optional, e.g. Mention trade-offs and caching)"
                    value={q.instructions}
                    onChange={(e) => updateVideoQuestion(idx, "instructions", e.target.value)}
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="card-actions" style={{ marginTop: "16px", display: "flex", gap: "10px" }}>
            <button
              type="button"
              className="button button-secondary"
              disabled={savingVideo}
              onClick={() => saveVideoAssessment("draft")}
            >
              Save as Draft
            </button>
            <button
              type="button"
              className="button"
              disabled={savingVideo}
              onClick={() => saveVideoAssessment("published")}
            >
              {savingVideo ? "Saving..." : "Publish Video Assessment"}
            </button>
          </div>
        </div>
      )}

      {assessments.length ? (
        <div className="applicant-cards-list">
          {assessments.map((item) => (
            <article className="applicant-card" key={item.id}>
              <div className="applicant-card-header">
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <h3>{item.title}</h3>
                    <span className={`status-badge ${item.assessment_type === "video" ? "status-badge-info" : "status-badge-neutral"}`} style={{ fontSize: "11px", fontWeight: "700" }}>
                      {item.assessment_type === "video" ? "🎥 VIDEO INTERVIEW" : "📝 MCQ ASSESSMENT"}
                    </span>
                  </div>
                  <p className="small-meta">
                    Job: <strong>{item.job_title}</strong> ·{" "}
                    {item.assessment_type === "video"
                      ? `${item.total_questions} Video Questions · Prep: ${item.prep_time_seconds || 30}s · Response: ${item.response_time_seconds || 120}s · Retakes: ${item.max_recordings_per_question || 1}`
                      : `${item.total_questions} MCQs · ${item.total_marks} Total Marks · Passing: > ${item.passing_marks} · Duration: ${item.duration_minutes} mins`}
                  </p>
                  <p className="small-meta">
                    Assigned: {item.assignments_count} · Submitted: {item.submitted_count}
                    {item.expires_at ? ` · Expires ${new Date(item.expires_at).toLocaleString()}` : ""}
                  </p>
                  {item.missing_skills?.length > 0 && item.assessment_type !== "video" && (
                    <p className="small-meta" style={{ color: "#b45309", marginTop: "4px" }}>
                      ⚠ Missing required skills: {item.missing_skills.join(", ")}
                    </p>
                  )}
                </div>
                <div className="badge-row">
                  <span className={`status-badge ${item.status === "published" ? "status-badge-success" : "status-badge-neutral"}`}>
                    {item.status.toUpperCase()}
                  </span>
                </div>
              </div>
              <div className="card-actions">
                {item.assignments_count === 0 && (
                  <button type="button" className="button button-secondary button-small" onClick={() => editAssessment(item)}>
                    Edit / Reorder Questions
                  </button>
                )}
                {item.status === "draft" && (
                  <button type="button" className="button button-small" onClick={() => publishExisting(item)}>
                    Publish
                  </button>
                )}
                {item.assignments_count === 0 && (
                  <button type="button" className="button button-danger button-small" onClick={() => deleteExisting(item)}>
                    Delete
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="small-meta">No assessments created yet. Click “+ Create Assessment” to select questions from the Question Bank.</p>
      )}
    </section>
  );
}
