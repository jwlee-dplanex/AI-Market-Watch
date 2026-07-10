from django.db import migrations


SEED_DATA = [
    {
        "name": "RAG(검색증강생성)",
        "aliases": [
            "RAG", "rag", "검색증강생성", "검색 증강 생성",
            "Retrieval-Augmented Generation", "Retrieval Augmented Generation",
            "retrieval-augmented generation",
        ],
    },
    {
        "name": "온톨로지",
        "aliases": [
            "온톨로지", "ontology", "Ontology", "지식그래프", "지식 그래프",
            "knowledge graph", "Knowledge Graph",
        ],
    },
    {
        "name": "AI Ready Data",
        "aliases": [
            "AI Ready Data", "AI-Ready Data", "AI 레디 데이터", "AI레디데이터",
            "AI 준비 데이터", "데이터 거버넌스", "data governance", "Data Governance",
        ],
    },
    {
        "name": "파인튜닝",
        "aliases": [
            "파인튜닝", "파인 튜닝", "fine-tuning", "fine tuning", "Fine-tuning",
            "Fine-Tuning", "미세조정", "미세 조정",
        ],
    },
    {
        "name": "벡터 검색/임베딩",
        "aliases": [
            "벡터 검색", "벡터검색", "임베딩", "embedding", "Embedding",
            "vector search", "Vector Search", "벡터 데이터베이스", "벡터DB",
            "vector database",
        ],
    },
    {
        "name": "AI 에이전트",
        "aliases": [
            "AI 에이전트", "AI에이전트", "AI agent", "AI Agent", "에이전트 AI",
            "agentic AI", "Agentic AI", "멀티에이전트", "멀티 에이전트",
            "multi-agent",
        ],
    },
    {
        "name": "멀티모달",
        "aliases": [
            "멀티모달", "멀티 모달", "multimodal", "Multimodal", "Multi-modal",
            "다중모달", "다중 모달",
        ],
    },
    {
        "name": "온디바이스 AI",
        "aliases": [
            "온디바이스 AI", "온디바이스AI", "on-device AI", "On-Device AI",
            "on device AI", "엣지 AI", "엣지AI", "edge AI", "Edge AI",
        ],
    },
    {
        "name": "MLOps",
        "aliases": [
            "MLOps", "mlops", "ML Ops", "머신러닝 운영", "엠엘옵스",
            "AIOps", "AI Ops",
        ],
    },
    {
        "name": "AI 거버넌스",
        "aliases": [
            "AI 거버넌스", "AI거버넌스", "AI governance", "AI Governance",
            "책임 AI", "책임있는 AI", "Responsible AI", "AI 윤리", "AI윤리",
            "AI 규제",
        ],
    },
]


def seed_techtopics(apps, schema_editor):
    TechTopic = apps.get_model("setting", "TechTopic")
    for data in SEED_DATA:
        TechTopic.objects.get_or_create(
            name=data["name"],
            defaults={"aliases": data["aliases"]},
        )


def unseed_techtopics(apps, schema_editor):
    TechTopic = apps.get_model("setting", "TechTopic")
    names = [d["name"] for d in SEED_DATA]
    TechTopic.objects.filter(name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("setting", "0009_techtopic"),
    ]

    operations = [
        migrations.RunPython(seed_techtopics, unseed_techtopics),
    ]
