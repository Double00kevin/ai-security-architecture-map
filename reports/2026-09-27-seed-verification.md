# Seed verification report, 2026-09-27

Every tool on map v2026.09.26 was re-verified against a primary source and the evidence recorded in `registry/claims.yaml` (source URL, excerpt, sha256, date). This report is the human-readable summary; the registry is the source of truth.

Method: `python3 -m drift.snapshot --all` on 2026-09-27. Sources are limited to the vendor's own package registry entry, GitHub org releases/tags, or a vendor-owned docs/press page. No aggregators. Unauthenticated GitHub API (60 req/h) was sufficient for this run.

## Result

- 62 of 62 claims verified. 0 could not be verified.
- Per layer: 7, 4, 5, 5, 4, 6, 5, 5, 5, 6, 5, 5 (matches the map).
- Statuses: 59 active, 3 acquired (Prisma AIRS/Portkey, Check Point AI Guardrails, Voyage), 0 renamed, 0 deprecated, 0 dead.

## Changed since 2026-09-26

Status changes that would make the live map wrong: **none.** No tool on the map was renamed, acquired, deprecated, killed or found miscategorised between the map's verification date (2026-09-26) and this run (2026-09-27). The three `acquired` statuses all predate the map and are already reflected in its labels.

Watch list (not map errors, but worth knowing):

| Tool | What was found | Map impact |
|---|---|---|
| Arcade (L04) | The `arcade-ai` PyPI package is marked DEPRECATED and renamed to `arcade-mcp` (1.16.1, 2026-09-25). Product and company unchanged. | None. Tool name on the map stays "Arcade". Registry points at `arcade-mcp`. |
| LlamaParse (L05) | The `llama-parse` PyPI package is deprecated (maintained until 2026-05-01) in favour of `llama-cloud>=1.0`. Developer docs now title the product "Parse"; llamaindex.ai still markets it as LlamaParse. | None yet. Watch for a full rename; if the vendor drops the LlamaParse name, map v-next should follow. |
| LlamaFirewall (L09) | PyPI package last released 2025-05-29 (16 months). The PurpleLlama repo is not archived and was pushed 2026-08-18. | None. Keep `active`; flag as at-risk if the repo goes quiet. |
| Prisma AIRS (Portkey) (L02) | Acquisition by Palo Alto Networks closed 2026-05-29 (vendor press release). | None. Map label already reflects it. Status recorded as `acquired`. |
| Check Point AI Guardrails (L09) | Product is Lakera Guard under "Check Point AI Security" (docs.lakera.ai). | None. Status recorded as `acquired`. |
| Voyage (L06) | Voyage AI operates under MongoDB (2025 acquisition); SDK `voyageai` 0.5.0 (2026-07-10). | None. Status recorded as `acquired`. |
| Neo4j (L08) | GitHub "latest release" is a 2017 alpha and tags are unsorted. | None for the map. Checker uses a calendar-version tag pattern (newest: 2026.09.0). |

Side observation from the OpenAI models page: the HTML page names GPT-6 (Astra/Sol/Luna) as flagship while the `.md` variant of the same page still names GPT-5.6. The registry snapshots the HTML. Either way the map's "GPT" entry is correct.

## Evidence table

