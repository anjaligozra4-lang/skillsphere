import { useCallback, useEffect, useState } from "react";
import api from "../api";
import {
  formatInterviewMode,
  formatInterviewStatus,
  formatNotificationType,
  formatRecommendation,
  getStatusBadgeClass,
  parseApiError,
} from "../utils/profileUtils";

export default function AdminInterviewsAndNotifications({ onFeedback }) {
  const [summary, setSummary] = useState({ total: 0, by_status: {} });
  const [interviews, setInterviews] = useState([]);
  const [interviewsLoading, setInterviewsLoading] = useState(true);
  const [intSearch, setIntSearch] = useState("");
  const [intStatus, setIntStatus] = useState("");
  const [intMode, setIntMode] = useState("");
  const [intFromDate, setIntFromDate] = useState("");
  const [intToDate, setIntToDate] = useState("");

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [notifications, setNotifications] = useState([]);
  const [notifCounts, setNotifCounts] = useState({});
  const [notifLoading, setNotifLoading] = useState(true);
  const [notifSearch, setNotifSearch] = useState("");
  const [notifStatus, setNotifStatus] = useState("");
  const [notifType, setNotifType] = useState("");
  const [notifFromDate, setNotifFromDate] = useState("");
  const [notifToDate, setNotifToDate] = useState("");

  const loadInterviews = useCallback(async (overrides = {}) => {
    setInterviewsLoading(true);
    try {
      const [sumRes, listRes] = await Promise.all([
        api.get("/api/admin/interviews/summary").catch(() => ({ data: { total: 0, by_status: {} } })),
        api.get("/api/admin/interviews", {
          params: {
            q: (overrides.q !== undefined ? overrides.q : intSearch) || undefined,
            status: (overrides.status !== undefined ? overrides.status : intStatus) || undefined,
            interview_mode: (overrides.interview_mode !== undefined ? overrides.interview_mode : intMode) || undefined,
            from_date: (overrides.from_date !== undefined ? overrides.from_date : intFromDate) || undefined,
            to_date: (overrides.to_date !== undefined ? overrides.to_date : intToDate) || undefined,
          },
        }),
      ]);
      setSummary(sumRes?.data || { total: 0, by_status: {} });
      setInterviews(Array.isArray(listRes?.data?.items) ? listRes.data.items : []);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load admin interview oversight."), true);
    } finally {
      setInterviewsLoading(false);
    }
  }, [intSearch, intStatus, intMode, intFromDate, intToDate, onFeedback]);

  const loadNotifications = useCallback(async (overrides = {}) => {
    setNotifLoading(true);
    try {
      const res = await api.get("/api/admin/notifications", {
        params: {
          q: (overrides.q !== undefined ? overrides.q : notifSearch) || undefined,
          status: (overrides.status !== undefined ? overrides.status : notifStatus) || undefined,
          notification_type: (overrides.notification_type !== undefined ? overrides.notification_type : notifType) || undefined,
          from_date: (overrides.from_date !== undefined ? overrides.from_date : notifFromDate) || undefined,
          to_date: (overrides.to_date !== undefined ? overrides.to_date : notifToDate) || undefined,
        },
      });
      setNotifications(Array.isArray(res?.data?.items) ? res.data.items : []);
      setNotifCounts(res?.data?.counts_by_status || {});
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load notification audit logs."), true);
    } finally {
      setNotifLoading(false);
    }
  }, [notifSearch, notifStatus, notifType, notifFromDate, notifToDate, onFeedback]);

  useEffect(() => {
    loadInterviews();
    loadNotifications();
  }, [loadInterviews, loadNotifications]);

  const openInterviewDetail = async (interviewId) => {
    setDetailLoading(true);
    try {
      const res = await api.get(`/api/admin/interviews/${interviewId}`);
      setDetail(res?.data || null);
    } catch (requestError) {
      onFeedback?.(await parseApiError(requestError, "Unable to load interview details."), true);
    } finally {
      setDetailLoading(false);
    }
  };

  const resetInterviewFilters = () => {
    setIntSearch("");
    setIntStatus("");
    setIntMode("");
    setIntFromDate("");
    setIntToDate("");
    loadInterviews({ q: "", status: "", interview_mode: "", from_date: "", to_date: "" });
  };

  const resetNotificationFilters = () => {
    setNotifSearch("");
    setNotifStatus("");
    setNotifType("");
    setNotifFromDate("");
    setNotifToDate("");
    loadNotifications({ q: "", status: "", notification_type: "", from_date: "", to_date: "" });
  };

  const statusBuckets = summary?.by_status || {};

  return (
    <>
      <section className="panel admin-table-panel" id="admin-interviews">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Read-Only Platform Oversight</span>
            <h2>Interview Management Overview</h2>
          </div>
          <span className="table-count">{summary?.total ?? interviews.length} total interviews</span>
        </div>

        <div className="stats-grid" style={{ marginBottom: "16px" }}>
          {[
            ["Scheduled", statusBuckets.scheduled || 0],
            ["Rescheduled", statusBuckets.rescheduled || 0],
            ["Completed", statusBuckets.completed || 0],
            ["Cancelled", statusBuckets.cancelled || 0],
            ["No Show", statusBuckets.no_show || 0],
          ].map(([label, count]) => (
            <div className="stat-card" key={label}>
              <strong>{count}</strong>
              <span>{label}</span>
            </div>
          ))}
        </div>

        <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); loadInterviews(); }}>
          <input
            aria-label="Search admin interviews"
            placeholder="Search candidate, email, job, company, or round"
            value={intSearch}
            onChange={(e) => setIntSearch(e.target.value)}
          />
          <select aria-label="Filter admin interviews by status" value={intStatus} onChange={(e) => setIntStatus(e.target.value)}>
            <option value="">All interview statuses</option>
            <option value="scheduled">Scheduled</option>
            <option value="rescheduled">Rescheduled</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
            <option value="no_show">No Show</option>
          </select>
          <select aria-label="Filter admin interviews by mode" value={intMode} onChange={(e) => setIntMode(e.target.value)}>
            <option value="">All modes</option>
            <option value="online">Online</option>
            <option value="in_person">Offline (In-Person)</option>
            <option value="phone">Phone</option>
          </select>
          <input type="date" aria-label="Admin interviews from date" value={intFromDate} onChange={(e) => setIntFromDate(e.target.value)} />
          <input type="date" aria-label="Admin interviews to date" value={intToDate} onChange={(e) => setIntToDate(e.target.value)} />
          <button type="submit" className="button button-small">Filter Interviews</button>
          <button type="button" className="button button-secondary button-small" onClick={resetInterviewFilters}>Reset</button>
        </form>

        {interviewsLoading && <p className="loading-message" role="status">Loading interviews...</p>}

        {!interviewsLoading && (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Job &amp; Round</th>
                  <th>Date &amp; Mode</th>
                  <th>Status</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {interviews.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Candidate">
                      <strong>{item.candidate_name || "Candidate"}</strong>
                      <span>{item.candidate_email}</span>
                    </td>
                    <td data-label="Job & Round">
                      <strong>{item.job_title}</strong>
                      <span>{item.company} · Round {item.round_number} ({item.round_name})</span>
                    </td>
                    <td data-label="Date & Mode">
                      <span>{new Date(item.scheduled_at).toLocaleString()} ({item.timezone})</span>
                      <div className="small-meta">{formatInterviewMode(item.interview_mode)}</div>
                    </td>
                    <td data-label="Status">
                      <span className={getStatusBadgeClass(item.status)}>{formatInterviewStatus(item.status)}</span>
                    </td>
                    <td data-label="Details">
                      <button
                        type="button"
                        className="button button-secondary button-small"
                        onClick={() => openInterviewDetail(item.id)}
                      >
                        View Details
                      </button>
                    </td>
                  </tr>
                ))}
                {!interviews.length && (
                  <tr><td colSpan="5" className="table-empty">No interviews match the selected filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel admin-table-panel" id="admin-notifications">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Email Delivery Oversight</span>
            <h2>Email Notification Logs</h2>
          </div>
          <div className="badge-row">
            <span className="status-badge status-badge-success">Sent: {notifCounts.sent || 0}</span>
            <span className="status-badge status-badge-danger">Failed: {notifCounts.failed || 0}</span>
            <span className="status-badge status-badge-neutral">Pending: {notifCounts.pending || 0}</span>
          </div>
        </div>

        <form className="admin-filters" onSubmit={(e) => { e.preventDefault(); loadNotifications(); }}>
          <input
            aria-label="Search admin notification logs"
            placeholder="Search recipient, subject, type, or job"
            value={notifSearch}
            onChange={(e) => setNotifSearch(e.target.value)}
          />
          <select aria-label="Filter admin notifications by status" value={notifStatus} onChange={(e) => setNotifStatus(e.target.value)}>
            <option value="">All statuses</option>
            <option value="sent">Sent</option>
            <option value="failed">Failed</option>
            <option value="pending">Pending</option>
          </select>
          <select aria-label="Filter admin notifications by type" value={notifType} onChange={(e) => setNotifType(e.target.value)}>
            <option value="">All types</option>
            <option value="application_shortlisted">Shortlisted</option>
            <option value="application_selected">Selected</option>
            <option value="application_rejected">Rejected</option>
            <option value="interview_scheduled">Interview Scheduled</option>
            <option value="interview_rescheduled">Interview Rescheduled</option>
            <option value="interview_cancelled">Interview Cancelled</option>
          </select>
          <input type="date" aria-label="Admin notifications from date" value={notifFromDate} onChange={(e) => setNotifFromDate(e.target.value)} />
          <input type="date" aria-label="Admin notifications to date" value={notifToDate} onChange={(e) => setNotifToDate(e.target.value)} />
          <button type="submit" className="button button-small">Filter Notifications</button>
          <button type="button" className="button button-secondary button-small" onClick={resetNotificationFilters}>Reset</button>
        </form>

        {notifLoading && <p className="loading-message" role="status">Loading notification logs...</p>}

        {!notifLoading && (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Job</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Sent / Logged At</th>
                </tr>
              </thead>
              <tbody>
                {notifications.map((item) => (
                  <tr key={item.id}>
                    <td data-label="Recipient">
                      <strong>{item.recipient_name || "Candidate"}</strong>
                      <span>{item.recipient_email}</span>
                    </td>
                    <td data-label="Job">{item.job_title || "—"}</td>
                    <td data-label="Type">
                      <strong>{formatNotificationType(item.notification_type)}</strong>
                      <span>{item.subject}</span>
                      {item.error_message && <div className="resume-error small-meta">{item.error_message}</div>}
                    </td>
                    <td data-label="Status">
                      <span className={getStatusBadgeClass(item.status)}>{item.status.toUpperCase()}</span>
                    </td>
                    <td data-label="Sent / Logged At">
                      <span>{item.sent_at ? new Date(item.sent_at).toLocaleString() : new Date(item.created_at).toLocaleString()}</span>
                      <div className="small-meta">Retries: {item.retry_count ?? 0}</div>
                    </td>
                  </tr>
                ))}
                {!notifications.length && (
                  <tr><td colSpan="5" className="table-empty">No notification logs match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {(detail || detailLoading) && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Admin Interview Details">
          <div className="modal-panel panel">
            <div className="modal-header">
              <div>
                <span className="eyebrow">Read-Only Interview Audit</span>
                <h2>{detail?.candidate_name || "Loading..."} — {detail?.round_name || ""}</h2>
                {detail && (
                  <p className="modal-subtitle">
                    {detail.job_title} · {detail.company} · Round {detail.round_number}
                  </p>
                )}
              </div>
              <button type="button" className="button button-secondary button-small" onClick={() => setDetail(null)}>
                Close ✕
              </button>
            </div>
            {detailLoading && !detail && <p className="loading-message">Loading interview details...</p>}
            {detail && (
              <div className="modal-body">
                <div className="assessment-meta-grid">
                  <div><span>Status</span><strong>{formatInterviewStatus(detail.status)}</strong></div>
                  <div><span>Mode</span><strong>{formatInterviewMode(detail.interview_mode)}</strong></div>
                  <div><span>Scheduled</span><strong>{new Date(detail.scheduled_at).toLocaleString()} ({detail.timezone})</strong></div>
                  <div><span>Interviewer</span><strong>{detail.interviewer_name || "Not specified"}</strong></div>
                </div>
                {detail.meeting_link && <p><strong>Meeting Link:</strong> {detail.meeting_link}</p>}
                {detail.location && <p><strong>Location:</strong> {detail.location}</p>}
                {detail.recommendation && <p><strong>Outcome:</strong> {formatRecommendation(detail.recommendation)}</p>}
                {detail.feedback && <p><strong>Feedback:</strong> {detail.feedback}</p>}
                {detail.notifications?.length > 0 && (
                  <div className="subpanel">
                    <h3>Linked Email Notifications ({detail.notifications.length})</h3>
                    <ul className="compact-list">
                      {detail.notifications.map((n) => (
                        <li key={n.id}>
                          <strong>{formatNotificationType(n.notification_type)}</strong> — {n.status.toUpperCase()} ({n.recipient_email})
                          {n.error_message ? ` — ${n.error_message}` : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
