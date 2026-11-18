import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RecruiterAssessments from "./RecruiterAssessments";

vi.mock("../api", () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));
import api from "../api";

describe("RecruiterAssessments empty job state", () => {
  it("requires an approved published job before enabling assessment creation", async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<RecruiterAssessments jobs={[{ id: 4, title: "Pending role", status: "pending" }]} />);

    expect(await screen.findByText(/approved, published job is required/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create assessment/i })).toBeDisabled();
  });

  it("points recruiters to the job form when no jobs are available", async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<RecruiterAssessments jobs={[]} />);

    expect(await screen.findByText(/post a job first/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to Post a Job" })).toHaveAttribute(
      "href",
      "#recruiter-post-job",
    );
    expect(screen.getByRole("button", { name: /create assessment/i })).toBeDisabled();
  });

  it("lets the recruiter edit their AI generated question before adding it", async () => {
    const question = {
      id: 51,
      skill: "Python",
      category: "AI Generated",
      difficulty: "Medium",
      question_text: "Which Python collection stores key-value pairs?",
      options: ["dict", "list", "set", "tuple"],
      correct_option_index: 0,
      explanation: "A dictionary maps keys to values.",
      marks: 2,
      is_editable: true,
    };
    api.get.mockImplementation((path) => {
      if (path === "/api/recruiter/assessments") return Promise.resolve({ data: [] });
      if (path === "/api/recruiter/question-bank") {
        return Promise.resolve({ data: { items: [question], skills: ["Python"], categories: ["AI Generated"], job_skills: ["Python"] } });
      }
      return Promise.resolve({ data: [] });
    });
    api.put.mockResolvedValue({ data: { ...question, question_text: "Edited Python MCQ" } });

    render(<RecruiterAssessments jobs={[{ id: 7, title: "Python role", status: "published" }]} />);
    fireEvent.click(screen.getByRole("button", { name: /create assessment/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Question text" }), {
      target: { value: "Edited Python MCQ" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Question Edits" }));

    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/recruiter/question-bank/51",
      expect.objectContaining({ question_text: "Edited Python MCQ", correct_option_index: 0 }),
    ));
    expect(await screen.findByText("Edited Python MCQ")).toBeInTheDocument();
  });

  it("displays covered and missing job required skills when building an assessment", async () => {
    const question = {
      id: 51,
      skill: "Python",
      category: "Technical",
      difficulty: "Medium",
      question_text: "What is Python?",
      options: ["Language", "Database", "OS", "Browser"],
      correct_option_index: 0,
      marks: 2,
    };
    api.get.mockImplementation((path) => {
      if (path === "/api/recruiter/assessments") return Promise.resolve({ data: [] });
      if (path === "/api/recruiter/question-bank") {
        return Promise.resolve({
          data: {
            items: [question],
            skills: ["Python", "FastAPI"],
            categories: ["Technical"],
            job_skills: ["Python", "FastAPI"],
          },
        });
      }
      return Promise.resolve({ data: [] });
    });

    render(<RecruiterAssessments jobs={[{ id: 7, title: "Python role", status: "published" }]} />);
    fireEvent.click(screen.getByRole("button", { name: /create assessment/i }));

    expect(await screen.findByText("Job Required Skills Coverage")).toBeInTheDocument();
    expect(screen.getByText(/⚠ Python \(Not covered\)/)).toBeInTheDocument();
    expect(screen.getByText(/⚠ FastAPI \(Not covered\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));

    expect(await screen.findByText(/✓ Python \(1 question\)/)).toBeInTheDocument();
    expect(screen.getByText(/⚠ FastAPI \(Not covered\)/)).toBeInTheDocument();
    expect(screen.getByText(/Skill Gap Warning/)).toBeInTheDocument();
  });
});
