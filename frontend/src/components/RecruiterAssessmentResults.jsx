import { useCallback, useEffect, useState } from "react";
import api from "../api";
import { getStatusBadgeClass, parseApiError } from "../utils/profileUtils";

export default function RecruiterAssessmentResults({ jobs = [], refreshSignal = 0, onFeedback }) {
  const [results, setResults] = useState([]);
  const [recordings, setRecordings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [jobFilter, setJobFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [resultFilter, setResultFilter] = useState("");
  const [search, setSearch] = useState("");

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeRecording, setActiveRecording] = useState(null);
  const [recordingLoading, setRecordingLoading] = useState(null);

  const loadResults = useCallback(async (overrides = {}) => {
    setLoading(true);
    try {
      const res = await api.get("/api/recruiter/assessment-results", {
        params: {
          job_id: (overrides.job_id !== undefined ? overrides.job_id : jobFilter) || undefined,
          test_status: (overrides.test_status !== undefined ? overrides.test_status : statusFilter) || undefined,
          result_status: (overrides.result_status !== undefined ? overrides.result_status : resultFilter) || undefined,
          q: (overrides.q !== undefined ? overrides.q : search) || undefined,
        },
      });
      setResults(Array.isArray(res?.data) ? res.data : []);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load assessment results."), true);
    } finally {
      setLoading(false);
    }
  }, [jobFilter, statusFilter, resultFilter, search, onFeedback]);

  const loadRecordings = useCallback(async () => {
    try {
      const res = await api.get("/api/recruiter/assessment-recordings");
      setRecordings(Array.isArray(res?.data?.items) ? res.data.items : []);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load assessment recordings."), true);
    }
  }, [onFeedback]);

  useEffect(() => {
    loadResults();
    loadRecordings();
  }, [loadResults, loadRecordings, refreshSignal]);

  const openDetail = async (assignmentId) => {
    setDetailLoading(true);
    try {
      const res = await api.get(`/api/recruiter/assessment-results/${assignmentId}`);
      setDetail(res.data);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load candidate answers."), true);
    } finally {
      setDetailLoading(false);
    }
  };

  const resendInvite = async (assignmentId) => {
    try {
      const res = await api.post(`/api/recruiter/assignments/${assignmentId}/resend`);
      onFeedback?.(res.data.message || "Invitation resent.", false);
      await loadResults();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Failed to resend invitation."), true);
    }
  };

  const playRecording = async (recordingId) => {
    setRecordingLoading(recordingId);
    try {
      const res = await api.get(`/api/recruiter/assessment-recordings/${recordingId}/playback`);
      setActiveRecording(res.data);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to open assessment recording."), true);
    } finally {
      setRecordingLoading(null);
    }
  };

  const resetFilters = () => {
    setJobFilter("");
    setStatusFilter("");
    setResultFilter("");
    setSearch("");
    loadResults({ job_id: "", test_status: "", result_status: "", q: "" });
  };

  return (
    <section className="panel admin-table-panel" id="recruiter-results">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Candidate Performance &amp; Evaluation</span>
          <h2>Assessment Results &amp; Candidate Performance</h2>
        </div>
        <span className="table-count">{results.length} assignments</span>
      </div>

      <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); loadResults(); }}>
        <input placeholder="Search candidate, email, job, or assessment" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select aria-label="Filter results by job" value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
          <option value="">All jobs</option>
          {jobs.map((job) => <option key={job.id} value={job.id}>{job.title}</option>)}
        </select>
        <select aria-label="Filter results by test status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">All test statuses</option>
          <option value="assigned">Assigned</option>
          <option value="started">Started</option>
          <option value="submitted">Submitted</option>
          <option value="expired">Expired</option>
        </select>
        <select aria-label="Filter results by qualification" value={resultFilter} onChange={(e) => setResultFilter(e.target.value)}>
          <option value="">All outcomes</option>
          <option value="Selected for next round">Selected for next round</option>
          <option value="Not qualified">Not qualified</option>
        </select>
        <button type="submit" className="button button-small">Filter</button>
        <button type="button" className="button button-secondary button-small" onClick={resetFilters}>Reset</button>
      </form>

      {activeRecording && (
        <div className="subpanel recording-playback" style={{ margin: "16px 0" }}>
          <div className="section-heading">
            <h3>Assessment Recording</h3>
            <button type="button" className="button button-secondary button-small" onClick={() => setActiveRecording(null)}>Close</button>
          </div>
          <video controls playsInline preload="metadata" src={activeRecording.playback_url} style={{ width: "100%", maxHeight: "480px", background: "#111", borderRadius: "12px" }}>
            Your browser does not support video playback.
          </video>
          <p className="small-meta">This secure playback link expires at {new Date(activeRecording.expires_at).toLocaleString()}.</p>
        </div>
      )}

      {loading && <p className="loading-message" role="status">Loading assessment results...</p>}

      {!loading && (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>Candidate Name</th>
                <th>Job Position</th>
                <th>Assessment Name</th>
                <th>Assignment Date</th>
                <th>Submission Date</th>
                <th>Score</th>
                <th>Total Marks</th>
                <th>Percentage</th>
                <th>Result</th>
                <th>Assessment Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row) => {
                const isSubmitted = row.test_status === "submitted";
                const isPassed = Boolean(row.is_passed);
                const resultText = !isSubmitted
                  ? "Pending"
                  : row.result_status || (isPassed ? "Passed" : "Failed");
                const resultBadgeClass = !isSubmitted
                  ? "status-badge status-badge-neutral"
                  : isPassed
                  ? "status-badge status-badge-success"
                  : "status-badge status-badge-danger";

                let statusLabel = "Assigned";
                if (row.test_status === "started") statusLabel = "In Progress";
                else if (row.test_status === "submitted") statusLabel = "Submitted";
                else if (row.test_status === "expired") statusLabel = "Expired";

                return (
                  <tr key={row.assignment_id}>
                    <td data-label="Candidate Name">
                      <strong>{row.candidate_name}</strong>
                      <span className="small-meta">{row.candidate_email}</span>
                    </td>
                    <td data-label="Job Position">
                      <span>{row.job_title}</span>
                    </td>
                    <td data-label="Assessment Name">
                      <strong>{row.assessment_title}</strong>
                    </td>
                    <td data-label="Assignment Date">
                      <span>{row.assigned_at ? new Date(row.assigned_at).toLocaleDateString() : "—"}</span>
                    </td>
                    <td data-label="Submission Date">
                      <span>{row.submitted_at ? new Date(row.submitted_at).toLocaleDateString() : "Not submitted"}</span>
                    </td>
                    <td data-label="Score">
                      <strong>{row.obtained_marks != null ? row.obtained_marks : "—"}</strong>
                    </td>
                    <td data-label="Total Marks">
                      <span>{row.total_marks}</span>
                    </td>
                    <td data-label="Percentage">
                      <span>{row.percentage != null ? `${Number(row.percentage).toFixed(1)}%` : "—"}</span>
                    </td>
                    <td data-label="Result">
                      <span className={resultBadgeClass}>
                        {resultText}
                      </span>
                    </td>
                    <td data-label="Assessment Status">
                      <span className={getStatusBadgeClass(row.test_status)}>
                        {statusLabel}
                      </span>
                    </td>
                    <td data-label="Actions">
                      <div className="card-actions">
                        <button type="button" className="button button-secondary button-small" onClick={() => openDetail(row.assignment_id)}>
                          View Answers
                        </button>
                        {row.test_status !== "submitted" && (
                          <button type="button" className="button button-small" onClick={() => resendInvite(row.assignment_id)}>
                            {row.invitation_status === "failed" ? "Retry Email" : "Resend"}
                          </button>
                        )}
                        {recordings.filter((item) => item.assignment_id === row.assignment_id && item.status === "uploaded").map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            className="button button-secondary button-small"
                            disabled={recordingLoading === item.id}
                            onClick={() => playRecording(item.id)}
                          >
                            {recordingLoading === item.id ? "Loading recording..." : "Play recording"}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!results.length && (
                <tr><td colSpan="11" className="table-empty">No assessment assignments or results found yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {(detail || detailLoading) && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Candidate Assessment Result Details">
          <div className="modal-panel panel">
            <div className="modal-header">
              <div>
                <span className="eyebrow">Assessment Submission Review</span>
                <h2>{detail?.candidate_name || "Loading..."} — {detail?.assessment_title || ""}</h2>
                {detail && (
                  <p className="small-meta">
                    {detail.candidate_email} · {detail.job_title} · Passing Rule: Strictly &gt; {detail.passing_marks} marks
                  </p>
                )}
              </div>
              <button type="button" className="button button-secondary button-small" onClick={() => setDetail(null)}>Close ✕</button>
            </div>
            {detailLoading && !detail && <p className="loading-message">Loading answers...</p>}
            {detail && (
              <div className="modal-body">
                <div className="assessment-meta-grid">
                  <div><span>Status</span><strong>{detail.test_status}</strong></div>
                  <div><span>Submitted At</span><strong>{detail.submitted_at ? new Date(detail.submitted_at).toLocaleString() : "Not submitted"}</strong></div>
                  <div><span>Score</span><strong>{detail.obtained_marks != null ? `${detail.obtained_marks} / ${detail.total_marks}` : "Not submitted"}</strong></div>
                  <div><span>Percentage</span><strong>{detail.percentage != null ? `${Number(detail.percentage).toFixed(1)}%` : "—"}</strong></div>
                  <div><span>Outcome</span><strong>{detail.result_status || "Pending"}</strong></div>
                  <div><span>Proctoring</span><strong style={{ color: detail.proctoring_event_count > 0 ? "var(--danger, #dc2626)" : "var(--success, #16a34a)" }}>{detail.proctoring_event_count > 0 ? `${detail.proctoring_event_count} warnings` : "Clean (0 warnings)"}</strong></div>
                </div>
                {detail.proctoring_events?.length > 0 && (
                  <div className="subpanel" style={{ marginTop: "14px", border: "1px solid #f59e0b", background: "#fffbeb" }}>
                    <h4 style={{ color: "#b45309", margin: "0 0 6px 0" }}>Proctoring Alerts Log ({detail.proctoring_events.length} Warnings)</h4>
                    <ul className="small-meta" style={{ margin: 0, paddingLeft: "20px" }}>
                      {detail.proctoring_events.map((ev) => (
                        <li key={ev.id}>
                          <strong>{ev.event_type}</strong> — {new Date(ev.created_at).toLocaleTimeString()}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="assessment-review-list">
                  {(detail.questions || []).map((q) => (
                    <div className={`review-q-item ${q.is_correct ? "is-correct" : "is-wrong"}`} key={q.id}>
                      <div className="review-q-head">
                        <strong>Q{q.order_index}. {q.skill} ({q.difficulty} · {q.marks_awarded}/{q.marks}m)</strong>
                        <span>{q.is_correct ? "✓ Correct" : "✕ Incorrect"}</span>
                      </div>
                      <p>{q.question_text}</p>
                      {q.instructions && <p className="small-meta" style={{ fontStyle: "italic" }}>Instructions: {q.instructions}</p>}
                      {q.video_recordings?.length > 0 ? (
                        <div style={{ marginTop: "10px" }}>
                          <strong style={{ fontSize: "13px", display: "block", marginBottom: "6px", color: "#2563eb" }}>🎥 Candidate Video Response:</strong>
                          {q.video_recordings.map((vid) => (
                            <div key={vid.id} style={{ marginBottom: "8px" }}>
                              <video
                                controls
                                playsInline
                                src={vid.cloudinary_secure_url}
                                style={{ width: "100%", maxHeight: "280px", borderRadius: "8px", background: "#000" }}
                              >
                                Your browser does not support video playback.
                              </video>
                              <span className="small-meta" style={{ display: "block", color: "#64748b" }}>
                                Duration: {vid.duration || 0}s · Size: {((vid.file_size || 0) / (1024 * 1024)).toFixed(2)} MB · Cloudinary ID: {vid.cloudinary_public_id}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : q.question_type === "video" ? (
                        <p className="small-meta" style={{ color: "#b45309", marginTop: "8px" }}>
                          No video recording submitted for this question.
                        </p>
                      ) : (
                        <p className="small-meta">
                          Candidate selected: <strong>{q.selected_option_index != null ? q.options[q.selected_option_index] : "Unanswered"}</strong> · Correct answer: <strong>{q.options[q.correct_option_index]}</strong>
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
