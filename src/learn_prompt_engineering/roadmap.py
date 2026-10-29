"""
The Learning Hub - Prompt Engineering Pedagogical Mastery Roadmap.
7-Stage progression covering in-context learning, CoT reasoning, adversarial defense, and prompt caching.
"""

from typing import List, Dict, Any

PROMPT_ENG_STAGES: List[Dict[str, Any]] = [
    {
        "stage_number": 1,
        "title": "LLM Foundations, Transformer Attention Dynamics & Prompt Anatomy",
        "domain_focus": "Self-attention mechanisms, causal language modeling, tokenization boundaries, and prompt structure.",
        "completed": True,
        "key_topics": ["Attention Heatmaps", "Byte-Pair Encoding (BPE)", "System vs User vs Assistant Turns", "Context Window Limits"]
    },
    {
        "stage_number": 2,
        "title": "In-Context Learning & Fundamental Prompting Strategies",
        "domain_focus": "Zero-shot, one-shot, few-shot prompting, dynamic exemplar selection, and format enforcement.",
        "completed": True,
        "key_topics": ["Few-Shot Exemplar Selection", "Negative Examples vs Positive Guidance", "Role Prompting", "JSON Output Constraints"]
    },
    {
        "stage_number": 3,
        "title": "Advanced Cognitive Architectures & Multi-Step Reasoning",
        "domain_focus": "Chain-of-Thought (CoT), Least-to-Most prompting, Self-Consistency, and Tree-of-Thoughts (ToT).",
        "completed": True,
        "key_topics": ["Step-by-Step Scratchpads", "Tree-of-Thoughts Branch Evaluation", "Self-Consistency Majority Voting", "Reflection Prompts"]
    },
    {
        "stage_number": 4,
        "title": "Production Prompt Architecture, System Instructions & Delimiters",
        "domain_focus": "XML tags (<context>, <rules>), markdown formatting, delimiter isolation, and unambiguous specifications.",
        "completed": True,
        "key_topics": ["XML Structural Delimiters", "Unambiguous Negative Constraints", "Priority Ranking Rules", "Context Anchoring"]
    },
    {
        "stage_number": 5,
        "title": "Adversarial Robustness, Prompt Injections & Jailbreak Defenses",
        "domain_focus": "Direct prompt injection, indirect data poisoning, canary tokens, sandwich defenses, and LLM guardrails.",
        "completed": True,
        "key_topics": ["Canary Token Verification", "Sandwich Defense Pattern", "Delimited Input Sanitization", "Indirect Prompt Injection Mitigations"]
    },
    {
        "stage_number": 6,
        "title": "Programmatic Optimization, Metaprompting & DSPy Compilation",
        "domain_focus": "DSPy teleprompters, BootstrapFewShot, programmatic prompt mutation, and metric-driven optimization.",
        "completed": True,
        "key_topics": ["DSPy Module Architecture", "BootstrapFewShot Optimizer", "Metaprompting Self-Improvement", "Automated Validation Loops"]
    },
    {
        "stage_number": 7,
        "title": "Production Latency, Token Economics, Prompt Caching & Staff Architect Cheatsheet",
        "domain_focus": "Prefix KV-Cache reuse, token pruning, latency budgeting, cost modeling, and 40+ staff interview Q&As.",
        "completed": True,
        "key_topics": ["Prompt Cache Prefix Optimization", "Token Budget Compression", "Sub-100ms TTFT SLAs", "Staff Architecture Cheatsheet"]
    }
]

def get_completed_count() -> int:
    return sum(1 for s in PROMPT_ENG_STAGES if s["completed"])

def get_progress_percentage() -> int:
    return round((get_completed_count() / len(PROMPT_ENG_STAGES)) * 100)
