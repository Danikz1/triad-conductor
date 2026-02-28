# Triad Forge: Pre-Development Specification Orchestrator

## 1. Executive Summary
**Triad Forge** is a specialized pre-development tool designed to refine raw, unstructured project ideas into high-quality, actionable technical specifications. By triangulating insights from three distinct LLM personas and synthesizing them via an Arbiter, it ensures that project plans are technically feasible, user-centric, and risk-aware before they are handed off to **Triad Conductor** for implementation.

## 2. Core Workflow: The "Pre-Phase" Loop

`INTAKE -> TRIANGULATE -> SYNTHESIZE -> REVIEW -> HANDOFF`

### Stage 1: INTAKE
- **Source:** Raw text, voice-to-text, or brief `.md` files.
- **Action:** Extract core intent and constraints from the user's unstructured input.

### Stage 2: TRIANGULATE (The Three Lenses)
The idea is processed in parallel by three specialized agents:
1.  **The Product Visionary:** Focuses on user experience, feature prioritization, and market value.
2.  **The Systems Architect:** Focuses on technical stack suitability, data models, and API design.
3.  **The Security Critic:** Focuses on edge cases, potential failure points, security risks, and scalability.

### Stage 3: SYNTHESIZE (The Arbiter)
- **Action:** A lead LLM analyzes the three proposals, resolves contradictions, and merges the best elements into a single **Draft Specification**.
- **Output:** A structured JSON/Markdown document including:
    - Feature Scope (In vs. Out)
    - Technical Architecture
    - Proposed Milestones
    - Data Schema drafts

### Stage 4: REVIEW (Human-in-the-Loop)
- **Action:** The user reviews the Draft Specification via CLI or Telegram.
- **Interaction:**
    - **Approve:** Locks the design and proceeds to handoff.
    - **Push Back:** Provides feedback (e.g., "Change the DB to PostgreSQL") which triggers a re-synthesis (V2).

### Stage 5: HANDOFF
- **Action:** Generates a finalized `project.md` or `task.md`.
- **Integration:** Automatically triggers the **Triad Conductor** entry point:
  ```bash
  ./triad-start final_specification.md
  ```

## 3. Technical Integration
- **Persona Injection:** Uses specialized system prompts to force diversity in the `TRIANGULATE` phase.
- **Shared Infrastructure:** Reuses Triad Conductor's `invoker.py`, `cost_tracker.py`, and `telegram/` handlers.
- **State Management:** Tracks iteration history to allow users to revert to previous versions of the specification.

## 4. Value Add
- **Mitigates Hallucinations:** Prevents autonomous builders from guessing missing requirements.
- **Reduces Development Cost:** Identifies technical roadblocks *before* code is written.
- **Improves Developer Experience:** Provides a clear, approved roadmap for the autonomous build phase.
