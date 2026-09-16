"""Print only provider status — never print secrets."""

from moodos.config import settings
from moodos.llm import router
from moodos.memory import mem0

print("groq_configured", bool(settings.groq_api_key))
print("gemini_configured", bool(settings.gemini_api_key))
print("mem0_configured", bool(settings.mem0_api_key))
print("groq_client", router.groq_ready)
print("gemini_client", router.gemini_ready)
print("mem0_cloud", mem0.cloud_ready)

ext = router.extract_json(
    'Extract JSON with keys current_mood, budget_inr from: "I am exhausted, budget 1000 rupees."'
)
print("extract_agent", ext.get("_agent"), "mood", ext.get("current_mood"), "keys", sorted(k for k in ext if not k.startswith("_"))[:8])

plan = router.plan_json(
    'Return JSON {"steps":[{"order":1,"title":"quiet cafe"}],"explanation":"ok"}'
)
print("plan_agent", plan.get("_agent") or plan.get("_model"), "has_steps", bool(plan.get("steps")))
