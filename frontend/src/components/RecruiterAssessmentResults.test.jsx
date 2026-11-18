import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RecruiterAssessmentResults from "./RecruiterAssessmentResults";

vi.mock("../api", () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));
import api from "../api";

describe("RecruiterAssessmentResults component", () => {
  const mockJobs = [{ id: 1, title: "Python Developer" }];
  const mockResults = [
    {
      assignment_id: 101,
      candidate_name: "Rahul Verma",
      candidate_email: "rahul@example.com",
      job_title: "Python Developer",
      assessment_title: "Python Level 1 Test",
      assigned_at: "2026-11-15T10:00:00Z",
      submitted_at: "2026-11-15T11:30:00Z",
      obtained_marks: 8,
      total_marks: 10,
      passing_marks: 5,
      percentage: 80.0,
      is_passed: true,
      result_status: "Selected for next round",
      test_status: "submitted",
      invitation_status: "sent",
      proctoring_event_count: 0,
    },
    {
      assignment_id: 102,
      candidate_name: "Pooja Sharma",
      candidate_email: "pooja@example.com",
      job_title: "Python Developer",
      assessment_title: "Python Level 1 Test",
      assigned_at: "2026-11-16T09:00:00Z",
      submitted_at: null,
      obtained_marks: null,
      total_marks: 10,
      passing_marks: 5,
      percentage: null,
      is_passed: null,
      result_status: null,
      test_status: "assigned",
      invitation_status: "sent",
      proctoring_event_count: 0,
    },
  ];

  it("renders table with required columns and accurate status labels", async () => {
    api.get.mockImplementation((path) => {
      if (path === "/api/recruiter/assessment-results") {
        return Promise.resolve({ data: mockResults });
      }
      if (path === "/api/recruiter/assessment-recordings") {
        return Promise.resolve({ data: { items: [] } });
      }
      return Promise.resolve({ data: [] });
    });

    render(<RecruiterAssessmentResults jobs={mockJobs} />);

    expect(await screen.findByRole("heading", { name: "Assessment Results & Candidate Performance" })).toBeInTheDocument();
    expect(screen.getByText("Candidate Name")).toBeInTheDocument();
    expect(screen.getByText("Job Position")).toBeInTheDocument();
    expect(screen.getByText("Assessment Name")).toBeInTheDocument();
    expect(screen.getByText("Assignment Date")).toBeInTheDocument();
    expect(screen.getByText("Submission Date")).toBeInTheDocument();
    expect(screen.getByText("Score")).toBeInTheDocument();
    expect(screen.getByText("Total Marks")).toBeInTheDocument();
    expect(screen.getByText("Percentage")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
    expect(screen.getByText("Assessment Status")).toBeInTheDocument();

    // Verify submitted candidate row
    expect(screen.getByText("Rahul Verma")).toBeInTheDocument();
    expect(screen.getByText("Selected for next round", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("80.0%")).toBeInTheDocument();

    // Verify pending candidate row
    expect(screen.getByText("Pooja Sharma")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Not submitted")).toBeInTheDocument();
  });

  it("opens View Answers modal with detailed questions and proctoring status", async () => {
    const detailData = {
      ...mockResults[0],
      questions: [
        {
          id: 1,
          order_index: 1,
          skill: "Python",
          difficulty: "Easy",
          question_text: "What is list comprehension?",
          options: ["Syntax to create lists", "Loop", "Function", "Tuple"],
          selected_option_index: 0,
          correct_option_index: 0,
          marks: 2,
          marks_awarded: 2,
          is_correct: true,
        },
      ],
      proctoring_events: [],
    };

    api.get.mockImplementation((path) => {
      if (path === "/api/recruiter/assessment-results") {
        return Promise.resolve({ data: [mockResults[0]] });
      }
      if (path === "/api/recruiter/assessment-results/101") {
        return Promise.resolve({ data: detailData });
      }
      if (path === "/api/recruiter/assessment-recordings") {
        return Promise.resolve({ data: { items: [] } });
      }
      return Promise.resolve({ data: [] });
    });

    render(<RecruiterAssessmentResults jobs={mockJobs} />);

    expect(await screen.findByText("Rahul Verma")).toBeInTheDocument();
    const viewBtn = screen.getByRole("button", { name: "View Answers" });
    fireEvent.click(viewBtn);

    expect(await screen.findByRole("dialog", { name: "Candidate Assessment Result Details" })).toBeInTheDocument();
    expect(screen.getByText("What is list comprehension?")).toBeInTheDocument();
    expect(screen.getByText("Clean (0 warnings)")).toBeInTheDocument();
  });
});
