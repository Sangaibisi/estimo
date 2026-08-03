<!-- prompt: decompose v1 -->
You refine ONE work item drafted from a Turkish telco BRD requirement. The deterministic
pipeline already attributed candidate modules; you improve the item TITLE (concise,
noun-phrase, Turkish, "iş kalemi" style) and may ADD missing modules from the allowed
taxonomy — never remove existing ones. Reply with ONLY a JSON object:
{"title": "<Turkish work-item title>", "extra_modules": ["<module>", ...]}

Allowed modules: billing-core, crm-suite, product-catalog, campaign-engine,
dealer-portal, integration-hub, payment-adapter, invoice-render, selfcare-web.

Examples:
- Requirement: "Taksit tutarı, abonenin aylık faturasına ayrı kalem olarak yansıtılmalıdır." · modules: [billing-core]
  → {"title": "Faturada ayrı taksit kalemi gösterimi", "extra_modules": ["invoice-render"]}
- Requirement: "Bayi, satış anında abonenin taksitlendirmeye uygunluğunu sorgulayabilmelidir." · modules: [dealer-portal]
  → {"title": "Bayi kanalında taksitlendirme uygunluk sorgusu", "extra_modules": ["integration-hub"]}

Never invent scope that is not in the requirement. The requirement and current draft:
