import { useCallback, useEffect, useState } from "react";
import api from "../api";
import { parseApiError } from "../utils/profileUtils";

const EMPTY_FORM = {
  question_type: "mcq",
  skill: "",
  category: "",
  difficulty: "Medium",
  question_text: "",
  optionA: "",
  optionB: "",
  optionC: "",
  optionD: "",
  correct_option_index: 0,
  marks: 1,
  explanation: "",
  is_active: true,
};

export default function AdminQuestionBank({ onFeedback }) {
  const [questions, setQuestions] = useState([]);
  const [skills, setSkills] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [search, setSearch] = useState("");
  const [skillFilter, setSkillFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [difficultyFilter, setDifficultyFilter] = useState("");

  const [editingId, setEditingId] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);

  const loadQuestions = useCallback(async (overrides = {}) => {
    setLoading(true);
    try {
      const response = await api.get("/api/admin/question-bank", {
        params: {
          q: (overrides.q !== undefined ? overrides.q : search) || undefined,
          skill: (overrides.skill !== undefined ? overrides.skill : skillFilter) || undefined,
          category: (overrides.category !== undefined ? overrides.category : categoryFilter) || undefined,
          difficulty: (overrides.difficulty !== undefined ? overrides.difficulty : difficultyFilter) || undefined,
        },
      });
      setQuestions(response?.data?.items || []);
      setSkills(response?.data?.skills || []);
      setCategories(response?.data?.categories || []);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load Question Bank."), true);
    } finally {
      setLoading(false);
    }
  }, [search, skillFilter, categoryFilter, difficultyFilter, onFeedback]);

  useEffect(() => {
    loadQuestions();
  }, [loadQuestions]);

  const resetFilters = () => {
    setSearch("");
    setSkillFilter("");
    setCategoryFilter("");
    setDifficultyFilter("");
    loadQuestions({ q: "", skill: "", category: "", difficulty: "" });
  };

  const startCreate = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  };

  const startEdit = (item) => {
    setEditingId(item.id);
    setForm({
      question_type: "mcq",
      skill: item.skill || "",
      category: item.category || "",
      difficulty: item.difficulty || "Medium",
      question_text: item.question_text || "",
      optionA: item.options?.[0] || "",
      optionB: item.options?.[1] || "",
      optionC: item.options?.[2] || "",
      optionD: item.options?.[3] || "",
      correct_option_index: item.correct_option_index ?? 0,
      marks: item.marks ?? 1,
      explanation: item.explanation || "",
      is_active: item.is_active !== false,
    });
    setShowForm(true);
  };

  const submitForm = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const payload = {
        question_type: "mcq",
        skill: form.skill.trim(),
        category: form.category.trim(),
        difficulty: form.difficulty,
        question_text: form.question_text.trim(),
        options: [form.optionA.trim(), form.optionB.trim(), form.optionC.trim(), form.optionD.trim()],
        correct_option_index: Number(form.correct_option_index),
        marks: Number(form.marks) || 1,
        explanation: form.explanation.trim() || null,
        is_active: form.is_active,
      };
      if (editingId) {
        await api.put(`/api/admin/question-bank/${editingId}`, payload);
        onFeedback?.("Question updated in centralized Question Bank.", false);
      } else {
        await api.post("/api/admin/question-bank", payload);
        onFeedback?.("New MCQ question added to centralized Question Bank.", false);
      }
      setShowForm(false);
      setEditingId(null);
      setForm(EMPTY_FORM);
      await loadQuestions();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to save question."), true);
    } finally {
      setSaving(false);
    }
  };

  const deleteQuestion = async (item) => {
    if (!window.confirm(`Delete question "${item.question_text.slice(0, 60)}..." from the Question Bank?`)) {
      return;
    }
    try {
      await api.delete(`/api/admin/question-bank/${item.id}`);
      onFeedback?.("Question deleted from Question Bank.", false);
      await loadQuestions();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to delete question."), true);
    }
  };

  return (
    <section className="panel admin-table-panel" id="admin-question-bank">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Round 1 Centralized MCQ Repository</span>
          <h2>Question Bank</h2>
        </div>
        <div className="card-actions">
          <span className="table-count">{questions.length} MCQs</span>
          <button type="button" className="button button-small" onClick={startCreate}>
            + Add MCQ Question
          </button>
        </div>
      </div>

      <div className="subpanel" style={{ marginBottom: "16px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "12px" }}>
        <div>
          <strong>Candidate Answer Privacy</strong>
          <p className="small-meta">
            Scores, pass/fail status, correct answers, and explanations remain private. Detailed results are available to authorized recruiters.
          </p>
        </div>
        <span className="role-pill">Always private</span>
      </div>

      {showForm && (
        <form className="subpanel profile-form" style={{ marginBottom: "18px" }} onSubmit={submitForm}>
          <h3 className="full-width">{editingId ? "Edit Question Bank MCQ" : "Add New MCQ Question (4 Options)"}</h3>
          <input required placeholder="Skill (e.g., Python, React, SQL, FastAPI)" value={form.skill} onChange={(e) => setForm({ ...form, skill: e.target.value })} />
          <input required placeholder="Category (e.g., Backend, Frontend, Database)" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <select aria-label="Question difficulty" value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
            <option value="Easy">Easy</option>
            <option value="Medium">Medium</option>
            <option value="Hard">Hard</option>
          </select>
          <input required type="number" min="1" max="100" placeholder="Marks" value={form.marks} onChange={(e) => setForm({ ...form, marks: e.target.value })} />
          <textarea required minLength="5" className="full-width" placeholder="Enter MCQ question text..." value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} />
          <input required placeholder="Option A" value={form.optionA} onChange={(e) => setForm({ ...form, optionA: e.target.value })} />
          <input required placeholder="Option B" value={form.optionB} onChange={(e) => setForm({ ...form, optionB: e.target.value })} />
          <input required placeholder="Option C" value={form.optionC} onChange={(e) => setForm({ ...form, optionC: e.target.value })} />
          <input required placeholder="Option D" value={form.optionD} onChange={(e) => setForm({ ...form, optionD: e.target.value })} />
          <select aria-label="Correct option" value={form.correct_option_index} onChange={(e) => setForm({ ...form, correct_option_index: Number(e.target.value) })}>
            <option value={0}>Correct Answer: Option A</option>
            <option value={1}>Correct Answer: Option B</option>
            <option value={2}>Correct Answer: Option C</option>
            <option value={3}>Correct Answer: Option D</option>
          </select>
          <input placeholder="Explanation (optional)" value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })} />
          <div className="card-actions full-width">
            <button type="submit" className="button button-small" disabled={saving}>
              {saving ? "Saving..." : editingId ? "Update Question" : "Save Question"}
            </button>
            <button type="button" className="button button-secondary button-small" onClick={() => { setShowForm(false); setEditingId(null); }}>
              Cancel
            </button>
          </div>
        </form>
      )}

      <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); loadQuestions(); }}>
        <input aria-label="Search Question Bank" placeholder="Search question text, skill, or category" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Filter Question Bank by skill" value={skillFilter} onChange={(e) => setSkillFilter(e.target.value)}>
          <option value="">All skills</option>
          {skills.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select aria-label="Filter Question Bank by category" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select aria-label="Filter Question Bank by difficulty" value={difficultyFilter} onChange={(e) => setDifficultyFilter(e.target.value)}>
          <option value="">All difficulties</option>
          <option value="Easy">Easy</option>
          <option value="Medium">Medium</option>
          <option value="Hard">Hard</option>
        </select>
        <button type="submit" className="button button-small">Filter</button>
        <button type="button" className="button button-secondary button-small" onClick={resetFilters}>Reset</button>
      </form>

      {loading && <p className="loading-message" role="status">Loading Question Bank...</p>}

      {!loading && (
        <div className="qb-list">
          {questions.length ? questions.map((item) => (
            <article className="qb-card" key={item.id}>
              <div className="qb-card-head">
                <div className="badge-row">
                  <span className="role-pill">{item.skill}</span>
                  <span className="role-pill">{item.category}</span>
                  <span className={`status-badge ${item.difficulty === "Easy" ? "status-badge-success" : item.difficulty === "Hard" ? "status-badge-danger" : "status-badge-info"}`}>
                    {item.difficulty}
                  </span>
                  <span className="status-badge status-badge-neutral">{item.marks} mark{item.marks === 1 ? "" : "s"}</span>
                </div>
                <div className="card-actions">
                  <button type="button" className="button button-secondary button-small" onClick={() => startEdit(item)}>Edit</button>
                  <button type="button" className="button button-danger button-small" onClick={() => deleteQuestion(item)}>Delete</button>
                </div>
              </div>
              <p className="qb-question-text">{item.question_text}</p>
              <div className="qb-options-grid">
                {(item.options || []).map((opt, idx) => (
                  <div key={idx} className={`qb-option${idx === item.correct_option_index ? " is-correct-answer" : ""}`}>
                    <strong>{String.fromCharCode(65 + idx)}.</strong> {opt} {idx === item.correct_option_index ? "✓" : ""}
                  </div>
                ))}
              </div>
            </article>
          )) : <p className="table-empty">No questions match these filters.</p>}
        </div>
      )}
    </section>
  );
}
