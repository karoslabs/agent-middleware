"""Feedback and evaluation store.

Every reviewer verdict on a run is kept so it can be mined later: the highest
rated (or reviewer-corrected) outputs are exactly the material a few-shot example
should be made of, and ``promote`` turns one into an example in place, recording
the link in both directions.

Feedback lives in a root collection carrying ``agent_id`` and ``run_id``, so the
two access patterns that matter -- "all feedback for this run" and "the best
feedback for this agent" -- are both single indexed queries.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_query import FieldFilter

from app.api.schemas.prompt import FewShotExampleCreate
from app.api.schemas.run import FeedbackCreate, FeedbackPromoteRequest
from app.core.enums import ExampleSource, FeedbackStatus
from app.core.exceptions import InvalidStateError, ResourceNotFoundError
from app.db.firestore import FEEDBACK, FirestoreDB, generate_id, snapshot_to_dict, utcnow
from app.services.prompts import PromptService
from app.services.runs import RunService

logger = logging.getLogger(__name__)

# Keys an engine artifact commonly uses for its main text body.
_OUTPUT_TEXT_KEYS = ("content", "text", "html", "body", "output", "markdown")


class FeedbackService:
    """Stores reviewer verdicts and turns the good ones into training examples."""

    def __init__(self, db: FirestoreDB, runs: RunService, prompts: PromptService) -> None:
        self._db = db
        self._runs = runs
        self._prompts = prompts

    # --- Writes ------------------------------------------------------------

    async def add(self, agent_id: str, run_id: str, payload: FeedbackCreate) -> dict[str, Any]:
        """Record feedback for a run.

        The run must already be registered (via ``POST /agents/{id}/runs`` or by
        dispatching through ``POST /agents/{id}/jobs``); that is what ties the
        verdict to the prompt and template version it is judging.
        """

        await self._runs.get(run_id, agent_id=agent_id)

        feedback_id = generate_id()
        now = utcnow()
        document = {
            "run_id": run_id,
            "agent_id": agent_id,
            "rating": payload.rating,
            "status": payload.status.value,
            "correction_notes": payload.correction_notes,
            "corrected_output": payload.corrected_output,
            "reviewer": payload.reviewer,
            "tags": payload.tags,
            "promoted_example_id": None,
            "created_at": now,
            "updated_at": now,
        }
        await self._db.document(FEEDBACK, feedback_id).set(document)

        logger.info(
            "Stored feedback %s for run %s (agent=%s rating=%s status=%s)",
            feedback_id,
            run_id,
            agent_id,
            payload.rating,
            payload.status.value,
        )
        return {**document, "id": feedback_id}

    async def promote(
        self, agent_id: str, feedback_id: str, payload: FeedbackPromoteRequest
    ) -> dict[str, Any]:
        """Turn a piece of feedback into an active few-shot example."""

        feedback = await self.get(agent_id, feedback_id)
        if feedback.get("promoted_example_id"):
            raise InvalidStateError(
                f"feedback '{feedback_id}' has already been promoted to example "
                f"'{feedback['promoted_example_id']}'"
            )

        run = await self._runs.get(feedback["run_id"], agent_id=agent_id)
        user_input = payload.user_input or derive_input_text(run)
        assistant_output = payload.assistant_output or derive_output_text(run, feedback)

        if not user_input or not assistant_output:
            raise InvalidStateError(
                "cannot derive an example from this feedback; supply 'user_input' and "
                "'assistant_output' explicitly"
            )

        example = await self._prompts.create_example(
            agent_id,
            FewShotExampleCreate(
                user_input=user_input,
                assistant_output=assistant_output,
                label=payload.label or f"from run {feedback['run_id']}",
                tags=payload.tags,
                position=payload.position,
                extra={
                    "feedback_id": feedback_id,
                    "rating": feedback.get("rating"),
                    "reviewer": feedback.get("reviewer"),
                },
            ),
            source=ExampleSource.FEEDBACK,
            source_run_id=feedback["run_id"],
        )

        patch = {"promoted_example_id": example["id"], "updated_at": utcnow()}
        await self._db.document(FEEDBACK, feedback_id).update(patch)
        logger.info("Promoted feedback %s to example %s", feedback_id, example["id"])
        return example

    # --- Reads -------------------------------------------------------------

    async def get(self, agent_id: str, feedback_id: str) -> dict[str, Any]:
        snapshot = await self._db.document(FEEDBACK, feedback_id).get()
        if not snapshot.exists:
            raise ResourceNotFoundError("feedback", feedback_id)

        feedback = snapshot_to_dict(snapshot)
        if feedback.get("agent_id") != agent_id:
            raise ResourceNotFoundError("feedback", feedback_id)
        return feedback

    async def list_for_run(self, agent_id: str, run_id: str) -> list[dict[str, Any]]:
        """All verdicts on one run, oldest first.

        A single equality filter needs no composite index, so the ordering is
        applied in process.
        """

        await self._runs.get(run_id, agent_id=agent_id)
        feedback = [
            snapshot_to_dict(snapshot)
            async for snapshot in self._db.collection(FEEDBACK)
            .where(filter=FieldFilter("run_id", "==", run_id))
            .stream()
        ]
        feedback.sort(key=lambda item: item.get("created_at") or utcnow())
        return feedback

    async def list_for_agent(
        self,
        agent_id: str,
        *,
        min_rating: int | None = None,
        status: FeedbackStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Feedback for an agent, best rated first, plus whether more follow."""

        query = self._db.collection(FEEDBACK).where(
            filter=FieldFilter("agent_id", "==", agent_id)
        )
        if status is not None:
            query = query.where(filter=FieldFilter("status", "==", status.value))
        if min_rating is not None:
            query = query.where(filter=FieldFilter("rating", ">=", min_rating))

        if offset:
            query = query.offset(offset)

        # Ordering needs a composite index (agent_id + rating), declared in
        # firestore.indexes.json. If it is missing, Firestore fails the whole
        # query with FailedPrecondition -- which is how a page that merely
        # LISTS feedback returned 500 while the index sat undeployed.
        #
        # Degrade instead: fetch unordered and sort in process. Wrong at scale,
        # which is why the index exists, but a listing that cannot be sorted
        # should still list. Index builds take minutes and any new query shape
        # reintroduces this, so the fallback is not a substitute for the index
        # -- it is the difference between a slow page and a broken one.
        try:
            items = [
                snapshot_to_dict(snapshot)
                async for snapshot in query.order_by("rating", direction="DESCENDING")
                .limit(limit + 1)
                .stream()
            ]
        except FailedPrecondition:
            logger.warning(
                "run_feedback is missing its composite index; returning unordered results. "
                "Deploy firestore.indexes.json.",
                extra={"agent_id": agent_id},
            )
            rows = [snapshot_to_dict(snapshot) async for snapshot in query.stream()]
            rows.sort(key=lambda r: r.get("rating") or 0, reverse=True)
            items = rows[: limit + 1]

        return items[:limit], len(items) > limit

    async def candidate_examples(
        self,
        agent_id: str,
        *,
        min_rating: int = 4,
        status: FeedbackStatus | None = FeedbackStatus.APPROVED,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Feedback distilled into example candidates the portal can review.

        Defaults to approved, well-rated runs: the ones worth teaching the agent
        with. Each candidate carries the run's input and the best available
        output (the reviewer's correction when there is one).
        """

        feedback_items, has_more = await self.list_for_agent(
            agent_id, min_rating=min_rating, status=status, limit=limit, offset=offset
        )

        candidates: list[dict[str, Any]] = []
        for feedback in feedback_items:
            try:
                run = await self._runs.get(feedback["run_id"], agent_id=agent_id)
            except ResourceNotFoundError:
                run = {}

            candidates.append(
                {
                    "feedback_id": feedback["id"],
                    "run_id": feedback["run_id"],
                    "rating": feedback["rating"],
                    "status": feedback["status"],
                    "user_input": derive_input_text(run),
                    "assistant_output": derive_output_text(run, feedback),
                    "correction_notes": feedback.get("correction_notes"),
                    "reviewer": feedback.get("reviewer"),
                    "already_promoted": bool(feedback.get("promoted_example_id")),
                    "created_at": feedback["created_at"],
                }
            )
        return candidates, has_more


def derive_input_text(run: dict[str, Any]) -> str | None:
    """Best-effort textual rendering of what the run was asked to do."""

    payload = run.get("input_payload") or {}
    job_input = payload.get("input", payload) if isinstance(payload, dict) else payload
    return _as_text(job_input)


def derive_output_text(run: dict[str, Any], feedback: dict[str, Any]) -> str | None:
    """The reviewer's correction if present, else what the run produced."""

    corrected = (feedback.get("corrected_output") or "").strip()
    if corrected:
        return corrected

    output = run.get("output")
    if isinstance(output, dict):
        for key in _OUTPUT_TEXT_KEYS:
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return _as_text(output)


def _as_text(value: Any) -> str | None:
    """Render a stored JSON value as text, or ``None`` when there is nothing to show."""

    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if not value:
        return None
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
