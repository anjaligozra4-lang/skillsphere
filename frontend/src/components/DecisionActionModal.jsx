import { useState } from "react";
import api from "../api";
import { formatStatusLabel, getStatusBadgeClass, parseApiError } from "../utils/profileUtils";

export default function DecisionActionModal({
  applicant,
  initialMode = "select",
  onClose,
  onCompleted,
}) {
  const defaultStatus = initialMode === "accept" ? "accepted" : "selected";
  const [targetStatus, setTargetStatus] = useState(
    initialMode === "reject" ? "rejected" : applicant?.status === "selected" ? "accepted" : defaultStatus
  );
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!applicant) return null;

  const isReject = initialMode === "reject" || targetStatus === "rejected";
  const isDuplicateDecision = applicant.status === targetStatus;

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (submitting || isDuplicateDecision) return;

    setSubmitting(true);
    setError("");
    try {
      const payload = {
        reason: reason.trim() || null,
        note: note.trim() || null,
        send_email: sendEmail,
      };
      const endpoint = isReject
        ? `/api/recruiter/applications/${applicant.id}/reject`
        : `/api/recruiter/applications/${applicant.id}/select`;
      const body = isReject ? payload : { ...payload, status: targetStatus };

      const response = await api.post(endpoint, body);
      onCompleted?.(response.data);
      onClose?.();
    } catch (requestError) {
      setError(await parseApiError(requestError, "Unable to save candidate decision."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={isReject ? "Confirm Candidate Rejection" : "Confirm Candidate Selection"}
    >
      <div className="modal-panel panel">
        <div className="modal-header">
          <div>
            <span className="eyebrow">Recruiter Hiring Decision</span>
            <h2>{isReject ? "Reject Candidate" : "Select / Accept Candidate"}</h2>
            <p className="modal-subtitle">
              {applicant.candidate} ({applicant.email}) · {applicant.job_title}
            </p>
          </div>
          <button type="button" className="button button-secondary button-small" onClick={onClose} disabled={submitting}>
            Close ✕
          </button>
        </div>

        <form className="modal-body" onSubmit={handleSubmit}>
          <div className="subpanel">
            <div className="badge-row">
              <span>Current Status:</span>
              <span className={getStatusBadgeClass(applicant.status)}>{formatStatusLabel(applicant.status)}</span>
              {applicant.match_score != null && (
                <span className="score-pill score-high">ATS Match: {Number(applicant.match_score).toFixed(1)}%</span>
              )}
            </div>
            <p className="small-meta" style={{ marginTop: "8px" }}>
              {isReject
                ? "Please confirm rejecting this candidate. Finalized status and decision notes are recorded in application history."
                : "Confirm selecting or marking this candidate accepted. You can optionally include onboarding/offer details below."}
            </p>
          </div>

          {!isReject && (
            <label className="resume-selector">
              Selection Stage
              <select
                aria-label="Selection status choice"
                value={targetStatus}
                disabled={submitting || applicant.status === "selected"}
                onChange={(e) => setTargetStatus(e.target.value)}
              >
                <option value="selected">Selected</option>
                <option value="accepted">Accepted</option>
              </select>
            </label>
          )}

          <label className="resume-selector">
            Decision Reason (optional)
            <input
              maxLength={255}
              placeholder={isReject ? "e.g., Insufficient backend experience" : "e.g., Strong technical and interview performance"}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>

          <label className="resume-selector">
            Recruiter Note / Candidate Message (optional)
            <textarea
              maxLength={2000}
              rows={3}
              placeholder={
                isReject
                  ? "Optional constructive note for candidate and audit history..."
                  : "Optional next steps, offer timeline, or welcome note..."
              }
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={sendEmail}
              onChange={(e) => setSendEmail(e.target.checked)}
            />
            <span>Send {isReject ? "rejection" : "selection"} email notification to candidate</span>
          </label>

          {isDuplicateDecision && (
            <p className="small-meta">This application is already in status {formatStatusLabel(targetStatus)}.</p>
          )}
          {error && <p className="error" role="alert">{error}</p>}

          <div className="card-actions">
            <button
              type="submit"
              className={`button ${isReject ? "button-danger" : ""}`}
              disabled={submitting || isDuplicateDecision}
            >
              {submitting
                ? "Saving Decision..."
                : isReject
                  ? "Confirm Rejection"
                  : targetStatus === "accepted"
                    ? "Confirm Acceptance"
                    : "Confirm Selection"}
            </button>
            <button type="button" className="button button-secondary" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
