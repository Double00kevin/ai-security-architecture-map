# The AI Architecture Map — Build it. Secure it.

Version **v2026.09.29** (generated 2026-09-29, re-check due 2026-10-28). 69 tools across 12 layers, one security control per layer. Every tool has a receipt in `registry/claims.yaml`, read by a person (oldest human review 2026-09-28) and re-checked since; the oldest check behind this version is from 2026-09-28.

![The AI Architecture Map v2026.09.29](maps/v2026.09.29/map.png)

12 layers every AI build runs on, the tools for each, and the security control none of them should ship without.

## 01 · Models & Hosting

**Security control:** Zero-retention terms, pinned versions with a named owner, no public inference ports

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| Claude | active | Anthropic | [L01-claude](https://platform.claude.com/docs/en/models/overview.md) | 2026-09-28 (review) | 2026-09-28 |
| GPT | active |  | [L01-gpt](https://developers.openai.com/api/docs/models) | 2026-09-28 (review) | 2026-09-28 |
| Gemini | active |  | [L01-gemini](https://raw.githubusercontent.com/googleapis/python-genai/main/README.md) | 2026-09-28 (review) | 2026-09-28 |
| Llama | active | Meta | [L01-llama](https://raw.githubusercontent.com/meta-llama/llama-models/main/README.md) | 2026-09-28 (review) | 2026-09-28 |
| Mistral | active |  | [L01-mistral](https://pypi.org/project/mistralai/) | 2026-09-28 (review) | 2026-09-28 |
| Qwen | active |  | [L01-qwen](https://huggingface.co/api/models?author=Qwen&sort=lastModified&direction=-1&limit=1) | 2026-09-28 (review) | 2026-09-28 |
| DeepSeek | active |  | [L01-deepseek](https://api-docs.deepseek.com/quick_start/pricing/) | 2026-09-28 (review) | 2026-09-28 |
| Bedrock | active |  | [L01-bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html) | 2026-09-28 (review) | 2026-09-28 |
| vLLM | active |  | [L01-vllm](https://github.com/vllm-project/vllm) | 2026-09-28 (review) | 2026-09-28 |
| Ollama | active |  | [L01-ollama](https://github.com/ollama/ollama) | 2026-09-28 (review) | 2026-09-28 |

## 02 · AI Gateway

**Security control:** Central auth, rate limits, spend caps, PII redaction

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| LiteLLM | active |  | [L02-litellm](https://github.com/BerriAI/litellm) | 2026-09-28 (review) | 2026-09-28 |
| Prisma AIRS (Portkey) | active | Palo Alto Networks (acquired by Palo Alto Networks (2026-05-29)) | [L02-prisma-airs-portkey](https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents) | 2026-09-28 (review) | 2026-09-28 |
| OpenRouter | active |  | [L02-openrouter](https://openrouter.ai/docs/quickstart.md) | 2026-09-28 (review) | 2026-09-28 |
| Cloudflare AI Gateway | active |  | [L02-cloudflare-ai-gateway](https://developers.cloudflare.com/ai-gateway/index.md) | 2026-09-28 (review) | 2026-09-28 |
| Kong | active |  | [L02-kong](https://github.com/Kong/kong) | 2026-09-28 (review) | 2026-09-28 |

## 03 · Orchestration & Agents

**Security control:** Step/budget limits, human approval for irreversible actions

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| LangGraph | active |  | [L03-langgraph](https://pypi.org/project/langgraph/) | 2026-09-28 (review) | 2026-09-28 |
| Claude Agent SDK | active |  | [L03-claude-agent-sdk](https://pypi.org/project/claude-agent-sdk/) | 2026-09-28 (review) | 2026-09-28 |
| OpenAI Agents SDK | active |  | [L03-openai-agents-sdk](https://pypi.org/project/openai-agents/) | 2026-09-28 (review) | 2026-09-28 |
| Google ADK | active |  | [L03-google-adk](https://pypi.org/project/google-adk/) | 2026-09-28 (review) | 2026-09-28 |
| CrewAI | active |  | [L03-crewai](https://pypi.org/project/crewai/) | 2026-09-28 (review) | 2026-09-28 |
| Microsoft Agent Framework | active |  | [L03-microsoft-agent-framework](https://pypi.org/project/agent-framework/) | 2026-09-28 (review) | 2026-09-28 |

## 04 · Tools & MCP

**Security control:** Least-privilege scopes, allowlists, vetted servers + skills

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| MCP | active |  | [L04-mcp](https://github.com/modelcontextprotocol/modelcontextprotocol) | 2026-09-28 (review) | 2026-09-28 |
| Agent Skills | active |  | [L04-agent-skills](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) | 2026-09-28 (review) | 2026-09-28 |
| FastMCP | active |  | [L04-fastmcp](https://pypi.org/project/fastmcp/) | 2026-09-28 (review) | 2026-09-28 |
| Composio | active |  | [L04-composio](https://pypi.org/project/composio/) | 2026-09-28 (review) | 2026-09-28 |
| Arcade | active |  | [L04-arcade](https://pypi.org/project/arcade-mcp/) | 2026-09-28 (review) | 2026-09-28 |

## 05 · Ingestion

**Security control:** Sanitize inputs, tag source + trust level on every chunk

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| Unstructured | active |  | [L05-unstructured](https://pypi.org/project/unstructured/) | 2026-09-28 (review) | 2026-09-28 |
| Docling | active |  | [L05-docling](https://pypi.org/project/docling/) | 2026-09-28 (review) | 2026-09-28 |
| LlamaParse | active |  | [L05-llamaparse](https://pypi.org/project/llama-cloud/) | 2026-09-28 (review) | 2026-09-28 |
| Firecrawl | active |  | [L05-firecrawl](https://pypi.org/project/firecrawl-py/) | 2026-09-28 (review) | 2026-09-28 |
| Airbyte | active |  | [L05-airbyte](https://github.com/airbytehq/airbyte) | 2026-09-28 (review) | 2026-09-28 |

## 06 · Embeddings & Vector DB

**Security control:** Classify vectors like source data, ACL filters at query time

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| Voyage | active | MongoDB (acquired by MongoDB (2025-02-24)) | [L06-voyage](https://pypi.org/project/voyageai/) | 2026-09-28 (review) | 2026-09-28 |
| Cohere | active |  | [L06-cohere](https://pypi.org/project/cohere/) | 2026-09-28 (review) | 2026-09-28 |
| BGE | active |  | [L06-bge](https://github.com/FlagOpen/FlagEmbedding) | 2026-09-28 (review) | 2026-09-28 |
| pgvector | active |  | [L06-pgvector](https://github.com/pgvector/pgvector) | 2026-09-28 (review) | 2026-09-28 |
| Pinecone | active |  | [L06-pinecone](https://pypi.org/project/pinecone/) | 2026-09-28 (review) | 2026-09-28 |
| Qdrant | active |  | [L06-qdrant](https://github.com/qdrant/qdrant) | 2026-09-28 (review) | 2026-09-28 |
| Weaviate | active |  | [L06-weaviate](https://github.com/weaviate/weaviate) | 2026-09-28 (review) | 2026-09-28 |

## 07 · Retrieval (RAG)

**Security control:** Retrieved text = untrusted input, never instructions

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| LlamaIndex | active |  | [L07-llamaindex](https://pypi.org/project/llama-index/) | 2026-09-28 (review) | 2026-09-28 |
| LangChain | active |  | [L07-langchain](https://pypi.org/project/langchain/) | 2026-09-28 (review) | 2026-09-28 |
| Haystack | active |  | [L07-haystack](https://pypi.org/project/haystack-ai/) | 2026-09-28 (review) | 2026-09-28 |
| GraphRAG | active |  | [L07-graphrag](https://pypi.org/project/graphrag/) | 2026-09-28 (review) | 2026-09-28 |
| Cohere Rerank | active |  | [L07-cohere-rerank](https://docs.cohere.com/docs/rerank-overview.md) | 2026-09-28 (review) | 2026-09-28 |

## 08 · Memory

**Security control:** Validate writes, TTLs, user-visible + deletable memory

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| Mem0 | active |  | [L08-mem0](https://pypi.org/project/mem0ai/) | 2026-09-28 (review) | 2026-09-28 |
| Zep | active |  | [L08-zep](https://pypi.org/project/zep-cloud/) | 2026-09-28 (review) | 2026-09-28 |
| Redis | active |  | [L08-redis](https://github.com/redis/redis) | 2026-09-28 (review) | 2026-09-28 |
| Neo4j | active |  | [L08-neo4j](https://github.com/neo4j/neo4j) | 2026-09-28 (review) | 2026-09-28 |
| Weaviate Engram | active |  | [L08-weaviate-engram](https://weaviate.io/product/engram) | 2026-09-28 (review) | 2026-09-28 |

## 09 · Guardrails

**Security control:** Defense in depth. Assume filters get bypassed

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| NeMo Guardrails | active |  | [L09-nemo-guardrails](https://pypi.org/project/nemoguardrails/) | 2026-09-28 (review) | 2026-09-28 |
| Llama Guard | active |  | [L09-llama-guard](https://raw.githubusercontent.com/meta-llama/PurpleLlama/main/Llama-Guard4/12B/MODEL_CARD.md) | 2026-09-28 (review) | 2026-09-28 |
| LlamaFirewall | active |  | [L09-llamafirewall](https://pypi.org/project/llamafirewall/) | 2026-09-28 (review) | 2026-09-28 |
| Presidio | active |  | [L09-presidio](https://pypi.org/project/presidio-analyzer/) | 2026-09-28 (review) | 2026-09-28 |
| Check Point AI Guardrails | active | Check Point | [L09-check-point-ai-guardrails](https://docs.lakera.ai/docs/api.md) | 2026-09-28 (review) | 2026-09-28 |

## 10 · Evals & Red Team

**Security control:** Adversarial evals gate every deploy

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| promptfoo | active | agreed to be acquired by OpenAI (2026-03-09) | [L10-promptfoo](https://www.npmjs.com/package/promptfoo) | 2026-09-28 (review) | 2026-09-28 |
| DeepEval | active |  | [L10-deepeval](https://pypi.org/project/deepeval/) | 2026-09-28 (review) | 2026-09-28 |
| Braintrust | active |  | [L10-braintrust](https://pypi.org/project/braintrust/) | 2026-09-28 (review) | 2026-09-28 |
| Inspect | active |  | [L10-inspect](https://pypi.org/project/inspect-ai/) | 2026-09-28 (review) | 2026-09-28 |
| garak | active |  | [L10-garak](https://pypi.org/project/garak/) | 2026-09-28 (review) | 2026-09-28 |
| PyRIT | active |  | [L10-pyrit](https://pypi.org/project/pyrit/) | 2026-09-28 (review) | 2026-09-28 |

## 11 · Observability

**Security control:** Audit every tool call; redact + restrict the logs

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| Langfuse | active | ClickHouse (acquired by ClickHouse (2026-01-16)) | [L11-langfuse](https://github.com/langfuse/langfuse) | 2026-09-28 (review) | 2026-09-28 |
| LangSmith | active |  | [L11-langsmith](https://pypi.org/project/langsmith/) | 2026-09-28 (review) | 2026-09-28 |
| Arize Phoenix | active |  | [L11-arize-phoenix](https://pypi.org/project/arize-phoenix/) | 2026-09-28 (review) | 2026-09-28 |
| MLflow | active |  | [L11-mlflow](https://pypi.org/project/mlflow/) | 2026-09-28 (review) | 2026-09-28 |
| OpenTelemetry | active |  | [L11-opentelemetry](https://github.com/open-telemetry/opentelemetry-specification) | 2026-09-28 (review) | 2026-09-28 |

## 12 · Automation

**Security control:** Vaulted secrets, signed webhooks, named owners

| Tool | Status | Owner | Receipt | Last check | Human review |
|---|---|---|---|---|---|
| n8n | active |  | [L12-n8n](https://www.npmjs.com/package/n8n) | 2026-09-28 (review) | 2026-09-28 |
| Temporal | active |  | [L12-temporal](https://github.com/temporalio/temporal) | 2026-09-28 (review) | 2026-09-28 |
| Airflow | active |  | [L12-airflow](https://pypi.org/project/apache-airflow/) | 2026-09-28 (review) | 2026-09-28 |
| Prefect | active |  | [L12-prefect](https://pypi.org/project/prefect/) | 2026-09-28 (review) | 2026-09-28 |
| Make | active |  | [L12-make](https://developers.make.com/api-documentation) | 2026-09-28 (review) | 2026-09-28 |

## Govern It All

The frameworks the controls draw on.

- [OWASP Top 10 for LLM Applications (2026)](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/)
- [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-genai-security-project-releases-top-10-risks-and-mitigations-for-agentic-ai-security/)
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- [ISO/IEC 42001](https://www.iso.org/standard/42001)
- [MITRE ATLAS](https://atlas.mitre.org/)

## How to read a receipt

Each row links to the primary source the claim rests on. `registry/claims.yaml` also holds the short excerpt that was read, its SHA-256, the version seen, the date it was fetched, which assertions it supports, and the review record of the person who read it. Every Saturday `python -m drift check` re-fetches every source. Routine changes (a new version number or date, nothing else) are re-checked automatically and the claim keeps its person's review for up to 180 days; anything else (a changed page, a lifecycle or ownership signal, a source that can't be reached) waits for a person. "Last check" says which kind of check it was.
