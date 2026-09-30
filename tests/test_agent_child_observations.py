from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module


class RecordingObservation:
    def __init__(self, kwargs: dict) -> None:
        self.start_kwargs = kwargs
        self.updates: list[dict] = []

    def update(self, **kwargs) -> "RecordingObservation":
        self.updates.append(kwargs)
        return self


def test_retrieval_and_generation_are_child_observations(monkeypatch) -> None:
    observations: list[RecordingObservation] = []

    @contextmanager
    def record_observation(**kwargs):
        observation = RecordingObservation(kwargs)
        observations.append(observation)
        yield observation

    monkeypatch.setattr(agent_module, "start_observation", record_observation)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: False)

    agent = agent_module.LabAgent()
    result = agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message="Refund for student@vinuni.edu.vn?",
        correlation_id="req-12345678",
    )

    retrieval, generation = observations
    assert retrieval.start_kwargs["as_type"] == "retriever"
    assert "student@" not in str(retrieval.start_kwargs["input"])
    assert retrieval.updates[-1]["output"] == {"doc_count": 1}

    assert generation.start_kwargs["as_type"] == "generation"
    assert generation.start_kwargs["model"] == agent.model
    assert "student@" not in str(generation.start_kwargs["input"])
    usage_update = generation.updates[-1]
    assert usage_update["usage_details"] == {"input": result.tokens_in, "output": result.tokens_out}
    assert usage_update["cost_details"]["total"] == result.cost_usd
