import { useMemo, useState } from "react";
import api from "../api";
import { parseApiError } from "../utils/profileUtils";

export default function AssignAssessmentModal({
  open,
  onClose,
  shortlistedApplicants = [],
  assessments = [],
  initialSelectedIds = [],
  onAssigned,
}) {
  const publishedAssessments = useMemo(
    () => assessments.filter((item) => item.status === "published"),
    [assessments]
  );

  const defaultAssessmentId = useMemo(() => {
    if (initialSelectedIds.length) {
      const candidate = shortlistedApplicants.find((a) => initialSelectedIds.includes(a.id));
      const matched = publishedAssessments.find((item) => item.job_id === candidate?.job_id);
      if (matched) return String(matched.id);
    }
    return publishedAssessments[0]?.id ? String(publishedAssessments[0].id) : "";
  }, [initialSelectedIds, shortlistedApplicants, publishedAssessments]);

  const [selectedIds, setSelectedIds] = useState(initialSelectedIds);
  const [assessmentId, setAssessmentId] = useState(defaultAssessmentId);
  const [expiresAt, setExpiresAt] = useState("");
  const [step, setStep] = useState("select"); // select | review | done
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [resultSummary, setResultSummary] = useState(null);

  if (!open) return null;

  const chosenAssessment = publishedAssessments.find((a) => String(a.id) === String(assessmentId))
    || publishedAssessments[0]
    || null;

  const jobFilteredShortlisted = chosenAssessment
    ? shortlistedApplicants.filter((a) => a.job_id === chosenAssessment.job_id)
    : shortlistedApplicants;

  const selectedApplicants = jobFilteredShortlisted.filter((a) => selectedIds.includes(a.id));

  const toggleCandidate = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const toggleAll = () => {
    if (selectedIds.length === jobFilteredShortlisted.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(jobFilteredShortlisted.map((a) => a.id));
    }
  };

  const confirmAndSend = async () => {
    if (!chosenAssessment || !selectedApplicants.length) return;
    setSubmitting(true);
    setError("");
    try {
      const response = await api.post(`/api/recruiter/assessments/${chosenAssessment.id}/assign`, {
        application_ids: selectedApplicants.map((a) => a.id),
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      });
      setResultSummary(response.data);
      setStep("done");
      onAssigned?.(response.data);
    } catch (requestError) {
      setError(await parseApiError(requestError, "Unable to assign assessment."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Assign Assessment to Shortlisted Candidates">
      <div className="modal-panel panel">
        <div className="modal-header">
          <div>
            <span className="eyebrow">Manual Recruiter Assignment</span>
            <h2>Assign Assessment to Shortlisted Candidates</h2>
          </div>
          <button type="button" className="button button-secondary button-small" onClick={onClose}>
            Close ✕
          </button>
        </div>

        {!publishedAssessments.length && (
          <p className="error">
            No published assessments found. Go to “Assessments / Manage Tests” to create and publish an MCQ assessment first.
          </p>
        )}

        {publishedAssessments.length > 0 && step === "select" && (
          <div className="modal-body">
            <label className="resume-selector">
              Select Published Assessment
              <select
                value={chosenAssessment?.id || ""}
                onChange={(e) => { setAssessmentId(e.target.value); setSelectedIds([]); }}
              >
                {publishedAssessments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title} ({item.job_title} · {item.total_questions} MCQs · {item.total_marks} marks · {item.duration_minutes} mins)
                  </option>
                ))}
              </select>
            </label>

            <label className="resume-selector">
              Optional Invitation Expiry Override
              <input type="datetime-local" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            </label>

            <div className="subpanel">
              <div className="section-heading">
                <h3>Shortlisted Candidates for {chosenAssessment?.job_title} ({jobFilteredShortlisted.length})</h3>
                {jobFilteredShortlisted.length > 0 && (
                  <button type="button" className="text-button" onClick={toggleAll}>
                    {selectedIds.length === jobFilteredShortlisted.length ? "Clear all" : "Select all"}
                  </button>
                )}
              </div>
              {jobFilteredShortlisted.length ? (
                <div className="qb-scroll-list">
                  {jobFilteredShortlisted.map((applicant) => (
                    <label className="assign-candidate-row" key={applicant.id}>
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(applicant.id)}
                        onChange={() => toggleCandidate(applicant.id)}
                      />
                      <div>
                        <strong>{applicant.candidate}</strong>
                        <span className="small-meta"> · {applicant.email}</span>
                        <div className="small-meta">
                          Match: {applicant.match_score != null ? `${Number(applicant.match_score).toFixed(1)}%` : "N/A"} · Current test: {applicant.assessment_status || "not_assigned"}
                        </div>
                      </div>
                    </label>
                  ))}
                </div>
              ) : (
                <p className="small-meta">No shortlisted candidates available for {chosenAssessment?.job_title}.</p>
              )}
            </div>

            {error && <p className="error">{error}</p>}

            <div className="card-actions">
              <button
                type="button"
                className="button"
                disabled={!chosenAssessment || !selectedApplicants.length}
                onClick={() => { setError(""); setStep("review"); }}
              >
                Review Assignment ({selectedApplicants.length} selected)
              </button>
              <button type="button" className="button button-secondary" onClick={onClose}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {step === "review" && chosenAssessment && (
          <div className="modal-body">
            <div className="subpanel">
              <h3>Confirm Assessment Assignment &amp; Email Invitations</h3>
              <p><strong>Assessment:</strong> {chosenAssessment.title}</p>
              <p><strong>Job:</strong> {chosenAssessment.job_title}</p>
              <p><strong>Format:</strong> {chosenAssessment.total_questions} MCQs · {chosenAssessment.total_marks} Total Marks · Passing: &gt; {chosenAssessment.passing_marks} marks · Duration: {chosenAssessment.duration_minutes} minutes</p>
              <p><strong>Candidates to receive unique invitation links ({selectedApplicants.length}):</strong></p>
              <ul className="compact-list">
                {selectedApplicants.map((c) => (
                  <li key={c.id}>{c.candidate} ({c.email})</li>
                ))}
              </ul>
            </div>

            {error && <p className="error">{error}</p>}

            <div className="card-actions">
              <button type="button" className="button" disabled={submitting} onClick={confirmAndSend}>
                {submitting ? "Sending Invitations..." : "Confirm & Send Invitations"}
              </button>
              <button type="button" className="button button-secondary" disabled={submitting} onClick={() => setStep("select")}>
                ← Back
              </button>
            </div>
          </div>
        )}

        {step === "done" && resultSummary && (
          <div className="modal-body">
            <div className="subpanel">
              <h3>Assignment Complete</h3>
              <p>
                Assigned: <strong>{resultSummary.assigned_count}</strong> · Emails Sent: <strong>{resultSummary.sent_count}</strong> · Failed: <strong>{resultSummary.failed_count}</strong> · Skipped (Already Assigned): <strong>{resultSummary.skipped_count}</strong>
              </p>
              <ul className="compact-list">
                {(resultSummary.results || []).map((row) => (
                  <li key={row.application_id}>
                    <strong>{row.candidate}</strong> ({row.email}): <span>{row.invitation_status.toUpperCase()}</span> — {row.message}
                  </li>
                ))}
              </ul>
            </div>
            <div className="card-actions">
              <button type="button" className="button" onClick={onClose}>Done</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
