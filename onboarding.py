"""SignalSeek onboarding — keyword suggestions based on product category."""

# Keyword suggestion templates by product category
# These are shown to new users to help them pick effective keywords

KEYWORD_SUGGESTIONS = {
    "Developer Tool": [
        "code review tool",
        "CI/CD pipeline",
        "API testing",
        "developer productivity",
        "monitoring tool",
        "debugging tool",
        "code generation",
        "documentation generator",
    ],
    "Productivity / Project Management": [
        "project management tool",
        "task manager",
        "team collaboration",
        "time tracking",
        "kanban board",
        "workflow automation",
        "note taking app",
        "calendar tool",
    ],
    "Marketing / Sales": [
        "email marketing",
        "CRM tool",
        "lead generation",
        "social media scheduler",
        "SEO tool",
        "cold outreach",
        "marketing automation",
        "sales pipeline",
    ],
    "Design": [
        "design tool",
        "UI kit",
        "prototyping tool",
        "wireframe tool",
        "icon set",
        "illustration tool",
        "design system",
        "mockup generator",
    ],
    "Analytics / Data": [
        "analytics tool",
        "dashboard builder",
        "data visualization",
        "business intelligence",
        "reporting tool",
        "data pipeline",
        "ETL tool",
        "metrics tracker",
    ],
    "Finance / Payments": [
        "invoicing tool",
        "expense tracker",
        "payment processing",
        "subscription management",
        "accounting software",
        "budgeting app",
        "tax tool",
        "billing platform",
    ],
    "AI / Machine Learning": [
        "AI writing tool",
        "chatbot builder",
        "image generation",
        "AI voice agent",
        "ML model deployment",
        "prompt engineering tool",
        "AI data labeling",
        "vector database",
    ],
    "Customer Support": [
        "help desk tool",
        "live chat",
        "ticketing system",
        "knowledge base",
        "customer feedback",
        "support automation",
        "FAQ builder",
        "community platform",
    ],
}

HELP_TIPS = [
    "💡 Use competitor names as keywords to catch people looking for alternatives",
    "💡 Add 'vs' comparisons: 'clickup vs asana' to find people comparing tools",
    "💡 Monitor 'who is hiring' threads for potential B2B leads",
    "💡 Set up subreddit filters to focus on niche communities",
    "💡 Check the dashboard daily — best leads appear within hours of posting",
]


def get_suggestions(category: str = None, count: int = 5) -> list[str]:
    """Get keyword suggestions. If category provided, return category-specific suggestions."""
    if category and category in KEYWORD_SUGGESTIONS:
        return KEYWORD_SUGGESTIONS[category][:count]

    # Mix from multiple categories
    import random
    all_kw = []
    for kws in KEYWORD_SUGGESTIONS.values():
        all_kw.extend(kws[:3])
    random.shuffle(all_kw)
    return all_kw[:count]


def get_onboarding_tips(count: int = 3) -> list[str]:
    """Get onboarding help tips."""
    import random
    return random.sample(HELP_TIPS, min(count, len(HELP_TIPS)))
