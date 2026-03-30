# CustomerService `nodes.py` Refactoring Plan

> Target file analyzed: `src/agents/customer_service/nodes.py` (2667 lines)
> 
> SPEC reference analyzed: `SPEC.md` §4.1–4.5 (Intent Sub-Agent → Hybrid Search → Reranker → GraphRAG → Reply Sub-Agent)

## 1) Problem Summary (Current State)

`nodes.py` currently mixes **all responsibilities** in one file:

- transport concerns (streaming/token callback)
- intent routing heuristics
- retrieval pipeline orchestration
- retrieval cache logic
- graph enrichment shaping
- prompt assembly
- compliance filtering
- business/FAQ/policy/review context loading
- conversation logging and async side effects

This violates the SPEC’s staged architecture and makes it hard to test/replace stages independently.

---

## 2) Logical Boundaries Mapped from Current Functions

## A. Shared/Utilities
- `_new_ai_reply_id`
- `_clean_context_text`
- `_build_vision_prompt_text`

## B. Fast-path + deterministic templates (SPEC 4.5 FAQ quick reply)
- `_parse_history_timestamp`
- `_has_recent_fast_greeting`
- `_is_non_actionable_placeholder_message`
- `_fast_path_reply`
- `_is_eta_or_logistics_question`
- `_extract_extension_order_fields`
- `_build_logistics_reply_from_extension_context`

## C. Compliance / response post-processing
- `_compliance_filter`
- `_postprocess_reply_text`

## D. Intent stage (SPEC 4.2)
- `_quick_intent_guess` (rule fallback)
- intent-related constants (`_PRODUCT_INTENTS`, `_ORDER_INTENTS`, etc.)
- (optional LLM intent path in `chat` via `ConversationTracker.classify_intent_llm`)

## E. Retrieval stage orchestration (SPEC 4.3)
- `_history_has_product_signals`
- `_should_run_product_pipeline`
- `_build_retrieval_cache_key`
- `_load_cached_retrieval`
- `_store_cached_retrieval`
- `_run_product_pipeline_with_cache`
- `_full_pipeline_search` (**already contains hybrid/vector+keyword + RRF + rerank + GraphRAG enrichment**)
- `search_products_with_embedding` (fallback)

## F. Context providers for prompt grounding
- `load_knowledge_base`
- `_search_auto_faq_context`
- `_load_policy_documents_context`
- `_load_review_sentiment_context`
- `_load_business_context`
- `_filter_relevant_knowledge`
- `_build_extension_context_str`
- `_select_context_by_intent`
- `_extract_summary`
- `_summarize_conversation`

## G. Reply stage (SPEC 4.4) + orchestration
- `chat` (currently giant orchestrator + reply generator + stream handling + action extraction)

## H. Persistence/telemetry
- `_log_conversation`
- `_log_conversation_compat`
- `_search_knowledge_base` (deprecated compat)

---

## 3) Proposed New Module Layout

Create a focused package under `src/agents/customer_service/`:

```text
customer_service/
  orchestrator.py                # new entrypoint pipeline coordinator (thin)
  intent/
    classifier.py                # Intent Sub-Agent + rule fallback
    schemas.py                   # output_intent schema/type constants
  retrieval/
    pipeline.py                  # Hybrid Search -> Reranker -> GraphRAG orchestration
    hybrid_search.py             # vector + keyword + RRF
    rerank.py                    # BGE reranker adapter
    graph_enrichment.py          # GraphRAG enrichment and normalization
    cache.py                     # retrieval cache key/load/store/inflight
  reply/
    generator.py                 # Reply Sub-Agent tool call + streaming mode
    schemas.py                   # output_reply schema
    postprocess.py               # compliance filter + truncation
  context/
    providers.py                 # faq/policy/review/profile/order/summary loaders
    budget.py                    # context budgeting by intent
    templates.py                 # deterministic FAQ/logistics direct replies
  infra/
    logging_repo.py              # conversation log persistence
    ids.py                       # ai_reply_id helpers
  nodes.py                       # compatibility shim (delegates to orchestrator.chat)
```

Notes:
- Existing modules (`order_context.py`, `customer_profile.py`, `conversation_manager.py`, `tracker.py`) stay and are used as dependencies.
- `nodes.py` should become a **facade** for backward compatibility, not business core.

---

## 4) Function-to-Module Move Plan (Concrete)

## `context/templates.py`
Move:
- `_parse_history_timestamp`
- `_has_recent_fast_greeting`
- `_is_non_actionable_placeholder_message`
- `_fast_path_reply`
- `_is_eta_or_logistics_question`
- `_extract_extension_order_fields`
- `_build_logistics_reply_from_extension_context`

Responsibility:
- deterministic, non-LLM quick replies (greeting/logistics/placeholders)
- SPEC 4.5 FAQ-template behavior

## `reply/postprocess.py`
Move:
- `_compliance_filter`
- `_postprocess_reply_text`

Responsibility:
- safety/compliance rewrite + output length cap

## `intent/classifier.py`
Move:
- `_quick_intent_guess`
- `_history_has_product_signals`
- `_should_run_product_pipeline`
- intent constants (`_PRODUCT_INTENTS`, `_ORDER_INTENTS`, `_POLICY_INTENTS`, `_PROFILE_INTENTS`, `_PROMPT_ENHANCER_INTENTS`)

Responsibility:
- unified `classify_intent(...)` interface:
  1) LLM intent (Haiku-like path) when enabled
  2) rule fallback
  3) topic override integration

## `retrieval/cache.py`
Move:
- `_build_retrieval_cache_key`
- `_load_cached_retrieval`
- `_store_cached_retrieval`
- `_run_product_pipeline_with_cache`
- `_retrieval_inflight` state

Responsibility:
- retrieval idempotence, cache hits, inflight dedup

## `retrieval/pipeline.py`
Move:
- `_full_pipeline_search`
- `search_products_with_embedding` (fallback path)

Internal split target:
- call into `hybrid_search.py` for vector+keyword+RRF
- call into `rerank.py` for BGE rerank top-5
- call into `graph_enrichment.py` for GraphRAG data attach

## `context/providers.py`
Move:
- `load_knowledge_base`
- `_search_auto_faq_context`
- `_load_policy_documents_context`
- `_load_review_sentiment_context`
- `_load_business_context`
- `_extract_summary`
- `_summarize_conversation`
- `_build_extension_context_str`
- `_build_vision_prompt_text`

Responsibility:
- all external context loading/compression; no reply generation

## `context/budget.py`
Move:
- `_select_context_by_intent`
- `_filter_relevant_knowledge`

Responsibility:
- decide what context sections can be injected for each intent

## `infra/logging_repo.py`
Move:
- `_log_conversation`
- `_log_conversation_compat`
- `_conversation_log_supports_ai_reply_id`

Responsibility:
- persistence for conversation logs only

## `infra/ids.py`
Move:
- `_new_ai_reply_id`

Responsibility:
- reply id generation

## `orchestrator.py`
Move/Refactor:
- `chat` (big split into small private methods)

Target methods inside orchestrator:
- `_prepare_tasks(...)`
- `_await_critical_and_optional(...)`
- `_resolve_intent_and_topic(...)`
- `_build_prompt_payload(...)`
- `_generate_reply(...)`
- `_collect_side_effects(...)`
- `_build_response(...)`

`nodes.py` keeps public `chat(...)` and delegates to `orchestrator.chat(...)`.

---

## 5) New Pipeline Flow (Entry → Stages)

## Entry point
`nodes.chat(...)` (compat facade) → `orchestrator.chat(...)`

## Stage 0: Fast deterministic handling
- placeholder message skip
- greeting/thanks/ack direct reply
- logistics direct template if extension order context is present

## Stage 1: Intent Sub-Agent (SPEC 4.2)
- `intent.classifier.classify_intent()`
- returns `{intent, confidence, sentiment, requires_human, entities}`
- fallback to rule-based intent on LLM failure/timeout

## Stage 2: Hybrid Search (SPEC 4.3)
- if intent requires product retrieval:
  - `retrieval.cache` cache key + inflight dedup
  - `retrieval.hybrid_search`: vector + keyword recall
  - RRF merge

## Stage 3: Reranker (SPEC 4.3)
- `retrieval.rerank` BGE rerank to top-5
- fallback: top-N from merged recall

## Stage 4: GraphRAG enrichment (SPEC 4.3)
- `retrieval.graph_enrichment` fetch product subgraph/deep context
- normalize structure for prompt consumption

## Stage 5: Reply Sub-Agent (SPEC 4.4)
- `reply.generator.generate(...)` (stream or tool mode)
- emit `output_reply` structured fields
- apply `reply.postprocess`

