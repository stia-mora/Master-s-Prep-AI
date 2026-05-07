"""Review helpers for the Kaoyan MVP."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .content_store import KaoyanContentStore
from .learning_store import DEFAULT_USER_ID, KaoyanLearningStore, utc_now


class KaoyanReviewService:
    def __init__(self, content_store: KaoyanContentStore, learning_store: KaoyanLearningStore) -> None:
        self.content_store = content_store
        self.learning_store = learning_store

    def seed_from_knowledge(self, knowledge_id: str, user_id: str = DEFAULT_USER_ID) -> int:
        detail = self.content_store.get_knowledge(knowledge_id, question_limit=0)
        if not detail:
            return 0
        cards = detail.get("review_cards", [])
        now = utc_now()
        next_review = (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()
        count = 0
        with self.learning_store._connect() as conn:  # Small domain helper; store owns schema.
            for card in cards[:5]:
                self.learning_store.upsert_review_item(
                    conn,
                    user_id=user_id,
                    source_type="review_card",
                    source_id=card["card_id"],
                    knowledge_id=knowledge_id,
                    title=f"{card.get('card_type') or '复习卡'}：{detail['knowledge']['knowledge_name']}",
                    prompt=card.get("front_content", ""),
                    answer=card.get("back_content", ""),
                    priority_score=3.0,
                    next_review_at=next_review,
                    now=now,
                )
                count += 1
            conn.commit()
        return count

    def list_today(self, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        return self.learning_store.list_reviews_today(user_id)

    def submit(self, review_id: str, status: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any] | None:
        return self.learning_store.submit_review(review_id, status, user_id)
