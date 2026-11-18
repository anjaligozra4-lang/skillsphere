import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AssignAssessmentModal from "./AssignAssessmentModal";

vi.mock("../api", () => ({
  default: { post: vi.fn() },
}));
import api from "../api";

const assessments = [
  { id: 10, job_id: 7, title: "Python Assessment", status: "published", job_title: "Python Developer", total_questions: 5, total_marks: 10, passing_marks: 5, duration_minutes: 30 },
  { id: 11, job_id: 8, title: "Draft Assessment", status: "draft", job_title: "Java Developer" },
];

const applicants = [
  { id: 101, job_id: 7, candidate: "Candidate One", email: "one@example.com", status: "shortlisted" },
  { id: 102, job_id: 7, candidate: "Candidate Two", email: "two@example.com", status: "shortlisted" },
  { id: 103, job_id: 8, candidate: "Candidate Three", email: "three@example.com", status: "shortlisted" },
];

describe("AssignAssessmentModal", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows only published assessments and candidates for the selected job", () => {
    render(
      <AssignAssessmentModal
        open
        onClose={vi.fn()}
        assessments={assessments}
        shortlistedApplicants={applicants}
      />
    );

    expect(screen.getByRole("option", { name: /Python Assessment/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Draft Assessment/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Candidate One/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate Two/)).toBeInTheDocument();
    expect(screen.queryByText(/Candidate Three/)).not.toBeInTheDocument();
  });

  it("sends selected application IDs and displays the assignment summary", async () => {
    const onAssigned = vi.fn();
    api.post.mockResolvedValue({
      data: {
        assigned_count: 1,
        sent_count: 1,
        failed_count: 0,
        skipped_count: 0,
        results: [
          {
            application_id: 101,
            candidate: "Candidate One",
            email: "one@example.com",
            invitation_status: "sent",
            message: "Invitation email sent",
          },
        ],
      },
    });

    render(
      <AssignAssessmentModal
        open
        onClose={vi.fn()}
        assessments={assessments}
        shortlistedApplicants={applicants}
        onAssigned={onAssigned}
      />
    );

    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: /review assignment/i }));

    expect(await screen.findByText(/Candidates to receive unique invitation links/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /confirm & send invitations/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/recruiter/assessments/10/assign",
        expect.objectContaining({ application_ids: [102], expires_at: null })
      );
    });

    expect(await screen.findByText("Assignment Complete")).toBeInTheDocument();
    expect(screen.getByText(/Emails Sent:/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate One/)).toBeInTheDocument();
    expect(onAssigned).toHaveBeenCalled();
  });
});


