"""Terminal entry point for the EOC multi-agent workflow."""

import json

from readforge.agents.state import CaseInput, Evidence
from readforge.agents.workflow import workflow


def main() -> None:
    question = input("Question: ").strip()
    plan_name = input("Plan name: ").strip() or None
    coverage_year_value = input("Coverage year: ").strip()
    service_date = input("Service date (YYYY-MM-DD, optional): ").strip() or None
    evidence_text = input("Relevant EOC text (optional): ").strip()

    evidence = []
    if evidence_text:
        page_number_value = input("EOC page number: ").strip()
        evidence = [
            Evidence(
                evidence_id="E1",
                page_number=int(page_number_value),
                content=evidence_text,
                document_type="eoc",
                plan_name=plan_name,
                coverage_year=(
                    int(coverage_year_value) if coverage_year_value else None
                ),
                official=True,
            )
        ]

    case = CaseInput(
        question=question,
        plan_name=plan_name,
        coverage_year=int(coverage_year_value) if coverage_year_value else None,
        service_date=service_date,
        evidence=evidence,
    )
    result = workflow.invoke({"case": case}, config={"max_concurrency": 2})
    print(json.dumps(result["final_response"], indent=2))


if __name__ == "__main__":
    main()
