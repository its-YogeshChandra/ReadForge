"""Checks for multi-agent routing and deterministic evidence scoring."""

import unittest
from unittest.mock import patch

from readforge.agents.provider import LLMProvider
from readforge.agents.state import CaseInput
from readforge.agents.workflow import _score_finding, workflow


class MultiAgentWorkflowTest(unittest.TestCase):
    def test_routes_specialists_and_scores_each_finding(self) -> None:
        def fake_response(
            system_prompt: str,
            request: dict,
            response_model: type,
        ) -> dict:
            if "intent router" in system_prompt:
                return {
                    "intents": ["coverage", "referral"],
                    "clarification_question": None,
                }
            if "coverage specialist" in system_prompt:
                return {
                    "findings": [
                        {
                            "conclusion": "The service is conditionally covered.",
                            "evidence_ids": ["E1"],
                            "missing_information": [],
                            "user_context": [],
                            "conflicts": [],
                        },
                        {
                            "conclusion": "Payment is guaranteed.",
                            "evidence_ids": ["UNKNOWN"],
                            "missing_information": [],
                            "user_context": ["Current member eligibility"],
                            "conflicts": [],
                        },
                    ]
                }
            return {
                "findings": [
                    {
                        "conclusion": "A PCP referral is required.",
                        "evidence_ids": ["E1"],
                        "missing_information": [],
                        "user_context": [],
                        "conflicts": [],
                    }
                ]
            }

        case = {
            "question": "Is this procedure covered and do I need a referral?",
            "plan_name": "Example HMO",
            "coverage_year": 2026,
            "service_date": "2026-10-02",
            "evidence": [
                {
                    "evidence_id": "E1",
                    "page_number": 43,
                    "content": "Specialist services require a PCP referral.",
                    "document_type": "eoc",
                    "plan_name": "Example HMO",
                    "coverage_year": 2026,
                    "official": True,
                }
            ],
        }

        with patch.object(LLMProvider, "invoke_json", side_effect=fake_response):
            result = workflow.invoke({"case": case}, config={"max_concurrency": 2})

        response = result["final_response"]
        self.assertEqual(
            [item["agent"] for item in response["results"]],
            ["coverage", "referral"],
        )
        self.assertEqual(response["results"][0]["findings"][0]["evidence_score"], 100)
        self.assertEqual(response["results"][0]["findings"][1]["evidence_score"], 30)
        self.assertEqual(response["overall_evidence_score"], 30)
        self.assertTrue(response["requires_human_review"])

    def test_missing_context_returns_a_clarification_without_calling_llm(self) -> None:
        with patch.object(LLMProvider, "invoke_json") as invoke_json:
            result = workflow.invoke({"case": {"question": "Is this covered?"}})

        invoke_json.assert_not_called()
        response = result["final_response"]
        self.assertEqual(response["results"], [])
        self.assertIsNone(response["overall_evidence_score"])
        self.assertIn("relevant evidence", response["clarification_question"])

    def test_missing_plan_metadata_does_not_block_document_answer(self) -> None:
        def fake_response(system_prompt: str, *_args) -> dict:
            if "intent router" in system_prompt:
                return {"intents": ["coverage"], "clarification_question": None}
            return {
                "findings": [
                    {
                        "conclusion": "The document describes office visits.",
                        "evidence_ids": ["E1"],
                        "missing_information": [],
                        "user_context": ["Plan year"],
                        "conflicts": [],
                    }
                ]
            }

        case = {
            "question": "Are office visits covered?",
            "evidence": [
                {
                    "evidence_id": "E1",
                    "page_number": 2,
                    "content": "Office visits are subject to cost sharing.",
                    "document_type": "eoc",
                    "official": False,
                }
            ],
        }
        with patch.object(LLMProvider, "invoke_json", side_effect=fake_response):
            response = workflow.invoke({"case": case})["final_response"]

        self.assertIsNone(response["clarification_question"])
        self.assertEqual(response["results"][0]["agent"], "coverage")
        self.assertEqual(response["overall_evidence_score"], 100)
        self.assertFalse(response["requires_human_review"])

    def test_explicit_plan_metadata_conflict_reduces_confidence(self) -> None:
        case = CaseInput.model_validate(
            {
                "question": "Is this covered?",
                "plan_name": "Requested Plan",
                "coverage_year": 2026,
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "page_number": 2,
                        "content": "The service is covered.",
                        "document_type": "eoc",
                        "plan_name": "Different Plan",
                        "coverage_year": 2025,
                        "official": False,
                    }
                ],
            }
        )

        finding = _score_finding(
            case,
            "coverage",
            {
                "conclusion": "The service is covered.",
                "evidence_ids": ["E1"],
                "missing_information": [],
                "user_context": [],
                "conflicts": [],
            },
        )

        self.assertEqual(finding["evidence_score"], 60)
        self.assertEqual(finding["score_breakdown"]["metadata_consistent"], 0)
        self.assertEqual(len(finding["conflicts"]), 2)


if __name__ == "__main__":
    unittest.main()