| id | tool | status | source | version seen | source_url |
|---|---|---|---|---|---|
| L01-claude | Claude | active | page_section | - | https://platform.claude.com/docs/en/models/overview.md |
| L01-gpt | GPT | active | page_section | - | https://developers.openai.com/api/docs/models |
| L01-gemini | Gemini | active | page_section | - | https://ai.google.dev/gemini-api/docs/models |
| L01-qwen | Qwen | active | page_section | - | https://huggingface.co/api/models?author=Qwen&sort=lastModified&direction=-1&limit=1 |
| L01-deepseek | DeepSeek | active | page_section | - | https://api-docs.deepseek.com/quick_start/pricing/ |
| L01-vllm | vLLM | active | github_release | v0.30.0 | https://github.com/vllm-project/vllm |
| L01-ollama | Ollama | active | github_release | v0.34.4 | https://github.com/ollama/ollama |
| L02-litellm | LiteLLM | active | github_release | v1.102.1 | https://github.com/BerriAI/litellm |
| L02-prisma-airs-portkey | Prisma AIRS (Portkey) | acquired | page_section | - | https://www.paloaltonetworks.com/company/press/2026/palo-alto-networks-completes-acquisition-of-portkey-to-secure-ai-agents |
| L02-openrouter | OpenRouter | active | page_section | - | https://openrouter.ai/docs/quickstart.md |
| L02-cloudflare-ai-gateway | Cloudflare AI Gateway | active | page_section | - | https://developers.cloudflare.com/ai-gateway/index.md |
| L03-langgraph | LangGraph | active | pypi | 1.2.12 | https://pypi.org/project/langgraph/ |
| L03-claude-agent-sdk | Claude Agent SDK | active | pypi | 0.2.160 | https://pypi.org/project/claude-agent-sdk/ |
| L03-openai-agents-sdk | OpenAI Agents SDK | active | pypi | 0.22.3 | https://pypi.org/project/openai-agents/ |
| L03-google-adk | Google ADK | active | pypi | 2.10.0 | https://pypi.org/project/google-adk/ |
| L03-crewai | CrewAI | active | pypi | 1.15.22 | https://pypi.org/project/crewai/ |
| L04-mcp | MCP | active | github_tag | 2026-07-28 | https://github.com/modelcontextprotocol/modelcontextprotocol |
| L04-agent-skills | Agent Skills | active | page_section | - | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview |
| L04-fastmcp | FastMCP | active | pypi | 4.0.10 | https://pypi.org/project/fastmcp/ |
| L04-composio | Composio | active | pypi | 0.24.0 | https://pypi.org/project/composio/ |
| L04-arcade | Arcade | active | pypi | 1.16.1 | https://pypi.org/project/arcade-mcp/ |
| L05-unstructured | Unstructured | active | pypi | 0.27.10 | https://pypi.org/project/unstructured/ |
| L05-docling | Docling | active | pypi | 2.130.0 | https://pypi.org/project/docling/ |
| L05-llamaparse | LlamaParse | active | pypi | 2.16.0 | https://pypi.org/project/llama-cloud/ |
| L05-firecrawl | Firecrawl | active | pypi | 4.44.0 | https://pypi.org/project/firecrawl-py/ |
| L06-voyage | Voyage | acquired | pypi | 0.5.0 | https://pypi.org/project/voyageai/ |
| L06-cohere | Cohere | active | pypi | 7.1.1 | https://pypi.org/project/cohere/ |
| L06-pgvector | pgvector | active | github_release | v0.8.6 | https://github.com/pgvector/pgvector |
| L06-pinecone | Pinecone | active | pypi | 10.0.0 | https://pypi.org/project/pinecone/ |
| L06-qdrant | Qdrant | active | github_release | v1.19.1 | https://github.com/qdrant/qdrant |
| L06-weaviate | Weaviate | active | github_release | v1.39.7 | https://github.com/weaviate/weaviate |
| L07-llamaindex | LlamaIndex | active | pypi | 0.14.25 | https://pypi.org/project/llama-index/ |
| L07-langchain | LangChain | active | pypi | 1.4.2 | https://pypi.org/project/langchain/ |
| L07-haystack | Haystack | active | pypi | 3.2.0 | https://pypi.org/project/haystack-ai/ |
| L07-graphrag | GraphRAG | active | pypi | 3.2.0 | https://pypi.org/project/graphrag/ |
| L07-cohere-rerank | Cohere Rerank | active | page_section | - | https://docs.cohere.com/docs/rerank-overview.md |
| L08-mem0 | Mem0 | active | pypi | 2.2.1 | https://pypi.org/project/mem0ai/ |
| L08-zep | Zep | active | pypi | 3.30.0 | https://pypi.org/project/zep-cloud/ |
| L08-redis | Redis | active | github_release | 8.10.2 | https://github.com/redis/redis |
| L08-neo4j | Neo4j | active | github_tag | 2026.09.0 | https://github.com/neo4j/neo4j |
| L08-weaviate-engram | Weaviate Engram | active | page_section | - | https://weaviate.io/product/engram |
| L09-nemo-guardrails | NeMo Guardrails | active | pypi | 0.24.1 | https://pypi.org/project/nemoguardrails/ |
| L09-llama-guard | Llama Guard | active | page_section | - | https://huggingface.co/api/models/meta-llama/Llama-Guard-4-12B |
| L09-llamafirewall | LlamaFirewall | active | pypi | 1.0.3 | https://pypi.org/project/llamafirewall/ |
| L09-presidio | Presidio | active | pypi | 2.2.364 | https://pypi.org/project/presidio-analyzer/ |
| L09-check-point-ai-guardrails | Check Point AI Guardrails | acquired | page_section | - | https://docs.lakera.ai/introduction.md |
| L10-promptfoo | promptfoo | active | npm | 0.123.1 | https://www.npmjs.com/package/promptfoo |
| L10-deepeval | DeepEval | active | pypi | 4.2.6 | https://pypi.org/project/deepeval/ |
| L10-braintrust | Braintrust | active | pypi | 0.42.0 | https://pypi.org/project/braintrust/ |
| L10-inspect | Inspect | active | pypi | 0.3.271 | https://pypi.org/project/inspect-ai/ |
| L10-garak | garak | active | pypi | 0.17.0 | https://pypi.org/project/garak/ |
| L10-pyrit | PyRIT | active | pypi | 1.1.0 | https://pypi.org/project/pyrit/ |
| L11-langfuse | Langfuse | active | github_release | v4.46.0 | https://github.com/langfuse/langfuse |
| L11-langsmith | LangSmith | active | pypi | 0.14.1 | https://pypi.org/project/langsmith/ |
| L11-arize-phoenix | Arize Phoenix | active | pypi | 20.16.0 | https://pypi.org/project/arize-phoenix/ |
| L11-mlflow | MLflow | active | pypi | 3.16.1 | https://pypi.org/project/mlflow/ |
| L11-opentelemetry | OpenTelemetry | active | github_release | v1.61.0 | https://github.com/open-telemetry/opentelemetry-specification |
| L12-n8n | n8n | active | npm | 2.40.7 | https://www.npmjs.com/package/n8n |
| L12-temporal | Temporal | active | github_release | v1.32.0 | https://github.com/temporalio/temporal |
| L12-airflow | Airflow | active | pypi | 3.3.2 | https://pypi.org/project/apache-airflow/ |
| L12-prefect | Prefect | active | pypi | 3.8.7 | https://pypi.org/project/prefect/ |
| L12-make | Make | active | page_section | - | https://developers.make.com/api-documentation |
