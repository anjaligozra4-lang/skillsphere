const PLACEHOLDER_REGEX = /\[(?:college|school|university|degree|diploma|year|city|state|country|percentage|cgpa|gpa|grade|name|your\s+name|email|phone|company|role|title|project|certification|institution|start|end|month|date|address)[^\]]*\]/i;
const GENERIC_BRACKET_REGEX = /\[[A-Za-z][A-Za-z0-9\s/|.,-]{2,60}\]/g;

export const APPLICATION_STATUS_OPTIONS = [
  { value: "applied", label: "Applied" },
  { value: "under_review", label: "Under Review" },
  { value: "screening", label: "Screening" },
  { value: "shortlisted", label: "Shortlisted" },
  { value: "interview", label: "Interview" },
  { value: "selected", label: "Selected" },
  { value: "accepted", label: "Accepted" },
  { value: "hired", label: "Hired (legacy)" },
  { value: "rejected", label: "Rejected" },
  { value: "withdrawn", label: "Withdrawn" },
];

export function sanitizeDisplayText(value) {
  if (value == null || typeof value !== "string") return "";
  const cleanedLines = value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => {
      if (!line) return false;
      if (PLACEHOLDER_REGEX.test(line)) return false;
      const matches = line.match(GENERIC_BRACKET_REGEX);
      if (matches) {
        const remaining = line.replace(GENERIC_BRACKET_REGEX, "").replace(/[^A-Za-z0-9]+/g, "");
        if (remaining.length < 4) return false;
      }
      if (["not provided", "n/a", "na", "none", "-", "--"].includes(line.toLowerCase())) {
        return false;
      }
      return true;
    });
  return cleanedLines.join("\n").trim();
}

export function displayValue(value, fallback = "Not provided") {
  const cleaned = sanitizeDisplayText(value);
  return cleaned || fallback;
}

export function formatStatusLabel(status) {
  if (!status) return "Unknown";
  const found = APPLICATION_STATUS_OPTIONS.find((item) => item.value === status);
  if (found) return found.label;
  return String(status).replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatInvitationStatus(status) {
  const map = {
    not_invited: "Not Invited",
    pending: "Pending",
    sent: "Sent",
    failed: "Failed",
    completed: "Completed",
    expired: "Expired",
  };
  return map[status] || formatStatusLabel(status);
}

export function formatAssessmentStatus(status) {
  const map = {
    not_assigned: "Not Assigned",
    assigned: "Assigned",
    started: "Started",
    submitted: "Submitted",
    expired: "Expired",
  };
  return map[status] || formatStatusLabel(status);
}

export function formatInterviewMode(mode) {
  const map = {
    online: "Online",
    in_person: "Offline (In-Person)",
    offline: "Offline (In-Person)",
    phone: "Phone",
  };
  return map[mode] || formatStatusLabel(mode);
}

export function formatInterviewStatus(status) {
  const map = {
    scheduled: "Scheduled",
    rescheduled: "Rescheduled",
    completed: "Completed",
    cancelled: "Cancelled",
    no_show: "No Show",
  };
  return map[status] || formatStatusLabel(status);
}

export function formatRecommendation(rec) {
  const map = {
    strong_hire: "Strong Hire",
    hire: "Hire",
    hold: "On Hold",
    no_hire: "No Hire",
  };
  return map[rec] || formatStatusLabel(rec);
}

export function formatNotificationType(type) {
  const map = {
    application_shortlisted: "Shortlisted Email",
    application_selected: "Selection Email",
    application_rejected: "Rejection Email",
    interview_scheduled: "Interview Scheduled",
    interview_rescheduled: "Interview Rescheduled",
    interview_cancelled: "Interview Cancelled",
  };
  return map[type] || formatStatusLabel(type);
}

export function getStatusBadgeClass(status) {
  if (["shortlisted", "selected", "accepted", "hired", "sent", "submitted", "completed", "strong_hire", "hire"].includes(status)) {
    return "status-badge status-badge-success";
  }
  if (["applied", "under_review", "screening", "interview", "assigned", "started", "scheduled", "rescheduled"].includes(status)) {
    return "status-badge status-badge-info";
  }
  if (["rejected", "failed", "expired", "cancelled", "no_show", "no_hire"].includes(status)) {
    return "status-badge status-badge-danger";
  }
  return "status-badge status-badge-neutral";
}

export async function parseApiError(requestError, fallback = "An unexpected error occurred.") {
  const data = requestError?.response?.data;
  if (!data) return requestError?.message || fallback;
  if (typeof data === "string") return data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const parsed = JSON.parse(text);
      return parsed?.detail || fallback;
    } catch {
      return fallback;
    }
  }
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return data.detail || fallback;
}
