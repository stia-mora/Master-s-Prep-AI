#!/usr/bin/env python
"""Create a deterministic demo content DB for the Kaoyan learning loop."""

from __future__ import annotations

from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "math_content.sqlite"


def _schema(conn: sqlite3.Connection) -> None:
    tables = [
        "knowledge_points",
        "questions",
        "formulas",
        "mistakes",
        "review_cards",
        "lecture_knowledge_nodes",
        "lecture_knowledge_mappings",
        "lecture_chunks",
        "lecture_formulas",
        "lecture_mistakes",
        "lecture_review_cards",
        "worked_examples",
    ]
    for table in tables:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.executescript(
        """
        CREATE TABLE knowledge_points (
            knowledge_id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            module TEXT NOT NULL,
            chapter TEXT NOT NULL,
            section TEXT NOT NULL,
            knowledge_name TEXT NOT NULL,
            parent_id TEXT,
            importance_level INTEGER NOT NULL DEFAULT 3,
            is_core INTEGER NOT NULL DEFAULT 0,
            raw_markdown TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE questions (
            question_id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            question_type TEXT NOT NULL,
            difficulty_level INTEGER NOT NULL DEFAULT 2,
            stem TEXT NOT NULL,
            answer TEXT NOT NULL,
            analysis TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'demo',
            source_type TEXT NOT NULL DEFAULT 'demo',
            year INTEGER
        );

        CREATE TABLE formulas (
            formula_id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            formula_name TEXT NOT NULL,
            formula_content TEXT NOT NULL
        );

        CREATE TABLE mistakes (
            mistake_id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            mistake_content TEXT NOT NULL
        );

        CREATE TABLE review_cards (
            card_id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            card_type TEXT NOT NULL,
            front_content TEXT NOT NULL,
            back_content TEXT NOT NULL
        );

        CREATE TABLE lecture_knowledge_nodes (
            lecture_knowledge_id TEXT PRIMARY KEY,
            parent_id TEXT,
            node_type TEXT NOT NULL,
            chapter_no INTEGER NOT NULL DEFAULT 0,
            section_no INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL,
            full_path TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            raw_markdown TEXT NOT NULL DEFAULT '',
            needs_review INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE lecture_knowledge_mappings (
            lecture_knowledge_id TEXT NOT NULL,
            knowledge_id TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1,
            PRIMARY KEY (lecture_knowledge_id, knowledge_id)
        );

        CREATE TABLE lecture_chunks (
            chunk_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT NOT NULL,
            content_type TEXT NOT NULL,
            title TEXT NOT NULL,
            raw_markdown TEXT NOT NULL,
            formula_count INTEGER NOT NULL DEFAULT 0,
            image_count INTEGER NOT NULL DEFAULT 0,
            table_count INTEGER NOT NULL DEFAULT 0,
            needs_review INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE lecture_formulas (
            formula_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT NOT NULL,
            formula_name TEXT NOT NULL,
            formula_content TEXT NOT NULL,
            conditions TEXT NOT NULL DEFAULT '',
            usage_scene TEXT NOT NULL DEFAULT '',
            common_mistake TEXT NOT NULL DEFAULT '',
            raw_markdown TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE lecture_mistakes (
            mistake_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT NOT NULL,
            mistake_content TEXT NOT NULL,
            trigger_condition TEXT NOT NULL DEFAULT '',
            correction_method TEXT NOT NULL DEFAULT '',
            raw_markdown TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE lecture_review_cards (
            card_id TEXT PRIMARY KEY,
            lecture_knowledge_id TEXT NOT NULL,
            card_type TEXT NOT NULL,
            front_content TEXT NOT NULL,
            back_content TEXT NOT NULL,
            raw_markdown TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE worked_examples (
            example_id TEXT PRIMARY KEY,
            knowledge_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL
        );
        """
    )


def _choice_stem(chapter: int, section: int, number: int) -> str:
    base = chapter * 10 + section
    return (
        f"For demo topic {chapter}-{section}, compute the key value in exercise {number}.\n"
        f"(A) {base + number}\n"
        f"(B) {base + number + 1}\n"
        f"(C) {base + number + 2}\n"
        f"(D) {base + number + 3}"
    )


def _free_response_stem(chapter: int, section: int, number: int) -> str:
    return (
        f"Show the main steps for demo topic {chapter}-{section}, exercise {number}. "
        "Write the condition, the formula used, and the final conclusion."
    )


