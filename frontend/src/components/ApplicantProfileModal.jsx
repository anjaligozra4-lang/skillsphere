import { useCallback, useEffect, useState } from "react";
import api from "../api";
import {
  APPLICATION_STATUS_OPTIONS,
  displayValue,
  formatAssessmentStatus,
  formatInterviewMode,
  formatInterviewStatus,
  formatInvitationStatus,
  formatNotificationType,
  formatRecommendation,
  formatStatusLabel,
  getStatusBadgeClass,
  parseApiError,
} from "../utils/profileUtils";

export default function ApplicantProfileModal({
  applicant,
  loading,
  refreshKey = 0,
  onClose,
  onStatusChange,
  onDownloadResume,
  onRefreshMatch,
  onOpenDecision,
  onScheduleInterview,
  onInterviewAction,
  onNotificationRetried,
  onFeedback,
  actionBusy,
}) {
  const [showQuestions, setShowQuestions] = useState(false);
  const [interviews, setInterviews] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [retryingId, setRetryingId] = useState(null);

  const loadApplicantExtras = useCallback(async () => {
    if (!applicant?.id) {
      setInterviews([]);
      setNotifications([]);
      return;
    }
    const [intRes, notifRes] = await Promise.all([
      api.get(`/api/recruiter/applications/${applicant.id}/interviews`).catch(() => ({ data: [] })),
      api.get(`/api/recruiter/applications/${applicant.id}/notifications`).catch(() => ({ data: [] })),
    ]);
    setInterviews(Array.isArray(intRes?.data) ? intRes.data : []);
    setNotifications(Array.isArray(notifRes?.data) ? notifRes.data : []);
  }, [applicant?.id]);

  useEffect(() => {
    loadApplicantExtras();
  }, [loadApplicantExtras, refreshKey]);

  const handleRetryNotification = async (notificationId) => {
    if (retryingId === notificationId) return;
    setRetryingId(notificationId);
    try {
      const res = await api.post(`/api/recruiter/notifications/${notificationId}/resend`);
      onFeedback?.(res?.data?.message || "Notification resent successfully.", false);
      await loadApplicantExtras();
      onNotificationRetried?.();
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Failed to resend email notification."), true);
      await loadApplicantExtras();
    } finally {
      setRetryingId(null);
    }
  };

  if (!applicant && !loading) return null;

  const canSchedule = !["withdrawn", "rejected", "accepted", "hired"].includes(applicant?.status);
  const canSelect = !["withdrawn", "rejected", "selected", "accepted", "hired"].includes(applicant?.status);
  const canAccept = applicant?.status === "selected";
  const canReject = !["withdrawn", "rejected", "accepted", "hired"].includes(applicant?.status);

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Candidate Profile Details">
      <div className="modal-panel panel">
        <div className="modal-header">
          <div>
            <span className="eyebrow">Candidate Profile & ATS Review</span>
            <h2>{applicant?.candidate || "Loading candidate..."}</h2>
            {applicant && (
              <p className="modal-subtitle">
                {applicant.job_title} · {applicant.company} · Applied {new Date(applicant.applied_at).toLocaleDateString()}
              </p>
            )}
          </div>
          <button type="button" className="button button-secondary button-small" onClick={onClose} aria-label="Close profile">
            Close ✕
          </button>
        </div>

        {loading && !applicant && <p className="loading-message" role="status">Loading full candidate profile...</p>}

        {applicant && (
          <div className="modal-body">
            {/* Top summary badges & quick actions */}
            <div className="modal-summary-bar">
              <div className="badge-row">
                <span className={getStatusBadgeClass(applicant.status)}>{formatStatusLabel(applicant.status)}</span>
                {applicant.shortlist_source === "automatic" && (
                  <span className="status-badge status-badge-ai">Auto-Shortlisted (≥70%)</span>
                )}
                {applicant.shortlist_source === "manual" && (
                  <span className="status-badge status-badge-neutral">Manual Shortlist</span>
                )}
                {applicant.match_score != null && (
                  <span className={`score-pill ${applicant.match_score >= 70 ? "score-high" : applicant.match_score >= 45 ? "score-mid" : "score-low"}`}>
                    AI Match: {Number(applicant.match_score).toFixed(1)}%
                  </span>
                )}
              </div>

              <div className="card-actions">
                {applicant.resume_id && (
                  <button
                    type="button"
                    className="button button-secondary button-small"
                    onClick={() => onDownloadResume({ id: applicant.resume_id, original_filename: applicant.resume_filename || `${applicant.candidate}-resume` })}
                  >
                    Download Resume
                  </button>
                )}
                <button
                  type="button"
                  className="button button-secondary button-small"
                  disabled={actionBusy || applicant.status === "withdrawn"}
                  onClick={() => onRefreshMatch(applicant.id)}
                >
                  {actionBusy ? "Processing..." : "Refresh AI Match"}
                </button>
                {onScheduleInterview && canSchedule && (
                  <button
                    type="button"
                    className="button button-small"
                    disabled={actionBusy}
                    onClick={() => onScheduleInterview(applicant, interviews.length)}
                  >
                    Schedule Interview
                  </button>
                )}
                {onOpenDecision && canSelect && (
                  <button
                    type="button"
                    className="button button-small"
                    disabled={actionBusy}
                    onClick={() => onOpenDecision(applicant, "select")}
                  >
                    Select
                  </button>
                )}
                {onOpenDecision && canAccept && (
                  <button
                    type="button"
                    className="button button-small"
                    disabled={actionBusy}
                    onClick={() => onOpenDecision(applicant, "accept")}
                  >
                    Mark Accepted
                  </button>
                )}
                {onOpenDecision && canReject && (
                  <button
                    type="button"
                    className="button button-danger button-small"
                    disabled={actionBusy}
                    onClick={() => onOpenDecision(applicant, "reject")}
                  >
                    Reject
                  </button>
                )}
              </div>
            </div>

            <div className="modal-grid">
              {/* Personal & Contact */}
              <section className="subpanel">
                <h3>Personal & Contact Details</h3>
                <dl className="detail-list">
                  <div><dt>Full Name</dt><dd>{displayValue(applicant.candidate)}</dd></div>
                  <div><dt>Registered Email</dt><dd>{displayValue(applicant.email)}</dd></div>
                  <div><dt>Contact Email</dt><dd>{displayValue(applicant.contact_email)}</dd></div>
                  <div><dt>Phone</dt><dd>{displayValue(applicant.phone)}</dd></div>
                  <div><dt>Location</dt><dd>{displayValue(applicant.location)}</dd></div>
                  <div><dt>Headline</dt><dd>{displayValue(applicant.headline)}</dd></div>
                  <div><dt>Summary</dt><dd>{displayValue(applicant.summary)}</dd></div>
                </dl>
              </section>

              {/* Qualifications */}
              <section className="subpanel">
                <h3>Education, Experience & Credentials</h3>
                <dl className="detail-list">
                  <div><dt>Education</dt><dd className="multiline-text">{displayValue(applicant.education)}</dd></div>
                  <div><dt>Work Experience</dt><dd className="multiline-text">{displayValue(applicant.experience)}</dd></div>
                  <div><dt>Projects</dt><dd className="multiline-text">{displayValue(applicant.projects)}</dd></div>
                  <div><dt>Certifications</dt><dd className="multiline-text">{displayValue(applicant.certifications)}</dd></div>
                  <div>
                    <dt>Technical Skills</dt>
                    <dd>
                      {applicant.skills?.length ? (
                        <div className="chips">{applicant.skills.map((s) => <span key={s}>{s}</span>)}</div>
                      ) : "Not provided"}
                    </dd>
                  </div>
                </dl>
              </section>
            </div>

            {/* AI Matching Details */}
            <section className="subpanel">
              <div className="section-heading">
                <h3>AI Job-Candidate Match Analysis</h3>
                <strong>{applicant.match_score != null ? `${Number(applicant.match_score).toFixed(1)}%` : "Not yet evaluated"}</strong>
              </div>
              {applicant.matching_explanation && <p>{applicant.matching_explanation}</p>}
              {applicant.relevant_experience && <p><strong>Relevant Experience:</strong> {applicant.relevant_experience}</p>}
              <div className="modal-grid">
                <div>
                  <p><strong>Matched Skills:</strong></p>
                  <div className="chips">
                    {applicant.matched_skills?.length ? applicant.matched_skills.map((s) => <span className="chip-match" key={s}>{s}</span>) : <span>None</span>}
                  </div>
                </div>
                <div>
                  <p><strong>Missing Skills:</strong></p>
                  <div className="chips">
                    {applicant.missing_skills?.length ? applicant.missing_skills.map((s) => <span className="chip-miss" key={s}>{s}</span>) : <span>None</span>}
                  </div>
                </div>
              </div>
              {(applicant.strengths?.length > 0 || applicant.weaknesses?.length > 0) && (
                <div className="modal-grid" style={{ marginTop: "12px" }}>
                  <div>
                    <p><strong>Strengths</strong></p>
                    <ul className="compact-list">
                      {(applicant.strengths || []).map((item, idx) => <li key={idx}>{item}</li>)}
                    </ul>
                  </div>
                  <div>
                    <p><strong>Weaknesses / Gaps</strong></p>
                    <ul className="compact-list">
                      {(applicant.weaknesses || []).map((item, idx) => <li key={idx}>{item}</li>)}
                    </ul>
                  </div>
                </div>
              )}
            </section>

            {/* Online Assessment & Invitation */}
            <section className="subpanel">
              <h3>Online Technical Assessment</h3>
              <div className="assessment-meta-grid">
                <div><span>Invitation Status</span><strong className={getStatusBadgeClass(applicant.invitation_status)}>{formatInvitationStatus(applicant.invitation_status)}</strong></div>
                <div><span>Assessment Status</span><strong className={getStatusBadgeClass(applicant.assessment_status)}>{formatAssessmentStatus(applicant.assessment_status)}</strong></div>
                <div><span>Score</span><strong>{applicant.assessment_score != null ? `${applicant.assessment_score} / ${applicant.assessment_max_score ?? "—"}` : "Pending"}</strong></div>
                <div><span>Percentage</span><strong>{applicant.assessment_percentage != null ? `${Number(applicant.assessment_percentage).toFixed(1)}%` : "—"}</strong></div>
                <div><span>Completed At</span><strong>{applicant.assessment_completed_at ? new Date(applicant.assessment_completed_at).toLocaleString() : "Not completed"}</strong></div>
              </div>
              {applicant.invitation_error && (
                <p className="error" style={{ marginTop: "10px" }}>
                  <strong>Email delivery issue:</strong> {applicant.invitation_error}
                </p>
              )}
              {applicant.assessment_questions?.length > 0 && (
                <div style={{ marginTop: "14px" }}>
                  <button
                    type="button"
                    className="button button-secondary button-small"
                    onClick={() => setShowQuestions((prev) => !prev)}
                  >
                    {showQuestions ? "Hide Assessment Breakdown" : `View Question-by-Question Results (${applicant.assessment_questions.length})`}
                  </button>
                  {showQuestions && (
                    <div className="assessment-review-list">
                      {applicant.assessment_questions.map((q) => (
                        <div className={`review-q-item ${q.is_correct ? "is-correct" : "is-wrong"}`} key={q.id}>
                          <div className="review-q-head">
                            <strong>Q{q.order_index} ({q.skill_tag} · {q.difficulty})</strong>
                            <span>{q.is_correct ? "✓ Correct" : "✕ Incorrect"}</span>
                          </div>
                          <p>{q.question_text}</p>
                          <p className="small-meta">
                            Candidate answer: <strong>{q.selected_option_index != null ? q.options[q.selected_option_index] : "Unanswered"}</strong> · Correct answer: <strong>{q.options[q.correct_option_index]}</strong>
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </section>

            {/* Hiring Decision Details */}
            {(applicant.decision_reason || applicant.decision_note || applicant.decided_at) && (
              <section className="subpanel">
                <h3>Hiring Decision Metadata</h3>
                <dl className="detail-list">
                  <div><dt>Decision Reason</dt><dd>{applicant.decision_reason || "Not provided"}</dd></div>
                  <div><dt>Decision Note</dt><dd className="multiline-text">{applicant.decision_note || "Not provided"}</dd></div>
                  <div><dt>Decided At</dt><dd>{applicant.decided_at ? new Date(applicant.decided_at).toLocaleString() : "Not recorded"}</dd></div>
                  {applicant.decided_by_name && <div><dt>Decided By</dt><dd>{applicant.decided_by_name}</dd></div>}
                </dl>
              </section>
            )}

            {/* Interview Rounds */}
            <section className="subpanel">
              <div className="section-heading">
                <h3>Interview Rounds ({interviews.length})</h3>
                {onScheduleInterview && canSchedule && (
                  <button
                    type="button"
                    className="button button-small"
                    disabled={actionBusy}
                    onClick={() => onScheduleInterview(applicant, interviews.length)}
                  >
                    + Schedule Round {interviews.length + 1}
                  </button>
                )}
              </div>
              {interviews.length ? (
                <div className="qb-list">
                  {interviews.map((iv) => {
                    const editable = ["scheduled", "rescheduled"].includes(iv.status);
                    return (
                      <article className="qb-card" key={iv.id}>
                        <div className="qb-card-head">
                          <strong>Round {iv.round_number}: {iv.round_name}</strong>
                          <div className="badge-row">
                            <span className={getStatusBadgeClass(iv.status)}>{formatInterviewStatus(iv.status)}</span>
                            <span className="role-pill">{formatInterviewMode(iv.interview_mode)}</span>
                            {iv.recommendation && (
                              <span className={getStatusBadgeClass(iv.recommendation)}>
                                {formatRecommendation(iv.recommendation)}
                              </span>
                            )}
                          </div>
                        </div>
                        <p className="small-meta">
                          {new Date(iv.scheduled_at).toLocaleString()} ({iv.timezone}) · {iv.duration_minutes} mins
                          {iv.interviewer_name ? ` · Interviewer: ${iv.interviewer_name}` : ""}
                        </p>
                        {iv.meeting_link && <p className="small-meta">Meeting Link: <a href={iv.meeting_link} target="_blank" rel="noreferrer">{iv.meeting_link}</a></p>}
                        {iv.location && <p className="small-meta">Location: {iv.location}</p>}
                        {iv.feedback && <p className="small-meta"><strong>Feedback:</strong> {iv.feedback}{iv.rating != null ? ` (Rating: ${iv.rating}/5)` : ""}</p>}
                        {iv.cancellation_reason && <p className="small-meta"><strong>Cancellation Reason:</strong> {iv.cancellation_reason}</p>}
                        {onInterviewAction && (
                          <div className="card-actions" style={{ marginTop: "8px" }}>
                            {editable && (
                              <button type="button" className="button button-secondary button-small" onClick={() => onInterviewAction("reschedule", iv)}>
                                Reschedule
                              </button>
                            )}
                            {iv.status !== "cancelled" && (
                              <button type="button" className="button button-small" onClick={() => onInterviewAction("feedback", iv)}>
                                Feedback &amp; Outcome
                              </button>
                            )}
                            {editable && (
                              <button type="button" className="button button-danger button-small" onClick={() => onInterviewAction("cancel", iv)}>
                                Cancel
                              </button>
                            )}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              ) : (
                <p className="small-meta">No interview rounds scheduled for this application yet.</p>
              )}
            </section>

            {/* Email Notifications */}
            <section className="subpanel">
              <h3>Email Notification Logs ({notifications.length})</h3>
              {notifications.length ? (
                <ul className="status-timeline">
                  {notifications.map((n) => (
                    <li key={n.id}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                        <div>
                          <strong>{formatNotificationType(n.notification_type)}</strong>{" "}
                          <span className={getStatusBadgeClass(n.status)}>{n.status.toUpperCase()}</span>
                          <span className="small-meta"> · {n.recipient_email} · Retries: {n.retry_count ?? 0}</span>
                        </div>
                        {n.status === "failed" && (
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            disabled={retryingId === n.id}
                            onClick={() => handleRetryNotification(n.id)}
                          >
                            {retryingId === n.id ? "Retrying..." : "Retry"}
                          </button>
                        )}
                      </div>
                      <div className="small-meta">
                        {n.sent_at ? `Sent ${new Date(n.sent_at).toLocaleString()}` : `Logged ${new Date(n.created_at).toLocaleString()}`}
                        {n.error_message ? ` — ${n.error_message}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small-meta">No shortlist, decision, or interview emails recorded yet.</p>
              )}
            </section>

            {/* Resume Preview & Download */}
            <section className="subpanel">
              <div className="section-heading">
                <h3>Resume Details</h3>
                {applicant.resume_filename && <span className="table-count">{applicant.resume_filename}</span>}
              </div>
              {applicant.resume_id ? (
                <>
                  <p className="small-meta">Processing status: {applicant.resume_processing_status || "processed"}</p>
                  {applicant.resume_extracted_text && (
                    <details>
                      <summary>View extracted resume text</summary>
                      <pre className="resume-text-preview">{applicant.resume_extracted_text}</pre>
                    </details>
                  )}
                </>
              ) : (
                <p>No resume file attached to this application.</p>
              )}
            </section>

            {/* Status Update & History */}
            <section className="subpanel">
              <div className="section-heading">
                <h3>Application Status & History</h3>
                <select
                  aria-label="Update candidate application status"
                  value={applicant.status}
                  disabled={applicant.status === "withdrawn" || actionBusy}
                  onChange={(e) => onStatusChange(applicant.id, e.target.value)}
                >
                  {APPLICATION_STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value} disabled={opt.value === "withdrawn" && applicant.status !== "withdrawn"}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              {applicant.status_history?.length ? (
                <ul className="status-timeline">
                  {applicant.status_history.map((entry) => (
                    <li key={entry.id}>
                      <div>
                        <strong>{entry.previous_status ? `${formatStatusLabel(entry.previous_status)} → ` : ""}{formatStatusLabel(entry.new_status)}</strong>
                        <span className="small-meta"> · by {entry.actor_name} ({entry.actor_role})</span>
                      </div>
                      <div className="small-meta">
                        {new Date(entry.created_at).toLocaleString()} {entry.note ? `— ${entry.note}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="small-meta">No status history entries recorded yet.</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