## Stage 6: Side effects (async, non-blocking)
- conversation logging
- evaluation/auto-evolve hooks
- action tracking

---

## 6) Interface Changes Needed

## A. Internal typed contracts (recommended)
Introduce dataclasses / TypedDicts:
- `IntentResult`
- `RetrievalCandidate`
- `EnrichedProduct`
- `ReplyDecision`
- `ContextBundle`

This removes widespread ad-hoc `dict[str, Any]` and key-miss fragility.

## B. Retrieval pipeline interface
Current: `_full_pipeline_search(message, pool) -> list[dict]`

Proposed:
```python
async def run_retrieval_pipeline(
    query: str,
    *,
    intent: str,
    entities: dict[str, Any] | None,
    timeout_s: float,
    redis_client,
) -> list[EnrichedProduct]
```

## C. Reply generator interface
Current reply generation is embedded in `chat`.

Proposed:
```python
async def generate_reply(
    *,
    system_prompt: str,
    messages: list[dict[str, str]],
    intent: IntentResult,
    stream: bool,
    token_callback,
    images: list[str] | None,
) -> ReplyDecision
```

## D. Keep external API stable
Keep `chat(...) -> dict` return shape unchanged initially:
- `session_id, reply, ai_reply_id, intent, sources, needs_human, action, product_cards, context_trace`

So callers are unaffected during migration.

---

## 7) Migration Strategy (Low-Risk Sequence)

1. **Phase 1 (no behavior change):** extract pure helper functions into new modules, keep `nodes.py` imports.
2. **Phase 2:** extract retrieval cache + retrieval pipeline wrapper, keep same outputs.
3. **Phase 3:** extract reply generator (stream/tool), keep tool schema and postprocess identical.
4. **Phase 4:** introduce `orchestrator.py`, make `nodes.chat` delegate.
5. **Phase 5:** remove dead compat/internal duplication after integration tests pass.

Each phase should pass regression checks before moving to next.

---

## 8) Risk Assessment

## High risk
1. **Behavior drift in intent routing**
   - Topic override + quick intent + optional LLM intent currently intertwined.
   - Split may change edge classifications (`other` vs `product_inquiry`).

2. **Streaming output parity**
   - Current stream mode has compliance holdback and structured decision fallback.
   - Easy to break token emission timing or final text consistency.

3. **Async timeout choreography**
   - Critical/optional task waits are tuned with env vars.
   - Refactor could accidentally increase tail latency or cancel useful tasks too early.

## Medium risk
4. **Cache semantics changes**
   - Inflight dedup + TTL cache currently coupled; race conditions possible after extraction.

5. **Context injection order**
   - Prompt quality depends on ordering of summary/history/faq/policy/reviews/topic context.

6. **GraphRAG field shape compatibility**
   - Downstream prompt builders expect current key names (`related_products`, `suitable_for`, etc.).

## Low risk
7. **Logging path migration**
   - Mostly side-effecting; low functional impact if API kept.

## Mitigations
- Snapshot tests for `chat()` output given fixed fixtures.
- Golden tests for stream mode (emitted chunks + final reply equality).
- Contract tests for retrieval output schema.
- Latency benchmark before/after (p50/p95).
- Feature flag to switch between old/new orchestrator during rollout.

---

## 9) Acceptance Criteria for Refactor Completion

- `nodes.py` reduced to thin facade + backward-compat exports.
- Pipeline stages map 1:1 to SPEC 4.1–4.5 modules.
- Unit tests per stage (intent/retrieval/rerank/graph/reply).
- No API break for existing callers of `chat(...)`.
- p95 latency not worse than baseline by >10%.
- Streaming and non-streaming responses remain behaviorally consistent.

---

## 10) Quick Mapping to SPEC 4.1–4.5

- **4.1 增强检索架构** → `orchestrator.py` + `retrieval/*`
- **4.2 Intent Sub-Agent** → `intent/classifier.py`
- **4.3 Hybrid Search + Reranker + GraphRAG** → `retrieval/hybrid_search.py`, `retrieval/rerank.py`, `retrieval/graph_enrichment.py`
- **4.4 Reply Sub-Agent** → `reply/generator.py` + `reply/schemas.py`
- **4.5 FAQ快捷回复模板** → `context/templates.py`

This gives clear stage ownership and removes the current “God function/file” bottleneck while preserving runtime compatibility during migration.