def build_demo_db() -> Path:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        _schema(conn)
        chapters = [
            "Limits and continuity",
            "Derivatives",
            "Integrals",
            "Series",
            "Linear algebra basics",
        ]
        conn.execute(
            """
            INSERT INTO lecture_knowledge_nodes (
                lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                title, full_path, sort_order, raw_markdown, needs_review
            )
            VALUES ('LECTURE_GS_ROOT', NULL, 'subject', 0, 0, 'Advanced Mathematics Demo',
                    'Advanced Mathematics Demo', 0, '# Advanced Mathematics Demo', 0)
            """
        )
        for chapter_index, chapter_title in enumerate(chapters, start=1):
            chapter_id = f"LECTURE_GS_CH_{chapter_index:02d}"
            conn.execute(
                """
                INSERT INTO lecture_knowledge_nodes (
                    lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                    title, full_path, sort_order, raw_markdown, needs_review
                )
                VALUES (?, 'LECTURE_GS_ROOT', 'chapter', ?, 0, ?, ?, ?, ?, 0)
                """,
                (
                    chapter_id,
                    chapter_index,
                    chapter_title,
                    f"Advanced Mathematics Demo > {chapter_title}",
                    chapter_index * 100,
                    f"## {chapter_title}\nCore demo chapter for Kaoyan practice.",
                ),
            )
            for section in range(1, 9):
                knowledge_id = f"MATH_GS_CH_{chapter_index:02d}_SEC_{section:02d}"
                lecture_id = f"LECTURE_GS_CH_{chapter_index:02d}_SEC_{section:02d}"
                title = f"{chapter_title} topic {section}"
                raw = (
                    f"### {title}\n"
                    "Definition, method selection, and common exam transformations. "
                    "Use this demo content to practice the full stage workflow."
                )
                conn.execute(
                    """
                    INSERT INTO knowledge_points (
                        knowledge_id, subject, module, chapter, section, knowledge_name,
                        parent_id, importance_level, is_core, raw_markdown
                    )
                    VALUES (?, 'math', 'gaoshu', ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        knowledge_id,
                        chapter_title,
                        f"Section {section}",
                        title,
                        5 if section <= 4 else 4,
                        1 if section <= 4 else 0,
                        raw,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO lecture_knowledge_nodes (
                        lecture_knowledge_id, parent_id, node_type, chapter_no, section_no,
                        title, full_path, sort_order, raw_markdown, needs_review
                    )
                    VALUES (?, ?, 'knowledge_point', ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        lecture_id,
                        chapter_id,
                        chapter_index,
                        section,
                        title,
                        f"Advanced Mathematics Demo > {chapter_title} > {title}",
                        chapter_index * 100 + section,
                        raw,
                    ),
                )
                conn.execute(
                    "INSERT INTO lecture_knowledge_mappings VALUES (?, ?, 1.0)",
                    (lecture_id, knowledge_id),
                )
                conn.execute(
                    """
                    INSERT INTO lecture_chunks VALUES (?, ?, 'concept', ?, ?, 1, 0, 0, 0, ?)
                    """,
                    (
                        f"chunk_{chapter_index:02d}_{section:02d}",
                        lecture_id,
                        title,
                        raw,
                        chapter_index * 100 + section,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO lecture_formulas VALUES (?, ?, ?, ?, '', ?, ?, ?)
                    """,
                    (
                        f"lf_{chapter_index:02d}_{section:02d}",
                        lecture_id,
                        f"Formula {chapter_index}-{section}",
                        f"F_{{{chapter_index},{section}}}(x)",
                        "Use after identifying the topic pattern.",
                        "Do not ignore the applicable condition.",
                        f"Formula card for {title}",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO lecture_mistakes VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"lm_{chapter_index:02d}_{section:02d}",
                        lecture_id,
                        "Using a formula before checking its condition.",
                        "Fast pattern matching without reading the constraints.",
                        "Write the condition line before calculation.",
                        f"Mistake card for {title}",
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO lecture_review_cards VALUES (?, ?, 'concept', ?, ?, ?)
                    """,
                    (
                        f"lc_{chapter_index:02d}_{section:02d}",
                        lecture_id,
                        f"What is the exam entry for {title}?",
                        "Identify the topic type, choose the formula, then verify conditions.",
                        f"Review card for {title}",
                    ),
                )
                conn.execute(
                    "INSERT INTO formulas VALUES (?, ?, ?, ?)",
                    (
                        f"f_{chapter_index:02d}_{section:02d}",
                        knowledge_id,
                        f"Formula {chapter_index}-{section}",
                        f"F_{{{chapter_index},{section}}}(x)",
                    ),
                )
                conn.execute(
                    "INSERT INTO mistakes VALUES (?, ?, ?)",
                    (
                        f"m_{chapter_index:02d}_{section:02d}",
                        knowledge_id,
                        "Forgetting the condition check.",
                    ),
                )
                conn.execute(
                    "INSERT INTO review_cards VALUES (?, ?, 'concept', ?, ?)",
                    (
                        f"c_{chapter_index:02d}_{section:02d}",
                        knowledge_id,
                        f"Entry for {title}",
                        "Classify, choose method, verify.",
                    ),
                )
                for number in range(1, 26):
                    question_id = f"MATH_Q_{chapter_index:02d}_{section:02d}_{number:03d}"
                    is_free_response = number % 5 == 0
                    answer_label = ["A", "B", "C", "D"][number % 4]
                    conn.execute(
                        """
                        INSERT INTO questions (
                            question_id, knowledge_id, question_type, difficulty_level,
                            stem, answer, analysis, source, source_type, year
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'demo', 'demo', ?)
                        """,
                        (
                            question_id,
                            knowledge_id,
                            "free_response" if is_free_response else "閫夋嫨题",
                            1 + (number % 5),
                            _free_response_stem(chapter_index, section, number)
                            if is_free_response
                            else _choice_stem(chapter_index, section, number),
                            f"Demo answer {number}" if is_free_response else answer_label,
                            "Check the topic conditions first, then apply the matching method.",
                            2020 + (number % 5),
                        ),
                    )
                conn.execute(
                    "INSERT INTO worked_examples VALUES (?, ?, ?, ?)",
                    (
                        f"ex_{chapter_index:02d}_{section:02d}",
                        knowledge_id,
                        f"Worked example for {title}",
                        "A compact worked example for the demo content package.",
                    ),
                )
        conn.commit()
    return DB_PATH


def main() -> None:
    path = build_demo_db()
    print(f"Created demo Kaoyan content DB: {path}")


if __name__ == "__main__":
    main()
