from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .models import JsonDict


@dataclass(frozen=True)
class TopicMatch:
  topic: str
  score: float
  reason: str

  def to_dict(self) -> JsonDict:
    return {"topic": self.topic, "score": round(self.score, 3), "reason": self.reason}


def fuzzy_topic_matches(topics: list[str], query: str, limit: int = 20) -> list[TopicMatch]:
  normalized_query = query.strip().lower()
  if not normalized_query:
    return []
  matches = [match for topic in topics if (match := score_topic_match(topic, normalized_query)) is not None]
  matches.sort(key=lambda match: (-match.score, match.topic))
  return matches[: max(0, limit)]


def score_topic_match(topic: str, normalized_query: str) -> TopicMatch | None:
  normalized_topic = topic.lower()
  query_tokens = topic_tokens(normalized_query)
  candidate_tokens = topic_tokens(normalized_topic)
  candidates: list[tuple[float, str]] = []

  if normalized_query in normalized_topic:
    length_bonus = min(len(normalized_query) / max(len(normalized_topic), 1), 1.0) * 0.05
    candidates.append((0.9 + length_bonus, "substring"))

  if query_tokens and candidate_tokens:
    overlap = len(set(query_tokens) & set(candidate_tokens)) / len(set(query_tokens))
    if overlap > 0:
      candidates.append((0.75 + 0.15 * overlap, "token_overlap"))
    approximate = approximate_token_score(query_tokens, candidate_tokens)
    if approximate >= 0.72:
      candidates.append((0.45 + 0.35 * approximate, "approximate"))

  full_similarity = difflib.SequenceMatcher(None, normalized_query, normalized_topic).ratio()
  if full_similarity >= 0.45:
    candidates.append((0.35 + 0.35 * full_similarity, "approximate"))

  if not candidates:
    return None
  score, reason = max(candidates, key=lambda item: item[0])
  if score < 0.4:
    return None
  return TopicMatch(topic=topic, score=min(score, 1.0), reason=reason)


def topic_tokens(value: str) -> list[str]:
  return [part for part in re.split(r"[/._:\-+\s]+", value.strip().lower()) if part]


def approximate_token_score(query_tokens: list[str], candidate_tokens: list[str]) -> float:
  scores = []
  for query_token in query_tokens:
    scores.append(max(difflib.SequenceMatcher(None, query_token, candidate_token).ratio() for candidate_token in candidate_tokens))
  return sum(scores) / len(scores) if scores else 0.0
